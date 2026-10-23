"""The bounded investigator: gather evidence with read-only tools in a short agent loop, then conclude with one structured call.

Gathering and concluding are separate on purpose. The agent loop only fills the evidence ledger. The answer is written by one schema-validated model call and its citations are resolved by code from the ledger, so an answer can never cite something no tool showed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, List, Optional

from api.core.models.model_invocation import StructuredModelOutputError, call_model_with_schema

from ..context_service import ContextService
from ..evaluator import default_token_budget
from ..similarity import normalize_text
from .evidence import EvidenceLedger
from .models import (
    CONCLUDE_TIMEOUT_SECONDS,
    MAX_ANSWER_CHARS,
    MAX_CONCURRENT_LOCAL,
    MAX_TOOL_CALLS,
    MIN_CONFIDENCE,
    RUN_DEADLINE_SECONDS,
    InvestigationConclusion,
    InvestigationRequest,
    InvestigationResult,
    InvestigationStatus,
)
from .policy import concurrency_limit_for
from .prompts import CONCLUSION_EVIDENCE_CHARS, build_conclusion_prompt, build_investigator_system_prompt, build_task_message
from .tools import InvestigatorToolEnvironment, RecordsSearch, ToolBudget, build_investigator_tools, default_records_search

logger = logging.getLogger(__name__)

ModelProvider = Callable[[Optional[str]], Awaitable[Any]]


class _Canceled(Exception):
    """Raised inside the runner when the cancel event wins a race with the model call."""


def default_llm_factory(model: Any) -> Any:
    from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import create_langchain_llm_from_model

    return create_langchain_llm_from_model(model)


class CompanionInvestigator:
    def __init__(
        self,
        *,
        schema_caller: Callable[..., Awaitable[Any]] = call_model_with_schema,
        llm_factory: Callable[[Any], Any] = default_llm_factory,
        records_search: RecordsSearch = default_records_search,
        token_budget: Callable[[Any], int] = default_token_budget,
        clock: Callable[[], float] = time.monotonic,
        deadline_seconds: float = RUN_DEADLINE_SECONDS,
        conclude_timeout_seconds: float = CONCLUDE_TIMEOUT_SECONDS,
        max_tool_calls: int = MAX_TOOL_CALLS,
    ) -> None:
        self._schema_caller = schema_caller
        self._llm_factory = llm_factory
        self._records_search = records_search
        self._token_budget = token_budget
        self._clock = clock
        self._deadline_seconds = deadline_seconds
        self._conclude_timeout_seconds = conclude_timeout_seconds
        self._max_tool_calls = max_tool_calls
        self._concurrency_limit = MAX_CONCURRENT_LOCAL

    @property
    def concurrency_limit(self) -> int:
        """How many runs may overlap; one until the first run has seen the model, then one for local and a few for API models."""
        return self._concurrency_limit

    async def investigate(
        self,
        request: InvestigationRequest,
        *,
        context: ContextService,
        cancel_event: "asyncio.Event",
        model_provider: ModelProvider,
    ) -> InvestigationResult:
        """Run one investigation to a result; never raises except ``CancelledError`` when the owning task is canceled."""
        started = self._clock()
        ledger = EvidenceLedger()
        budget = ToolBudget(self._max_tool_calls)

        def finish(status: InvestigationStatus, *, answer: str = "", confidence: float = 0.0, citations: Optional[List[Any]] = None, detail: str = "", proposals: Optional[List[Any]] = None) -> InvestigationResult:
            return InvestigationResult(
                investigation_id=request.investigation_id,
                status=status,
                answer=answer,
                confidence=confidence,
                citations=list(citations or []),
                tool_calls=budget.calls,
                evidence_count=len(ledger),
                duration_ms=max(0, int(round((self._clock() - started) * 1000))),
                detail=detail,
                proposals=list(proposals or []),
            )

        try:
            model = await model_provider(request.model_id)
        except Exception as error:
            return finish("failed", detail=f"model_unavailable: {error}")
        self._concurrency_limit = concurrency_limit_for(model)
        environment = InvestigatorToolEnvironment(
            context=context,
            ledger=ledger,
            budget=budget,
            records_search=self._records_search,
            cancel_event=cancel_event,
        )
        tools = build_investigator_tools(environment)
        try:
            budget_exhausted = await self._gather(model, tools, request, context.has_roots(), cancel_event)
        except asyncio.CancelledError:
            if cancel_event.is_set():
                return finish("canceled")
            raise
        except Exception as error:
            logger.warning("Companion investigation %s failed while gathering: %s", request.investigation_id, error, exc_info=True)
            return finish("failed", detail=f"gather_failed: {error}")
        if cancel_event.is_set():
            return finish("canceled")
        if len(ledger) == 0:
            return finish("timed_out" if budget_exhausted else "not_found", detail="no evidence was gathered")
        try:
            conclusion = await self._conclude(model, request, ledger, cancel_event)
        except _Canceled:
            return finish("canceled")
        except asyncio.CancelledError:
            if cancel_event.is_set():
                return finish("canceled")
            raise
        except asyncio.TimeoutError:
            return finish("timed_out", detail="the conclusion timed out")
        except StructuredModelOutputError as error:
            return finish("failed", detail=f"{error.category}: {error}")
        except Exception as error:
            logger.warning("Companion investigation %s failed while concluding: %s", request.investigation_id, error, exc_info=True)
            return finish("failed", detail=f"conclusion_failed: {error}")
        answer = normalize_text(conclusion.answer)[:MAX_ANSWER_CHARS]
        confidence = min(1.0, max(0.0, float(conclusion.confidence)))
        citations = ledger.citations(conclusion.evidence_ids)
        if not conclusion.found or not answer or not citations or confidence < MIN_CONFIDENCE:
            return finish("not_found", detail="the evidence did not support an answer")
        return finish("completed", answer=answer, confidence=round(confidence, 3), citations=citations, proposals=list(conclusion.proposals))

    async def _gather(self, model: Any, tools: List[Any], request: InvestigationRequest, has_roots: bool, cancel_event: "asyncio.Event") -> bool:
        """Run the short agent loop that fills the ledger; returns whether the run deadline ended it."""
        from langchain_core.messages import HumanMessage

        from api.services.agent_processing.lifecycle.execution_graph.agent_loop_runner import (
            build_agent_loop_graph,
            drive_agent_loop,
            prepare_agent_tools,
        )

        graph = build_agent_loop_graph(
            langchain_llm=self._llm_factory(model),
            tools=prepare_agent_tools(tools),
            system_prompt_text=build_investigator_system_prompt(focus=request.focus, has_roots=has_roots),
            middleware=[],
        )
        outcome = await drive_agent_loop(
            graph,
            [HumanMessage(content=build_task_message(request))],
            callbacks=None,
            cancel_event=cancel_event,
            budget_seconds=self._deadline_seconds,
        )
        return bool(outcome.budget_exhausted)

    async def _conclude(self, model: Any, request: InvestigationRequest, ledger: EvidenceLedger, cancel_event: "asyncio.Event") -> InvestigationConclusion:
        """One schema-validated call, raced against cancellation and its own timeout."""
        call = asyncio.ensure_future(
            self._schema_caller(
                model,
                prompt=build_conclusion_prompt(request, ledger.render(CONCLUSION_EVIDENCE_CHARS)),
                response_model=InvestigationConclusion,
                max_tokens=self._token_budget(model),
            )
        )
        cancel_wait = asyncio.ensure_future(cancel_event.wait())
        try:
            done, _pending = await asyncio.wait({call, cancel_wait}, timeout=self._conclude_timeout_seconds, return_when=asyncio.FIRST_COMPLETED)
            if call in done:
                return call.result().value
            if cancel_wait in done:
                raise _Canceled()
            raise asyncio.TimeoutError()
        finally:
            for task in (call, cancel_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(call, cancel_wait, return_exceptions=True)
