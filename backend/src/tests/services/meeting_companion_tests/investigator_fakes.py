"""Scripted collaborators for the investigator tests: a chat model, a schema caller, a records search and request builders."""

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from api.core.models.model_invocation import StructuredModelResponse
from api.services.meeting_companion.investigator.models import InvestigationConclusion, InvestigationRequest
from api.services.meeting_companion.models import CompanionTurn


def tool_call(name: str, args: Dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


DONE = AIMessage(content="DONE")


class ScriptedChatModel(BaseChatModel):
    """Returns the scripted messages in order, repeating the last one; ``bind_tools`` returns itself."""

    script: List[Any] = Field(default_factory=list)
    cursor: int = 0
    delay_seconds: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.script[min(self.cursor, len(self.script) - 1)]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self._generate(messages, stop, run_manager, **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self


class ScriptedConclusion:
    """A schema caller that returns a canned conclusion, optionally after a delay or with an error."""

    def __init__(self, conclusion: Optional[InvestigationConclusion] = None, *, error: Optional[Exception] = None, delay_seconds: float = 0.0) -> None:
        self.conclusion = conclusion or InvestigationConclusion(found=False)
        self.error = error
        self.delay_seconds = delay_seconds
        self.prompts: List[str] = []

    async def __call__(self, model: Any, *, prompt: str, response_model: Any, max_tokens: int) -> StructuredModelResponse:
        self.prompts.append(prompt)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return StructuredModelResponse(value=self.conclusion, enforcement="strict_json_fallback", finish_reason="stop")


class FakeRecords:
    """A records search that returns canned hits and remembers its calls."""

    def __init__(self, hits: Optional[List[Dict[str, Any]]] = None, *, error: Optional[Exception] = None) -> None:
        self.hits = hits or []
        self.error = error
        self.calls: List[Any] = []

    async def __call__(self, query: str, source_kinds: List[str]) -> List[Dict[str, Any]]:
        self.calls.append((query, list(source_kinds)))
        if self.error is not None:
            raise self.error
        return list(self.hits)


async def provide_model(model_id: Optional[str]) -> Any:
    return SimpleNamespace(model_id=model_id)


def make_turn(index: int, text: str, start: float) -> CompanionTurn:
    return CompanionTurn(id=f"t-{index:05d}", source_meeting_id="m", role="other", speaker="Zoom", start=start, end=start + 3, text=text)


def make_request(**overrides: Any) -> InvestigationRequest:
    turns = [make_turn(1, "What is the vendor renewal term in the contract?", 10.0)]
    values: Dict[str, Any] = dict(
        investigation_id="iv-test",
        origin="explicit",
        question="What is the vendor renewal term in the contract?",
        meeting_time=13.0,
        window_turns=turns,
        conversation_state="The team is reviewing a vendor contract.",
        focus="",
        model_id=None,
        watch_id=None,
        source_turn_ids=["t-00001"],
    )
    values.update(overrides)
    return InvestigationRequest(**values)
