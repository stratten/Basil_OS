"""Shared agent-model calling helpers.

This module keeps setup flows and regular agent tasks on the same model
execution path for local llama.cpp models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile

from .llama_cpp_langchain_adapter import create_langchain_llm_from_llama_cpp


def _to_langchain_messages(messages: List[Dict[str, str]]) -> List[BaseMessage]:
    converted: List[BaseMessage] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted


async def call_agent_model_with_messages(
    model: Any,
    messages: List[Dict[str, str]],
    *,
    enable_web_search: bool = True,
    max_tokens: Optional[int] = None,
    purpose: str = "general",
) -> str:
    """Call one agent-compatible model with an optional local workload purpose."""
    supports_search = getattr(model, "_supports_web_search", None)
    if not enable_web_search and callable(supports_search) and supports_search():
        return await model.generate_from_messages(
            messages,
            max_tokens=max_tokens or 4096,
            enable_web_search=False,
        )

    engine_source = "unknown"
    try:
        metadata = model.get_metadata()
        engine_source = getattr(metadata, "source", "unknown") or "unknown"
    except Exception:
        pass

    if engine_source.lower() == "llama.cpp":
        profile = resolve_runtime_model_profile(model)
        adapter = create_langchain_llm_from_llama_cpp(
            model,
            profile=profile,
            purpose=purpose,
            requested_output_tokens=max_tokens,
        )
        response = await adapter.ainvoke(_to_langchain_messages(messages))
        return str(getattr(response, "content", "") or "")

    if hasattr(model, "chat_completion"):
        response = await model.chat_completion(messages)
        if isinstance(response, dict):
            return str(response.get("content", ""))
        return str(response or "")

    prompt = "\n\n".join(
        f"{message.get('role', 'user').upper()}: {message.get('content', '')}"
        for message in messages
    )
    return await model.generate_response(prompt=prompt, max_tokens=max_tokens or 4096)
