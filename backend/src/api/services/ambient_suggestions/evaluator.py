"""Structured ambient suggestion evaluator."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from api.core.logging.api_logger import api_logger
from api.core.models.model_types import ModelCapability
from api.core.services.model_service import ModelService
from api.core.services.file_storage_service import StorageService

from .models import (
    AmbientCapability,
    AmbientContextEnvelope,
    AmbientEvaluationRequest,
    AmbientEvaluationResponse,
    AmbientRecentActivitySpan,
    AmbientRecentSuggestionContext,
    AmbientSuggestionPayload,
)


@dataclass
class _StructuredEvaluationResult:
    response: AmbientEvaluationResponse
    raw: str
    enforcement_mode: str
    finish_reason: str
    json_chars: int
    trailing_chars: int


class _StructuredEvaluationError(Exception):
    def __init__(self, message: str, *, raw: Optional[str] = None) -> None:
        super().__init__(message)
        self.raw = raw


SUGGESTION_PROMPT = """You are Basil's ambient suggestion evaluator.
Return exactly one JSON object that validates against AmbientEvaluationResponse.
Do not include markdown, bullets, analysis, or prose outside the JSON object.

AmbientEvaluationRequest:
{request_json}

AmbientEvaluationResponse JSON schema:
{response_schema_json}

Rules:
- Default to should_suggest=false unless the visible context clearly supports a useful action.
- Do not force any action category. Classify the scene first, cite visible evidence, then decide.
- For code, terminal, test logs, or IDE contexts, consider explain_error, summarize_visible_code, draft_test, review_visible_change, or no suggestion.
- For requirements/docs/specs, consider complete_section, tighten_requirements, summarize_section, extract_action_items, or no suggestion.
- For browser/research contexts, consider summarize_page, compare_options, extract_notes, or no suggestion.
- Use assistant_session for quick drafting, rewriting, summarizing, explaining, or asking Dill to help with the visible context.
- Use agent_task only for a specific complete task that is safe to launch from the card details without more input.
- Never invent recipients, email bodies, URLs, files, errors, or facts not visible in the context.
- Do not infer intent from stale Ambient panel text, previous suggestion cards, or isolated action words.
- Use recent_suggestions to avoid proposing substantially the same help again; if the best suggestion repeats recent help, return should_suggest=false.
- Use recent_activity_spans only as background for the current visible context, such as recognizing a handoff from recent IDE work into an email or status update.
- Do not suggest based only on history; the current visible context must still support the action.
- Set confidence above the request minimum_confidence only when the visible context strongly supports the action.
- If should_suggest=true, grounding.application, grounding.window_title, and grounding.visible_excerpt must reflect the request.
- If should_suggest=true, evidence must quote specific visible evidence supporting the action.
- If should_suggest=true, visible_context_summary must neutrally summarize the visible screen.
- If should_suggest=true, proposed_request must state the exact request Basil will show the user before launching Dill or Paprika.
- Keep title under 8 words and summary to one sentence.

