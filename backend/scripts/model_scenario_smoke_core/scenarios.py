"""Per-scenario invokers, success predicates, and applicability rules.

Each ``run_*`` function takes a :class:`ModelCandidate` (already confirmed
available by ``availability.check_availability``) and returns a
:class:`ScenarioOutcome`. Applicability (whether a scenario even makes sense
for a given candidate) is decided by ``applicability_for`` before any of the
``run_*`` functions are called, purely from registry-derived flags -- no
model is ever loaded just to discover it doesn't apply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from api.core.models.base_model import BaseAIModel
from api.core.models.model_invocation import call_model_with_prompt
from api.routes.setup_assistant.models import SetupAgentEventKind, SetupAgentRequest, SetupAssistantPhase
from api.services.meetings.meeting_recorder import MeetingMetadata, MeetingRecorder
from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer

from . import scaffolding
from .registry_enumeration import ModelCandidate

logger = logging.getLogger("model_scenario_smoke.scenarios")

Verdict = Literal["PASS", "FAIL", "SKIP", "N/A"]

SMOKE_TAG = "[model-scenario-smoke]"
_MINIMAL_PROMPT = "Reply with exactly the single word: DONE"
_AGENT_TASK_PROMPT = f"{SMOKE_TAG} Reply with the single word DONE and finalize immediately. Do not use any tools."
_SETUP_WIZARD_MESSAGE = (
    f"{SMOKE_TAG} Run the smallest valid conversational turn: call "
    "narrate_progress once, then call say with a brief greeting and stop. Do not call "
    "discovery, observations, chips, proposals, actions, or any other tool."
)

AGENT_TASK_SUBMIT_TIMEOUT_SECONDS = 30.0
AGENT_TASK_POLL_INTERVAL_SECONDS = 2.0
AGENT_TASK_POLL_TIMEOUT_SECONDS = 120.0
AGENT_TASK_STATUS_CHECK_TIMEOUT_SECONDS = 10.0
SETUP_WIZARD_TURN_TIMEOUT_SECONDS = 90.0

# Substrings that mark an error as transient *infrastructure unavailability*
# (the auth proxy / routing service being down), not "this model mishandles
# this scenario". These map to SKIP, not FAIL, so an intermittent 502 from the
# auth service never flips an otherwise-healthy cell red -- matching the
# availability gate's semantics (unavailable now != broken handling).
_INFRA_UNAVAILABLE_MARKERS = (
    "auth service error (502",
    "auth service error (503",
    "502 bad gateway",
    "503 service unavailable",
    "application failed to respond",
    "upstream error",
    "client_unavailable",
    "no basil client is connected",
)


def _infra_unavailable_reason(message: Optional[str]) -> Optional[str]:
    """Return the message if it looks like transient infra unavailability, else None."""
    if not message:
        return None
    lowered = message.lower()
    if any(marker in lowered for marker in _INFRA_UNAVAILABLE_MARKERS):
        return message
    return None


@dataclass
class ScenarioOutcome:
    verdict: Verdict
    detail: str = ""

    @staticmethod
    def ok(detail: str = "") -> "ScenarioOutcome":
        return ScenarioOutcome("PASS", detail)

    @staticmethod
    def fail(detail: str) -> "ScenarioOutcome":
        return ScenarioOutcome("FAIL", detail)

    @staticmethod
    def skip(detail: str) -> "ScenarioOutcome":
        return ScenarioOutcome("SKIP", detail)

    @staticmethod
    def na(detail: str) -> "ScenarioOutcome":
        return ScenarioOutcome("N/A", detail)


# ---------------------------------------------------------------------------
# Applicability -- derived purely from registry flags, no model load required.
# ---------------------------------------------------------------------------

TOOL_FAMILY_SCENARIO_IDS = (
    "tool_file", "tool_email", "tool_browser", "tool_vision", "tool_shell",
    "tool_automation", "tool_external", "tool_memory", "tool_schedule",
    "tool_activity", "tool_recall", "tool_iterative",
)
MIXED_TOOL_SCENARIO_IDS = (
    "mixed_email_file", "mixed_file_shell", "mixed_browser_vision",
    "mixed_automation_activity", "mixed_recall_schedule", "mixed_memory_external",
)
SCENARIOS = (
    "assistant_session", "meeting_analysis", "agent_task", "setup_wizard",
    *TOOL_FAMILY_SCENARIO_IDS, *MIXED_TOOL_SCENARIO_IDS,
)


def applicability_for(candidate: ModelCandidate) -> Dict[str, Optional[str]]:
    """Return {scenario_id: None} when applicable, or {scenario_id: "N/A reason"} when not.

    Mirrors the plan's applicability matrix:
    - generate_response scenarios (Assistant Session, Meeting Analysis): every reasoning model.
    - tool-calling scenarios (AgentTask): require FUNCTION_CALLING.
    - Setup Wizard: local models, or cloud models the registry marks proxy-compatible
      (``supports_openrouter_proxy``); direct-key-only cloud models are N/A because
      SetupAgentRuntime's model builder only ever produces local or AuthProxy LLMs.
    """
    result: Dict[str, Optional[str]] = {scenario: None for scenario in SCENARIOS}

    if not candidate.supports_function_calling:
        result["agent_task"] = "model lacks function_calling feature"
        for scenario in (*TOOL_FAMILY_SCENARIO_IDS, *MIXED_TOOL_SCENARIO_IDS):
            result[scenario] = "model lacks function_calling feature"

    if not (candidate.is_local or candidate.supports_openrouter_proxy):
        result["setup_wizard"] = (
            "SetupAgentRuntime only builds local or OpenRouter/AuthProxy LLMs; "
            "this model is direct-key-only cloud"
        )
    elif not candidate.supports_function_calling:
        result["setup_wizard"] = "model lacks function_calling feature"

    return result


# ---------------------------------------------------------------------------
# Assistant Session -- direct model.generate_response, the same model layer
# AssistantSessionService.generate_suggestion() calls after resolving a model.
# ---------------------------------------------------------------------------

async def run_assistant_session(model: BaseAIModel, candidate: ModelCandidate) -> ScenarioOutcome:
    try:
        response = await call_model_with_prompt(
            model,
            prompt=_MINIMAL_PROMPT,
            enable_web_search=False,
        )
    except Exception as exc:
        return ScenarioOutcome.fail(f"generate_response raised: {exc}")
    if not isinstance(response, str) or not response.strip():
        return ScenarioOutcome.fail(f"generate_response returned empty/non-string result: {response!r}")
    return ScenarioOutcome.ok(f"{len(response)} chars")


# ---------------------------------------------------------------------------
# Meeting Analysis -- exercises MeetingAnalyzer.analyze against a synthetic
# transcript so analyzer-specific prompt/format handling is caught, not just
# the shared generate_response layer underneath it.
# ---------------------------------------------------------------------------

def _write_fake_meeting(meeting_id: str) -> Path:
    meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
    meeting_dir.mkdir(parents=True, exist_ok=True)

    metadata = MeetingMetadata(
        id=meeting_id,
        name=f"{SMOKE_TAG} synthetic meeting",
        start_time=datetime.now(timezone.utc).isoformat(),
        audio_source="Smoke Test",
    )
    (meeting_dir / "metadata.json").write_text(json.dumps(metadata.to_dict(), indent=2))

    transcript = {
        "segments": [
            {"start": 0.0, "end": 1.8, "text": "Hello, this is a quick smoke test meeting.", "speaker": "Speaker 1"},
            {"start": 1.8, "end": 3.4, "text": "Let's confirm the summary analysis works end to end.", "speaker": "Speaker 1"},
        ]
    }
    (meeting_dir / "transcript.json").write_text(json.dumps(transcript, indent=2))
    return meeting_dir


async def run_meeting_analysis(candidate: ModelCandidate) -> ScenarioOutcome:
    meeting_id = f"smoke-{uuid.uuid4().hex[:10]}"
    meeting_dir = _write_fake_meeting(meeting_id)
    try:
        analyzer = MeetingAnalyzer(meeting_id=meeting_id, model_id=candidate.model_id)
        result = await analyzer.analyze(modes=["summary"])
    except Exception as exc:
        return ScenarioOutcome.fail(f"MeetingAnalyzer.analyze raised: {exc}")
    finally:
        shutil.rmtree(meeting_dir, ignore_errors=True)

    if result is None:
        return ScenarioOutcome.fail("analyze() returned None")
    return ScenarioOutcome.ok("analysis completed")


# ---------------------------------------------------------------------------
# AgentTask -- AgentTaskSubmissionService.process_agent_task_direct. This
# entry point always runs asynchronously (synchronous=False is hardcoded in
# _process_agent_task_direct_impl), so completion is observed by polling
# get_agent_task_status via the state machine's DB-driven background
# processing rather than by awaiting the initial call.
# ---------------------------------------------------------------------------

async def run_agent_task(candidate: ModelCandidate) -> ScenarioOutcome:
    service = scaffolding.get_agent_task_submission_service()
    try:
        result = await asyncio.wait_for(
            service.process_agent_task_direct(
                agent_task=_AGENT_TASK_PROMPT,
                model_id=candidate.model_id,
            ),
            timeout=AGENT_TASK_SUBMIT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return ScenarioOutcome.fail(f"process_agent_task_direct did not return within {AGENT_TASK_SUBMIT_TIMEOUT_SECONDS:.0f}s")
    except Exception as exc:
        return ScenarioOutcome.fail(f"process_agent_task_direct raised: {exc}")

    if not result.get("success", True) and result.get("status") == "failed":
        return ScenarioOutcome.fail(f"submission failed before routing: {result.get('error') or result.get('message')}")

    agent_task_id = result.get("agent_task_id")
    if not agent_task_id:
        return ScenarioOutcome.fail(f"no agent_task_id in submission result: {result}")

    # Each poll is individually bounded: process_agent_task_direct fires a
    # fire-and-forget title-generation call on the same model (with web
    # search enabled) that can run long or stall; a hang in *that*
    # unrelated background call must never defeat this loop's own deadline.
    deadline = asyncio.get_event_loop().time() + AGENT_TASK_POLL_TIMEOUT_SECONDS
    last_status: Optional[Dict[str, Any]] = None
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(AGENT_TASK_POLL_INTERVAL_SECONDS)
        try:
            last_status = await asyncio.wait_for(
                service.agent_task_orchestrator.get_agent_task_status(agent_task_id),
                timeout=AGENT_TASK_STATUS_CHECK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("get_agent_task_status timed out for %s; retrying until the outer deadline", agent_task_id)
            continue
        except Exception as exc:
            return ScenarioOutcome.fail(f"get_agent_task_status raised: {exc}")
        if last_status and last_status.get("status") in {"completed", "failed", "error", "cancelled"}:
            break

    if not last_status:
        return ScenarioOutcome.fail(f"agent_task {agent_task_id} never appeared in the db")
    if last_status.get("status") == "completed":
        return ScenarioOutcome.ok(f"agent_task_id={agent_task_id}")
    if last_status.get("status") in {"failed", "error"}:
        return ScenarioOutcome.fail(f"agent_task {agent_task_id} ended status={last_status.get('status')}")
    return ScenarioOutcome.fail(f"agent_task {agent_task_id} did not reach a terminal status within {AGENT_TASK_POLL_TIMEOUT_SECONDS:.0f}s (last={last_status.get('status')})")


# ---------------------------------------------------------------------------
# Setup Wizard -- SetupAgentRuntime.respond_stream.
# ---------------------------------------------------------------------------

async def run_setup_wizard(candidate: ModelCandidate) -> ScenarioOutcome:
    runtime = scaffolding.get_setup_agent_runtime()
    request = SetupAgentRequest(
        latest_message=_SETUP_WIZARD_MESSAGE,
        phase=SetupAssistantPhase.agent_synthesis,
        setup_agent_model_override_id=candidate.model_id,
    )

    saw_content = False
    saw_error: Optional[str] = None
    try:
        async with asyncio.timeout(SETUP_WIZARD_TURN_TIMEOUT_SECONDS):
            async for event in runtime.respond_stream(request):
                if event.kind == SetupAgentEventKind.error:
                    payload = event.payload if isinstance(event.payload, dict) else {}
                    saw_error = str(payload.get("message", event.payload))
                elif event.kind in {SetupAgentEventKind.message_delta, SetupAgentEventKind.message_completed}:
                    saw_content = True
                if event.kind == SetupAgentEventKind.turn_complete:
                    break
    except TimeoutError:
        return ScenarioOutcome.fail(f"respond_stream did not complete within {SETUP_WIZARD_TURN_TIMEOUT_SECONDS:.0f}s")
    except Exception as exc:
        return ScenarioOutcome.fail(f"respond_stream raised: {exc}")

    infra_reason = _infra_unavailable_reason(saw_error)
    if infra_reason:
        return ScenarioOutcome.skip(f"auth/routing infra unavailable: {infra_reason}")
    if saw_error:
        return ScenarioOutcome.fail(f"turn emitted an error event: {saw_error}")
    if not saw_content:
        return ScenarioOutcome.fail("turn completed with no message content")
    return ScenarioOutcome.ok("stream completed with content")
