"""Prompt-based model invocation that respects registry-declared features.

``enable_web_search`` is a cloud-only kwarg: only models whose registry entry
declares ``ModelFeature.WEB_SEARCH`` accept it (see cloud_reasoning_registry).
Local handlers (llama_cpp, qwen, deepseek, ...) omit it from their signature,
so passing it raises TypeError. Omitting it is safe for every model because
each declares its own default, which is why this module only ever adds the
kwarg when support is proven.

The messages-based agent path has an equivalent guard in
agent_processing/.../agent_model_caller.py; that module is intentionally left
independent because it serves the agent execution graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel

from api.core.models.models_registry import (
    ModelFeature,
    apply_request_parameter_omissions,
    get_omitted_request_parameters,
    has_feature,
)
from api.core.models.reasoning.model_runtime_profile import (
    resolve_runtime_model_profile,
)
from api.core.models.reasoning.streaming_contract import GenerationPurpose

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_BREAK = "\n\n<<BASIL_CACHE_BREAK>>\n\n"
CACHE_BREAK_TOKEN = ANALYSIS_CACHE_BREAK.strip()
TextDeltaCallback = Callable[[str], Awaitable[None]]


def split_cache_break(prompt: str) -> tuple[str, Optional[str]]:
    """Split a prompt at the first cache-break marker into (stable prefix, task suffix)."""
    if ANALYSIS_CACHE_BREAK not in prompt:
        return prompt, None
    prefix, _, suffix = prompt.partition(ANALYSIS_CACHE_BREAK)
    return prefix, suffix


def flatten_cache_break(prompt: str) -> str:
    """Replace every cache-break marker with a plain blank line."""
    return prompt.replace(ANALYSIS_CACHE_BREAK, "\n\n")


async def _forward_text_delta(callback: TextDeltaCallback, text: str) -> None:
    """Deliver one streamed delta; a failing consumer must never fail the model call."""
    try:
        await callback(text)
    except Exception:
        logger.warning("Streaming text-delta consumer failed", exc_info=True)


def _extract_usage(response: Any) -> Optional[dict[str, int]]:
    """Collect integer token counts a provider reports, ignoring anything else."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    counts: dict[str, int] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = getattr(usage, key, None)
        if isinstance(value, int) and not isinstance(value, bool):
            counts[key] = value
    for details_name in ("prompt_tokens_details", "input_tokens_details"):
        cached = getattr(getattr(usage, details_name, None), "cached_tokens", None)
        if isinstance(cached, int) and not isinstance(cached, bool):
            counts["cached_tokens"] = cached
    return counts or None