Examples:
{{"should_suggest": false, "no_suggestion_reason": "No concrete action is visible.", "capability": null, "suggestion_type": "none", "confidence": 0.0, "primary_activity": "unknown", "visible_context_summary": "", "evidence": [], "evidence_sources": [], "title": "", "summary": "", "details": null, "proposed_request": null, "instruction": null, "grounding": null, "auto_execute_eligible": false}}
{{"should_suggest": true, "no_suggestion_reason": null, "capability": "assistant_session", "suggestion_type": "complete_section", "confidence": 0.84, "primary_activity": "writing_document", "visible_context_summary": "A requirements section appears unfinished.", "evidence": ["Visible requirements section ends mid-list"], "evidence_sources": ["ocr_text"], "title": "Complete this section", "summary": "The visible requirements section appears unfinished and can be continued from the surrounding bullets.", "details": "Use only the visible requirements and preserve the existing tone.", "proposed_request": "Complete the visible requirements section based on the surrounding bullets and preserve the existing tone.", "instruction": "Complete the visible requirements section based on the surrounding content.", "grounding": {{"application": "Example editor", "window_title": "Requirements doc", "visible_excerpt": "..."}}, "auto_execute_eligible": false}}
{{"should_suggest": true, "no_suggestion_reason": null, "capability": "assistant_session", "suggestion_type": "explain_error", "confidence": 0.86, "primary_activity": "reviewing_logs", "visible_context_summary": "A failing test or stack trace is visible.", "evidence": ["Visible stack trace includes AssertionError"], "evidence_sources": ["ocr_text", "window_title"], "title": "Explain this failure", "summary": "The visible terminal or editor shows a concrete error that Dill can help diagnose.", "details": "Focus on the visible stack trace or failing test output.", "proposed_request": "Explain the visible failure and suggest the next debugging step.", "instruction": "Explain the visible failure and suggest the next debugging step.", "grounding": {{"application": "Cursor", "window_title": "failing test file", "visible_excerpt": "..."}}, "auto_execute_eligible": false}}
"""


class AmbientSuggestionEvaluator:
    """Ask a lightweight model for a typed suggestion decision."""

    def __init__(self, model_service: ModelService) -> None:
        self.model_service = model_service
        self.logger = api_logger.getChild("ambient_suggestion_evaluator")

    async def evaluate(
        self,
        context: AmbientContextEnvelope,
        *,
        model_id: str,
        minimum_confidence: float = 0.8,
        allowed_capabilities: Optional[list[AmbientCapability]] = None,
        recent_suggestions: Optional[list[AmbientRecentSuggestionContext]] = None,
        recent_activity_spans: Optional[list[AmbientRecentActivitySpan]] = None,
    ) -> AmbientSuggestionPayload:
        """Evaluate whether the current context merits a suggestion."""
        if not context.ocr_text.strip():
            return AmbientSuggestionPayload(should_suggest=False, confidence=0.0)

        request = self._build_evaluation_request(
            context,
            minimum_confidence=minimum_confidence,
            allowed_capabilities=allowed_capabilities,
            recent_suggestions=recent_suggestions,
            recent_activity_spans=recent_activity_spans,
        )
        prompt = SUGGESTION_PROMPT.format(
            request_json=request.model_dump_json(indent=2),
            response_schema_json=json.dumps(AmbientEvaluationResponse.model_json_schema(), ensure_ascii=False, indent=2),
        )
        raw: Optional[str] = None
        try:
            model = await self.model_service.load_model_by_id(model_id, {ModelCapability.REASONING})
            structured_result = await self._generate_structured_evaluation(
                model=model,
                prompt=prompt,
            )
            raw = structured_result.raw
            response = structured_result.response
            self.logger.info(
                "Ambient evaluator received output model=%s capture_id=%s app=%r window=%r mode=%s finish_reason=%s prompt_chars=%d raw_chars=%d json_chars=%d trailing_chars=%d raw_start=%r raw_end=%r",
                model_id,
                context.capture_id,
                context.app_name,
                context.window_title,
                structured_result.enforcement_mode,
                structured_result.finish_reason,
                len(prompt),
                len(raw),
                structured_result.json_chars,
                structured_result.trailing_chars,
                raw[:1500],
                raw[-1500:],
            )
            self.logger.info(
                "Ambient evaluator validated response model=%s capture_id=%s should_suggest=%s suggestion_type=%s capability=%s confidence=%.3f title=%r proposed_request_chars=%d instruction_chars=%d",
                model_id,
                context.capture_id,
                response.should_suggest,
                response.suggestion_type,
                response.capability,
                response.confidence,
                response.title,
                len(response.proposed_request or ""),
                len(response.instruction or ""),
            )
            if response.should_suggest and response.confidence < request.minimum_confidence:
                return AmbientSuggestionPayload(should_suggest=False, confidence=0.0)
            return response.to_payload()
        except Exception as exc:
            if isinstance(exc, _StructuredEvaluationError):
                raw = exc.raw
            if raw is not None:
                artifact_path = self._write_raw_output_artifact(
                    context=context,
                    model_id=model_id,
                    prompt=prompt,
                    raw=raw,
                    error=exc,
                )
                self.logger.error(
                    "Ambient suggestion model evaluation failed for model=%s app=%r window=%r prompt_chars=%d raw_chars=%d raw_start=%r raw_end=%r artifact=%s error=%s",
                    model_id,
                    context.app_name,
                    context.window_title,
                    len(prompt),
                    len(raw),
                    raw[:1000],
                    raw[-1000:],
                    artifact_path,
                    exc,
                    exc_info=True,
                )
            else:
                self.logger.error(
                    "Ambient suggestion model evaluation failed before raw output for model=%s app=%r window=%r error=%s",
                    model_id,
                    context.app_name,
                    context.window_title,
                    exc,
                    exc_info=True,
                )
            return self._fallback_evaluate(context)

    async def _generate_structured_evaluation(
        self,
        *,
        model: Any,
        prompt: str,
    ) -> _StructuredEvaluationResult:
        llama_instance = getattr(model, "llm", None)
        if llama_instance is not None and hasattr(llama_instance, "create_chat_completion"):
            output = await asyncio.to_thread(
                llama_instance.create_chat_completion,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_object",
                    "schema": AmbientEvaluationResponse.model_json_schema(),
                },
                max_tokens=1200,
                temperature=0.05,
                top_p=0.9,
                repeat_penalty=1.15,
            )
            message = output["choices"][0].get("message", {})
            raw = message.get("content") or ""
            finish_reason = output["choices"][0].get("finish_reason", "unknown")
            try:
                response = AmbientEvaluationResponse.model_validate(json.loads(raw))
            except Exception as exc:
                raise _StructuredEvaluationError(str(exc), raw=raw) from exc
            return _StructuredEvaluationResult(
                response=response,
                raw=raw,
                enforcement_mode="llama_cpp_response_format_schema",
                finish_reason=finish_reason,
                json_chars=len(raw),
                trailing_chars=0,
            )

        raw = await model.generate_response(prompt=prompt, max_tokens=900)
        try:
            response = AmbientEvaluationResponse.model_validate(json.loads(raw))
        except Exception as exc:
            raise _StructuredEvaluationError(str(exc), raw=raw) from exc
        return _StructuredEvaluationResult(
            response=response,
            raw=raw,
            enforcement_mode="strict_text_json_fallback",
            finish_reason="unknown",
            json_chars=len(raw),
            trailing_chars=0,
        )

    @staticmethod
    def _build_evaluation_request(
        context: AmbientContextEnvelope,
        *,
        minimum_confidence: float = 0.8,
        allowed_capabilities: Optional[list[AmbientCapability]] = None,
        recent_suggestions: Optional[list[AmbientRecentSuggestionContext]] = None,
        recent_activity_spans: Optional[list[AmbientRecentActivitySpan]] = None,
    ) -> AmbientEvaluationRequest:
        ocr_text = context.ocr_text.strip()
        recent_suggestions = recent_suggestions or []
        return AmbientEvaluationRequest(
            capture_id=context.capture_id,
            captured_at=context.timestamp,
            application=context.app_name,
            window_title=context.window_title,
            ocr_excerpt=ocr_text[:12000],
            ocr_char_count=len(ocr_text),
            structured_context=context.structured_context,
            content_fingerprint=context.content_fingerprint,
            recent_suggestion_types=[suggestion.suggestion_type for suggestion in recent_suggestions],
            previously_rejected=any(suggestion.outcome == "rejected" for suggestion in recent_suggestions),
            recent_suggestions=recent_suggestions,
            recent_activity_spans=recent_activity_spans or [],
            allowed_capabilities=allowed_capabilities or ["assistant_session"],
            minimum_confidence=minimum_confidence,
        )

    def _write_raw_output_artifact(
        self,
        *,
        context: AmbientContextEnvelope,
        model_id: str,
        prompt: str,
        raw: str,
        error: Exception,
    ) -> str:
        debug_dir = StorageService(development_mode=True).base_path / "data" / "debug" / "ambient_evaluator"
        debug_dir.mkdir(parents=True, exist_ok=True)
        safe_model_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_id)[:80]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        artifact_path = debug_dir / f"{timestamp}_{safe_model_id}_{context.capture_id}.json"
        artifact = {
            "timestamp": datetime.now().isoformat(),
            "model_id": model_id,
            "capture_id": context.capture_id,
            "application": context.app_name,
            "window_title": context.window_title,
            "content_fingerprint": context.content_fingerprint,
            "error_type": type(error).__name__,
            "error": str(error),
            "prompt_chars": len(prompt),
            "raw_chars": len(raw),
            "prompt_excerpt": prompt[:4000],
            "raw_output": raw,
        }
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(artifact_path)

    def _fallback_evaluate(self, context: AmbientContextEnvelope) -> AmbientSuggestionPayload:
        """Conservative fallback: structured evaluation failures should not create speculative cards."""
        return AmbientSuggestionPayload(should_suggest=False, confidence=0.0)

    @staticmethod
    def _build_context_text(context: AmbientContextEnvelope, excerpt: str) -> str:
        return (
            f"App: {context.app_name}\n"
            f"Window: {context.window_title}\n"
            f"Visible excerpt:\n{excerpt.strip()}"
        )
