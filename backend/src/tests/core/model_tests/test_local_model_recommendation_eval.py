"""Opt-in local model evaluation for choosing Basil's recommended GGUF model.

Run explicitly:

    RUN_LOCAL_MODEL_EVALS=1 poetry run pytest \
        backend/src/tests/core/model_tests/test_local_model_recommendation_eval.py -s

These tests intentionally load multi-GB local models and are skipped by default.
They are designed to answer whether Qwen3.5 4B should replace Qwen3 8B as the
recommended local reasoning model.
"""

from __future__ import annotations

import gc
import json
import os
import re
import time
import traceback
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from api.core.models.model_downloader import ModelDownloader
from api.core.models.model_manager import ModelManager
from api.core.models.model_types import ModelCapability
from api.core.models.models_registry import get_model
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel, _MODEL_CACHE
from api.core.models.reasoning.model_runtime_profile import (
    TOOL_RENDERING_SLIM_SCHEMA,
    resolve_runtime_model_profile,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
)
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LlamaCppLangChainAdapter,
)
from api.settings import get_models_dir


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_MODEL_EVALS") != "1",
    reason="Set RUN_LOCAL_MODEL_EVALS=1 to load and evaluate local GGUF models.",
)


CANDIDATE_MODEL_ID = "Qwen-qwen35-4b-q4km"
CURRENT_DEFAULT_MODEL_ID = "Qwen-qwen3-8b-instruct-q4km"
DEFAULT_MODEL_IDS = [CANDIDATE_MODEL_ID, CURRENT_DEFAULT_MODEL_ID]
OPTIONAL_CODER_EVAL_IDS = [
    "Qwen-qwen3-coder-30b-a3b-instruct-q4km",
    "Qwen-qwen3-coder-next-q4km",
]
CHAT_MARKERS = ("<think>", "</think>", "<|im_start|>", "<|im_end|>")


class RecordResultInput(BaseModel):
    value: str = Field(description="The exact value to record.")


def record_result(value: str) -> str:
    return value


def get_current_project() -> str:
    return "Basil"


def _selected_model_ids() -> List[str]:
    raw = os.getenv("LOCAL_MODEL_EVAL_IDS")
    if not raw:
        return DEFAULT_MODEL_IDS
    selected = [model_id.strip() for model_id in raw.split(",") if model_id.strip()]
    for model_id in selected:
        if model_id in OPTIONAL_CODER_EVAL_IDS:
            assert get_model(model_id) is not None
    return selected


def _split_model_id(model_id: str) -> tuple[str, str]:
    return model_id.split("-", 1) if "-" in model_id else (model_id, model_id)