def supports_web_search(model: Any) -> bool:
    """Return True when the model can accept ``enable_web_search`` on generate_response."""
    probe = getattr(model, "_supports_web_search", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False

    model_name = getattr(model, "model_name", getattr(model, "name", None))
    if not model_name:
        return False
    try:
        return has_feature(str(model_name), ModelFeature.WEB_SEARCH)
    except Exception:
        return False


def supports_system_prompt(model: Any) -> bool:
    """Return True when the model can accept a real system-role message.

    Cloud OpenAI/Anthropic/Gemini handlers (and any auth-proxy wrapping of
    them, since the registry's declared handler is unchanged either way)
    already read ``context["system_prompt"]`` in their ``generate_response``.
    Custom OpenAI-compatible models gate on their own registry-declared
    ``system_prompts`` feature. Everything else (local llama.cpp/huggingface)
    is not proven to support it, so callers fall back to folding the text
    into the flat prompt.
    """
    probe = getattr(model, "_supports_system_prompt", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    profile = resolve_runtime_model_profile(model)
    if profile.handler in {"openai_api", "anthropic_api", "gemini_api"}:
        return True
    model_name = getattr(model, "model_name", getattr(model, "name", None))
    if not model_name:
        return False
    try:
        return has_feature(str(model_name), ModelFeature.SYSTEM_PROMPTS)
    except Exception:
        return False


async def call_model_with_prompt(
    model: Any,
    *,
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    enable_web_search: bool = False,
    purpose: GenerationPurpose = "general",
    on_local_generation_telemetry: Optional[Callable[[Any], None]] = None,
) -> str:
    """Invoke ``generate_response`` with only kwargs the model supports.

    ``system_prompt`` is optional and additive: existing callers that never
    pass it see identical behavior to before this parameter existed.
    """
    effective_prompt = prompt
    context: Optional[dict[str, Any]] = None
    if system_prompt:
        if supports_system_prompt(model):
            context = {"system_prompt": system_prompt}
        else:
            effective_prompt = f"{system_prompt}\n\n{prompt}"
    kwargs: dict[str, Any] = {"prompt": effective_prompt}
    if context is not None:
        kwargs["context"] = context
    profile = resolve_runtime_model_profile(model)
    if (
        getattr(profile, "location", None) == "local"
        and getattr(profile, "handler", None) in {"llama_cpp", "huggingface"}
    ):
        from api.core.models.reasoning.streaming_contract import resolve_generation_budget

        local_budget = resolve_generation_budget(
            model,
            purpose=purpose,
            requested_output_tokens=max_tokens,
        )
        kwargs["max_tokens"] = local_budget.effective_output_tokens
        if getattr(profile, "handler", None) == "llama_cpp" and on_local_generation_telemetry is not None:
            kwargs["telemetry_callback"] = on_local_generation_telemetry
    elif max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if supports_web_search(model):
        kwargs["enable_web_search"] = enable_web_search
    return await model.generate_response(**kwargs)


StructuredOutputEnforcement = Literal[
    "llama_cpp_json_schema",
    "openai_responses_parse",
    "openai_chat_parse",
    "anthropic_output_format",
    "gemini_response_schema",
    "strict_json_fallback",
]

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredModelResponse(Generic[ResponseModelT]):
    """One schema-validated model response and its enforcement provenance."""

    value: ResponseModelT
    enforcement: StructuredOutputEnforcement
    finish_reason: Optional[str] = None
    usage: Optional[dict[str, int]] = None


class StructuredModelOutputError(RuntimeError):
    """Raised when structured generation cannot produce a complete valid value."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        retryable: bool = False,
        refusal_category: Optional[str] = None,
        refusal_explanation: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.refusal_category = refusal_category
        self.refusal_explanation = refusal_explanation


async def call_model_with_schema(
    model: Any,
    *,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
    on_text_delta: Optional[TextDeltaCallback] = None,
) -> StructuredModelResponse[ResponseModelT]:
    """Generate one object-root response without prose/markdown extraction.

    A prompt may contain ``ANALYSIS_CACHE_BREAK``; only Anthropic uses it (as an
    explicit cache breakpoint), every other provider sees a blank line instead.
    ``on_text_delta`` receives raw streamed JSON text where the provider supports
    streaming and is silently unused elsewhere.
    """
    profile = resolve_runtime_model_profile(model)
    cache_prefix, cache_suffix = split_cache_break(prompt)
    flat_prompt = flatten_cache_break(prompt)
    try:
        if profile.handler == "llama_cpp":
            return await _call_llama_cpp_with_schema(
                model, flat_prompt, response_model, max_tokens
            )
        if profile.handler == "openai_api":
            return await _call_openai_with_schema(
                model,
                flat_prompt,
                response_model,
                max_tokens,
                on_text_delta=on_text_delta,
            )
        if profile.handler == "anthropic_api":
            return await _call_anthropic_with_schema(
                model,
                flat_prompt,
                response_model,
                max_tokens,
                cache_prefix=cache_prefix,
                cache_suffix=cache_suffix,
                on_text_delta=on_text_delta,
            )
        if profile.handler == "gemini_api":
            return await _call_gemini_with_schema(
                model, flat_prompt, response_model, max_tokens
            )
        return await _call_strict_json_fallback(
            model, flat_prompt, response_model, max_tokens
        )
    except StructuredModelOutputError:
        raise
    except Exception as exc:
        category, retryable = _classify_provider_exception(exc)
        raise StructuredModelOutputError(
            "Structured generation failed for "
            f"model={profile.model_id} schema={response_model.__name__} "
            f"handler={profile.handler or 'unknown'}: {type(exc).__name__}: {exc}",
            category=category,
            retryable=retryable,
        ) from exc


def _classify_provider_exception(exc: Exception) -> tuple[str, bool]:
    """Classify provider transport failures without provider-specific imports."""
    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(exc, "code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        if status_code in {401, 403}:
            return ("authentication", False)
        if status_code in {408, 409, 425, 429} or status_code >= 500:
            return ("transient", True)
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return ("transient", True)
    message = str(exc).lower()
    if "invalid json" in message and (
        "eof while parsing" in message
        or "input_value=''" in message
        or 'input_value=""' in message
    ):
        return ("transient", True)
    return ("provider", False)


async def _call_llama_cpp_with_schema(
    model: Any,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
) -> StructuredModelResponse[ResponseModelT]:
    if getattr(model, "llm", None) is None:
        await model.load()
    output = await asyncio.to_thread(
        model.llm.create_chat_completion,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_object",
            "schema": response_model.model_json_schema(),
        },
        max_tokens=max_tokens,
        temperature=0.1,
        top_p=getattr(model, "top_p", 0.9),
        repeat_penalty=1.1,
    )
    choice = output["choices"][0]
    finish_reason = str(choice.get("finish_reason") or "unknown")
    _reject_incomplete_finish_reason(
        finish_reason,
        enforcement="llama_cpp_json_schema",
    )
    raw = choice.get("message", {}).get("content") or ""
    return StructuredModelResponse(
        value=_validate_exact_json(raw, response_model),
        enforcement="llama_cpp_json_schema",
        finish_reason=finish_reason,
    )


async def _call_openai_with_schema(
    model: Any,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
    on_text_delta: Optional[TextDeltaCallback] = None,
) -> StructuredModelResponse[ResponseModelT]:
    if getattr(model, "_async_client", None) is None:
        await model.load()
    if model._requires_responses_api():
        reasoning_effort = model._get_reasoning_effort()
        kwargs: dict[str, Any] = {
            "model": model.model_name,
            "input": prompt,
            "max_output_tokens": min(max_tokens, model.max_output_tokens),
            "text_format": response_model,
        }
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if on_text_delta is not None:
            async with model._async_client.responses.stream(**kwargs) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "response.output_text.delta":
                        await _forward_text_delta(on_text_delta, event.delta)
                response = await stream.get_final_response()
        else:
            response = await model._async_client.responses.parse(**kwargs)
        finish_reason = str(getattr(response, "status", None) or "completed")
        if finish_reason not in {"completed", "success"}:
            raise StructuredModelOutputError(
                f"OpenAI Responses API ended with status={finish_reason}"
            )
        value = getattr(response, "output_parsed", None)
        if value is None:
            raise StructuredModelOutputError(
                "OpenAI Responses API returned no parsed output"
            )
        return StructuredModelResponse(
            value=response_model.model_validate(value),
            enforcement="openai_responses_parse",
            finish_reason=finish_reason,
            usage=_extract_usage(response),
        )

    chat_kwargs: dict[str, Any] = {
        "model": model.model_name,
        "messages": [
            {"role": "system", "content": "Return the requested structured analysis."},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": min(max_tokens, model.max_output_tokens),
        "response_format": response_model,
    }
    if on_text_delta is not None:
        async with model._async_client.chat.completions.stream(**chat_kwargs) as stream:
            async for event in stream:
                if getattr(event, "type", None) == "content.delta":
                    await _forward_text_delta(on_text_delta, event.delta)
            response = await stream.get_final_completion()
    else:
        response = await model._async_client.chat.completions.parse(**chat_kwargs)
    choice = response.choices[0]
    finish_reason = str(choice.finish_reason or "unknown")
    _reject_incomplete_finish_reason(
        finish_reason,
        enforcement="openai_chat_parse",
    )
    value = getattr(choice.message, "parsed", None)
    if value is None:
        raise StructuredModelOutputError(
            "OpenAI Chat Completions returned no parsed output"
        )
    return StructuredModelResponse(
        value=response_model.model_validate(value),
        enforcement="openai_chat_parse",
        finish_reason=finish_reason,
        usage=_extract_usage(response),
    )


async def _call_anthropic_with_schema(
    model: Any,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
    cache_prefix: Optional[str] = None,
    cache_suffix: Optional[str] = None,
    on_text_delta: Optional[TextDeltaCallback] = None,
) -> StructuredModelResponse[ResponseModelT]:
    if getattr(model, "_async_client", None) is None:
        await model.load()
    api_params: dict[str, Any] = {
        "model": model._get_base_model_id(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": min(max_tokens, model.max_output_tokens),
        "temperature": model.temperature,
        "output_format": response_model,
    }
    if cache_prefix and cache_suffix is not None:
        api_params["messages"] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": cache_prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": cache_suffix},
                ],
            }
        ]
    api_params = apply_request_parameter_omissions(
        api_params,
        get_omitted_request_parameters(model.model_name),
    )
    model._apply_thinking_to_api_params(api_params)

    if (
        threading.current_thread().name.startswith("ThreadPoolExecutor")
        or "run_agent_task_in_thread" in threading.current_thread().name
    ):
        with model._client.messages.stream(**api_params) as stream:
            response = stream.get_final_message()
    else:
        async with model._async_client.messages.stream(**api_params) as stream:
            if on_text_delta is not None:
                async for text in stream.text_stream:
                    await _forward_text_delta(on_text_delta, text)
            response = await stream.get_final_message()

    finish_reason = str(getattr(response, "stop_reason", None) or "unknown")
    refusal_details = getattr(response, "stop_details", None)
    if isinstance(refusal_details, dict):
        refusal_category = refusal_details.get("category")
        refusal_explanation = refusal_details.get("explanation")
    else:
        refusal_category = getattr(refusal_details, "category", None)
        refusal_explanation = getattr(refusal_details, "explanation", None)
    _reject_incomplete_finish_reason(
        finish_reason,
        enforcement="anthropic_output_format",
        refusal_category=refusal_category if isinstance(refusal_category, str) else None,
        refusal_explanation=(
            refusal_explanation if isinstance(refusal_explanation, str) else None
        ),
    )
    value = getattr(response, "parsed_output", None)
    if value is None:
        raise StructuredModelOutputError(
            "Anthropic returned no parsed output"
        )
    return StructuredModelResponse(
        value=response_model.model_validate(value),
        enforcement="anthropic_output_format",
        finish_reason=finish_reason,
        usage=_extract_usage(response),
    )


async def _call_gemini_with_schema(
    model: Any,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
) -> StructuredModelResponse[ResponseModelT]:
    if getattr(model, "_client", None) is None:
        await model.load()
    if getattr(model, "_client", None) is None:
        raise StructuredModelOutputError(
            "Gemini client is unavailable: "
            f"{getattr(model, '_error', None) or 'model failed to load'}",
            category="provider",
        )
    config = model._build_generation_config(
        max_tokens,
        response_mime_type="application/json",
        response_json_schema=response_model.model_json_schema(),
    )
    response = await asyncio.to_thread(
        model._client.models.generate_content,
        model=model.model_name,
        contents=prompt,
        config=config,
    )
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise StructuredModelOutputError("Gemini returned no candidates")
    candidate = candidates[0]
    raw_finish_reason = getattr(candidate, "finish_reason", None)
    finish_reason = str(
        getattr(raw_finish_reason, "name", None)
        or raw_finish_reason
        or "unknown"
    )
    if finish_reason.upper() not in {"STOP", "1"}:
        raise StructuredModelOutputError(
            f"Gemini ended with finish_reason={finish_reason}"
        )
    return StructuredModelResponse(
        value=_validate_exact_json(response.text or "", response_model),
        enforcement="gemini_response_schema",
        finish_reason=finish_reason,
    )


async def _call_strict_json_fallback(
    model: Any,
    prompt: str,
    response_model: type[ResponseModelT],
    max_tokens: int,
) -> StructuredModelResponse[ResponseModelT]:
    raw = await call_model_with_prompt(
        model,
        prompt=prompt,
        max_tokens=max_tokens,
        enable_web_search=False,
    )
    return StructuredModelResponse(
        value=_validate_exact_json(raw, response_model),
        enforcement="strict_json_fallback",
        finish_reason=None,
    )


def _validate_exact_json(
    raw: str,
    response_model: type[ResponseModelT],
) -> ResponseModelT:
    try:
        return response_model.model_validate(json.loads(raw))
    except Exception as exc:
        raise StructuredModelOutputError(
            f"Output did not validate as exact {response_model.__name__}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _reject_incomplete_finish_reason(
    finish_reason: str,
    *,
    enforcement: StructuredOutputEnforcement,
    refusal_category: Optional[str] = None,
    refusal_explanation: Optional[str] = None,
) -> None:
    normalized = finish_reason.strip().lower()
    if normalized in {"stop", "end_turn", "completed", "success"}:
        return
    if normalized in {
        "length",
        "max_tokens",
        "max_output_tokens",
    }:
        raise StructuredModelOutputError(
            f"{enforcement} ended incompletely: finish_reason={finish_reason}",
            category="output_limit",
            retryable=False,
        )
    if normalized in {"cancelled", "canceled"}:
        raise StructuredModelOutputError(
            f"{enforcement} ended incompletely: finish_reason={finish_reason}",
            category="canceled",
            retryable=False,
        )
    if normalized in {"refusal", "safety", "content_filter"}:
        raise StructuredModelOutputError(
            f"{enforcement} ended incompletely: finish_reason={finish_reason}",
            category="safety",
            retryable=False,
            refusal_category=refusal_category,
            refusal_explanation=refusal_explanation,
        )
    if normalized in {"error", "failed"}:
        raise StructuredModelOutputError(
            f"{enforcement} ended incompletely: finish_reason={finish_reason}",
            category="provider",
            retryable=False,
        )
    raise StructuredModelOutputError(
        f"{enforcement} ended incompletely: finish_reason={finish_reason}",
        category="provider",
        retryable=False,
    )
