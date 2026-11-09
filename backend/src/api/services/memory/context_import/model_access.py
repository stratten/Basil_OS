"""The one place the import reaches a reasoning model, so everything else can be tested with a fake."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol


class ImportModelLike(Protocol):
    async def complete(self, messages: List[Dict[str, str]]) -> str: ...


class ImportModel:
    """A loaded reasoning model answering one request at a time, without web search.

    The output budget is generous because some local models write out their reasoning before the JSON; the model's own maximum still caps it, and a prompt that asks for the JSON alone keeps most answers short.
    """

    def __init__(self, model: Any, *, max_tokens: int = 8192) -> None:
        self._model = model
        self._max_tokens = max_tokens
        # Set by the running import job. Called with the tokens a local model has written so far in the current answer, so the job can tell the person the model is still working.
        self.on_activity: Optional[Callable[[int], None]] = None
        # Also set by the job. Called with the tail of what a local model has streamed so far, so the person can read its thinking.
        self.on_thinking: Optional[Callable[[str], None]] = None

    def _report_activity(self, tokens_written: int, _thinking_text: Optional[str] = None, _thinking_complete: bool = False) -> None:
        listener = self.on_activity
        if listener is not None:
            listener(tokens_written)

    def _report_stream(self, streamed_tail: str) -> None:
        listener = self.on_thinking
        if listener is not None:
            listener(streamed_tail)

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        from api.services.agent_processing.lifecycle.execution_graph.agent_model_caller import (
            call_agent_model_with_messages,
        )

        return await call_agent_model_with_messages(
            self._model,
            messages,
            enable_web_search=False,
            max_tokens=self._max_tokens,
            purpose="context_import",
            activity_callback=self._report_activity,
            stream_preview_callback=self._report_stream,
        )


async def load_settings_import_model() -> ImportModel:
    """The model Settings uses for memory work: the memory processing model, else the default reasoning model."""
    from api.core.models.model_types import ModelCapability
    from api.core.preferences.preferences_io import load_preferences
    from api.core.services.model_service import get_model_service

    preferences = load_preferences()
    model_id: Optional[str] = getattr(getattr(preferences, "memory_intelligence", None), "memory_processing_model", None)
    model_id = model_id or preferences.models.reasoning_model
    model = await get_model_service().load_model_by_id(model_id, {ModelCapability.REASONING})
    return ImportModel(model)


async def load_setup_import_model(access: Any) -> ImportModel:
    """The route the person confirmed on the previous setup step, loaded the same way the setup agent loads it."""
    from api.core.models.model_types import ModelCapability
    from api.core.services.model_service import get_model_service
    from api.services.setup_assistant.context_catalog_service import SetupAssistantContextCatalogService

    selection = SetupAssistantContextCatalogService().resolve_setup_agent_model(None, access)
    service = get_model_service()
    if selection.is_local:
        model_type, variant = selection.model_type_and_variant
        model = await service.load_model(
            model_type=model_type,
            variant=variant,
            capabilities={ModelCapability.REASONING},
            registry_model_id=selection.model_id,
        )
    else:
        model = await service.load_model_by_id(selection.model_id, capabilities={ModelCapability.REASONING})
    return ImportModel(model)