def _installed_variant(installed: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    provider, variant = _split_model_id(model_id)
    return installed.get(provider, {}).get("variants", {}).get(variant)


def _chatml(system_prompt: str, user_prompt: str) -> str:
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _json_object_from_text(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _has_chat_marker_leak(text: str) -> bool:
    return any(marker in text for marker in CHAT_MARKERS)


def _approx_token_count(model: LlamaCppModel, text: str) -> Optional[int]:
    try:
        return len(model.llm.tokenize(text.encode("utf-8")))
    except Exception:
        return None


def _safe_size_gb(model_id: str) -> Optional[float]:
    cfg = get_model(model_id) or {}
    raw = str(cfg.get("size") or "").strip().upper().replace("GB", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _build_model_manager(models_dir: Path, model_ids: List[str]) -> ModelManager:
    manager = ModelManager(models_dir, default_idle_seconds=3600)
    for model_id in model_ids:
        provider, _ = _split_model_id(model_id)
        manager.register_model_class(provider, LlamaCppModel)
    return manager


async def _load_model_for_eval(
    manager: ModelManager,
    model_id: str,
) -> tuple[LlamaCppModel, Dict[str, Any]]:
    provider, _ = _split_model_id(model_id)

    cold_start = time.perf_counter()
    model = await manager.load_model(
        model_name=model_id,
        model_type=provider,
        required_capabilities={ModelCapability.REASONING},
    )
    cold_load_seconds = time.perf_counter() - cold_start

    warm_start = time.perf_counter()
    warm_model = await manager.load_model(
        model_name=model_id,
        model_type=provider,
        required_capabilities={ModelCapability.REASONING},
    )
    warm_load_seconds = time.perf_counter() - warm_start

    assert model is warm_model
    assert isinstance(model, LlamaCppModel)

    cfg = get_model(model_id)
    assert cfg is not None

    trained_context = model._read_gguf_metadata_context_or_none()
    if trained_context is not None:
        assert int(cfg["context_window"]) <= trained_context

    return model, {
        "cold_load_seconds": cold_load_seconds,
        "warm_load_seconds": warm_load_seconds,
        "trained_context": trained_context,
        "loaded_context": getattr(model, "max_context_length", None),
    }


async def _measure_prompt(
    model: LlamaCppModel,
    name: str,
    prompt: str,
    max_tokens: int,
    checker,
) -> Dict[str, Any]:
    started = time.perf_counter()
    response = await model.generate_response(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.1,
        top_p=0.95,
    )
    elapsed = time.perf_counter() - started
    approx_tokens = _approx_token_count(model, response)

    passed, details = checker(response)
    marker_leak = _has_chat_marker_leak(response)

    return {
        "name": name,
        "passed": bool(passed and not marker_leak),
        "checker_passed": bool(passed),
        "marker_leak": marker_leak,
        "details": details,
        "elapsed_seconds": elapsed,
        "approx_output_tokens": approx_tokens,
        "approx_tokens_per_second": (
            approx_tokens / elapsed if approx_tokens is not None and elapsed > 0 else None
        ),
        "response_excerpt": response[:500],
    }


def _ok_checker(response: str) -> tuple[bool, str]:
    normalized = response.strip().lower().strip("`'\". ")
    return normalized == "ok", f"normalized={normalized!r}"


def _json_checker(response: str) -> tuple[bool, str]:
    parsed = _json_object_from_text(response)
    if not parsed:
        return False, "no JSON object parsed"
    expected = parsed.get("status") == "ok" and parsed.get("items") == ["alpha", "beta"]
    return expected, f"parsed={parsed!r}"


def _constraint_checker(response: str) -> tuple[bool, str]:
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    bullet_lines = [line for line in lines if line.startswith("-")]
    mentions_forbidden = "cloud" in response.lower()
    passed = len(bullet_lines) == 2 and not mentions_forbidden
    return passed, f"bullet_lines={len(bullet_lines)}, mentions_forbidden={mentions_forbidden}"


def _code_checker(response: str) -> tuple[bool, str]:
    lowered = response.lower()
    passed = bool(response.strip()) and ("return" in lowered or "none" in lowered or "missing" in lowered)
    return passed, f"contains_expected_debug_terms={passed}"


def _long_context_checker(response: str) -> tuple[bool, str]:
    lowered = response.lower()
    expected = ("marigold", "obsidian", "harbor")
    hits = [value for value in expected if value in lowered]
    return len(hits) == len(expected), f"hits={hits}"


def _long_context_prompt() -> str:
    sections = []
    for index in range(1, 90):
        fact = ""
        if index == 3:
            fact = " The alpha sentinel value is marigold."
        elif index == 47:
            fact = " The middle sentinel value is obsidian."
        elif index == 88:
            fact = " The omega sentinel value is harbor."
        sections.append(
            f"Section {index}: Basil local model evaluation filler text. "
            f"This section discusses deterministic model assessment, latency, and reliability.{fact}"
        )
    document = "\n".join(sections)
    return _chatml(
        "Answer from the provided document only. Return one concise sentence.",
        (
            f"{document}\n\n"
            "What are the alpha, middle, and omega sentinel values? "
            "Include all three exact values."
        ),
    )


async def _evaluate_output_quality(model: LlamaCppModel) -> List[Dict[str, Any]]:
    prompts = [
        (
            "exact_ok",
            _chatml("Follow formatting exactly.", "Reply with exactly: ok"),
            16,
            _ok_checker,
        ),
        (
            "json_only",
            _chatml(
                "Return only valid JSON. No prose.",
                'Return exactly this JSON object: {"status":"ok","items":["alpha","beta"]}',
            ),
            80,
            _json_checker,
        ),
        (
            "constraint_following",
            _chatml(
                "Follow every constraint exactly.",
                (
                    "Summarize Basil as a local-first assistant in exactly two bullet lines. "
                    "Do not use the word cloud."
                ),
            ),
            120,
            _constraint_checker,
        ),
        (
            "code_debugging",
            _chatml(
                "Be concise and practical.",
                (
                    "A Python function sometimes returns None unexpectedly:\n"
                    "def pick(items):\n"
                    "    if items:\n"
                    "        return items[0]\n"
                    "Explain the bug and one safe fix in one sentence."
                ),
            ),
            120,
            _code_checker,
        ),
    ]
    return [
        await _measure_prompt(model, name, prompt, max_tokens, checker)
        for name, prompt, max_tokens, checker in prompts
    ]


async def _evaluate_long_context(model: LlamaCppModel) -> Dict[str, Any]:
    return await _measure_prompt(
        model=model,
        name="long_context_sentinel_retrieval",
        prompt=_long_context_prompt(),
        max_tokens=120,
        checker=_long_context_checker,
    )


async def _evaluate_tool_behavior(model: LlamaCppModel, model_id: str) -> Dict[str, Any]:
    profile = resolve_runtime_model_profile(model)
    factory_adapter = create_langchain_llm(
        SimpleNamespace(
            _llm_model=model,
            _websocket_manager=None,
        )
    )
    adapter_is_local = isinstance(factory_adapter, LlamaCppLangChainAdapter)

    if adapter_is_local:
        factory_adapter.max_tokens = 256

    tools = [
        StructuredTool.from_function(
            func=get_current_project,
            name="get_current_project",
            description="Return the current project name.",
        ),
        StructuredTool.from_function(
            func=record_result,
            name="record_result",
            description="Record a final string value for the evaluation.",
            args_schema=RecordResultInput,
        ),
    ]
    bound = factory_adapter.bind_tools(tools)

    started = time.perf_counter()
    result = await bound._agenerate(
        [
            HumanMessage(
                content=(
                    "Use the record_result tool exactly once with value "
                    "'basil-local-eval'. Do not answer in prose."
                )
            )
        ]
    )
    elapsed = time.perf_counter() - started

    message = result.generations[0].message
    tool_calls = getattr(message, "tool_calls", []) or []
    matching_calls = [
        call
        for call in tool_calls
        if call.get("name") == "record_result"
        and call.get("args", {}).get("value") == "basil-local-eval"
    ]

    return {
        "model_id": model_id,
        "adapter_is_local": adapter_is_local,
        "tool_rendering": profile.tool_rendering,
        "tool_rendering_is_slim_schema": profile.tool_rendering == TOOL_RENDERING_SLIM_SCHEMA,
        "elapsed_seconds": elapsed,
        "tool_call_count": len(tool_calls),
        "matching_tool_call_count": len(matching_calls),
        "passed": adapter_is_local and bool(matching_calls),
        "content_excerpt": str(getattr(message, "content", ""))[:500],
        "tool_calls": tool_calls,
    }


def _build_recommendation(results: Dict[str, Any]) -> Dict[str, Any]:
    candidate = results["models"].get(CANDIDATE_MODEL_ID)
    baseline = results["models"].get(CURRENT_DEFAULT_MODEL_ID)
    if not candidate or not baseline:
        return {
            "decision": "defer",
            "reason": "Candidate and current default were not both evaluated.",
        }
    if candidate.get("load_error"):
        return {
            "decision": "do_not_promote",
            "reason": "Candidate failed to load through Basil's local runtime.",
            "candidate_load_error": candidate["load_error"],
            "baseline_load_error": baseline.get("load_error"),
        }
    if baseline.get("load_error"):
        return {
            "decision": "defer",
            "reason": "Current default failed to load, so comparison is inconclusive.",
            "candidate_load_error": candidate.get("load_error"),
            "baseline_load_error": baseline["load_error"],
        }

    candidate_quality = sum(1 for item in candidate.get("quality_prompts", []) if item["passed"])
    baseline_quality = sum(1 for item in baseline.get("quality_prompts", []) if item["passed"])
    candidate_long = bool(candidate.get("long_context", {}).get("passed"))
    baseline_long = bool(baseline.get("long_context", {}).get("passed"))
    candidate_tool = bool(candidate.get("tool_behavior", {}).get("passed"))
    baseline_tool = bool(baseline.get("tool_behavior", {}).get("passed"))

    candidate_generation = [
        item["elapsed_seconds"] for item in candidate.get("quality_prompts", []) if item["elapsed_seconds"]
    ]
    baseline_generation = [
        item["elapsed_seconds"] for item in baseline.get("quality_prompts", []) if item["elapsed_seconds"]
    ]
    candidate_mean = mean(candidate_generation) if candidate_generation else None
    baseline_mean = mean(baseline_generation) if baseline_generation else None
    candidate_size = _safe_size_gb(CANDIDATE_MODEL_ID)
    baseline_size = _safe_size_gb(CURRENT_DEFAULT_MODEL_ID)

    quality_ok = candidate_quality >= baseline_quality
    tool_ok = candidate_tool and (candidate_tool >= baseline_tool)
    long_context_ok = candidate_long or not baseline_long
    size_ok = candidate_size is not None and baseline_size is not None and candidate_size < baseline_size
    speed_ok = (
        candidate_mean is not None
        and baseline_mean is not None
        and candidate_mean <= baseline_mean * 1.25
    )

    if quality_ok and tool_ok and long_context_ok and (size_ok or speed_ok):
        decision = "promote"
        reason = "Candidate met quality/tool/long-context gates and is smaller or comparably fast."
    elif quality_ok and candidate_tool:
        decision = "defer"
        reason = "Candidate passed key behavior gates but did not clearly beat speed/size/long-context criteria."
    else:
        decision = "do_not_promote"
        reason = "Candidate failed one or more key behavior gates."

    return {
        "decision": decision,
        "reason": reason,
        "candidate_quality_passes": candidate_quality,
        "baseline_quality_passes": baseline_quality,
        "candidate_mean_generation_seconds": candidate_mean,
        "baseline_mean_generation_seconds": baseline_mean,
        "candidate_size_gb": candidate_size,
        "baseline_size_gb": baseline_size,
        "candidate_tool_passed": candidate_tool,
        "baseline_tool_passed": baseline_tool,
        "candidate_long_context_passed": candidate_long,
        "baseline_long_context_passed": baseline_long,
    }


def _write_report(report: Dict[str, Any], tmp_path: Path) -> Path:
    env_path = os.getenv("LOCAL_MODEL_EVAL_REPORT")
    report_path = Path(env_path) if env_path else tmp_path / "local_model_recommendation_eval.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report_path


def _release_model_memory(manager: ModelManager, model: LlamaCppModel) -> None:
    model.llm = None
    manager._models.clear()
    _MODEL_CACHE.clear()
    gc.collect()


@pytest.mark.asyncio
async def test_local_model_recommendation_eval(tmp_path: Path) -> None:
    model_ids = _selected_model_ids()
    assert CANDIDATE_MODEL_ID in model_ids, "Evaluation must include the Qwen3.5 4B candidate."

    models_dir = get_models_dir()
    downloader = ModelDownloader(models_dir)
    installed = downloader.get_installed_models()

    missing = [model_id for model_id in model_ids if not _installed_variant(installed, model_id)]
    if missing:
        pytest.skip(f"Local model(s) not installed under {models_dir}: {missing}")

    manager = _build_model_manager(models_dir, model_ids)
    report: Dict[str, Any] = {
        "models_dir": str(models_dir),
        "model_ids": model_ids,
        "models": {},
    }

    for model_id in model_ids:
        installed_info = _installed_variant(installed, model_id)
        assert installed_info is not None

        try:
            model, load_metrics = await _load_model_for_eval(manager, model_id)
        except Exception as exc:
            report["models"][model_id] = {
                "installed_path": installed_info.get("path"),
                "load_success": False,
                "load_error": str(exc),
                "load_traceback_excerpt": traceback.format_exc()[-4000:],
            }
            manager._models.clear()
            _MODEL_CACHE.clear()
            gc.collect()
            continue

        quality_prompts = await _evaluate_output_quality(model)
        long_context = await _evaluate_long_context(model)
        tool_behavior = await _evaluate_tool_behavior(model, model_id)

        report["models"][model_id] = {
            "installed_path": installed_info.get("path"),
            "load_success": True,
            "load_metrics": load_metrics,
            "quality_prompts": quality_prompts,
            "long_context": long_context,
            "tool_behavior": tool_behavior,
        }

        _release_model_memory(manager, model)

    report["recommendation"] = _build_recommendation(report)
    report_path = _write_report(report, tmp_path)
    print(f"Local model recommendation report: {report_path}")
    print(json.dumps(report["recommendation"], indent=2, sort_keys=True))

    load_errors = {
        model_id: model_report["load_error"]
        for model_id, model_report in report["models"].items()
        if model_report.get("load_error")
    }
    assert not load_errors, f"Local model load failure(s); report written to {report_path}: {load_errors}"

    for model_id in model_ids:
        model_report = report["models"][model_id]
        assert model_report["load_metrics"]["cold_load_seconds"] > 0
        assert any(prompt["passed"] for prompt in model_report["quality_prompts"])
