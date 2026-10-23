"""Model-driven evaluator for user-reviewable working-memory proposals."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field, ValidationError

from api.core.models.model_types import ModelCapability
from api.core.services.model_service import ModelService, get_model_service
from api.services.agent_processing.lifecycle.execution_graph.agent_model_caller import (
    call_agent_model_with_messages,
)


logger = logging.getLogger(__name__)

ManagedMemoryFileName = Literal["essentials.md", "now.md", "recent.md", "user.md"]
MemoryConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ActivitySignal:
    """A model-facing signal gathered from completed user-visible work."""

    source: str
    occurred_at: Optional[str]
    summary: str
    metadata: Dict[str, Any]


class MemoryProposal(BaseModel):
    """A reviewable memory proposal produced by a reasoning model."""

    target_file: ManagedMemoryFileName
    observation: str = Field(min_length=1, max_length=240)
    why: str = Field(min_length=1, max_length=500)
    confidence: MemoryConfidence


class MemoryProposalList(BaseModel):
    """Strict response envelope for memory proposal generation."""

    proposals: List[MemoryProposal] = Field(default_factory=list)


class MemoryEvaluator:
    """Use a reasoning model to identify durable memory proposals."""

    def __init__(
        self,
        *,
        model: Optional[Any] = None,
        model_id: Optional[str] = None,
        model_service: Optional[ModelService] = None,
    ) -> None:
        self.model = model
        self.model_id = model_id
        self.model_service = model_service or get_model_service()

    async def evaluate_signals(self, signals: List[ActivitySignal]) -> List[MemoryProposal]:
        """Return validated user-reviewable proposals for the provided signals."""
        if not signals:
            return []

        model = await self._resolve_model()
        response_text = await call_agent_model_with_messages(
            model,
            [
                {
                    "role": "system",
                    "content": self._build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"signals": [self._serialize_signal(signal) for signal in signals]},
                        ensure_ascii=False,
                    ),
                },
            ],
            enable_web_search=False,
        )
        return self._parse_validated_response(response_text)

    async def _resolve_model(self) -> Any:
        if self.model is not None:
            return self.model
        if not self.model_id:
            raise ValueError("MemoryEvaluator requires either model or model_id.")
        return await self.model_service.load_model_by_id(
            self.model_id,
            {ModelCapability.REASONING},
        )

    def _build_system_prompt(self) -> str:
        return (
            "You evaluate Basil usage signals and propose durable user memory ONLY when it would "
            "make future assistance more tailored. Return strict JSON only, with this shape: "
            '{"proposals":[{"target_file":"essentials.md|now.md|recent.md|user.md",'
            '"observation":"short user-reviewable markdown sentence, max 240 chars",'
            '"why":"why this is useful to remember",'
            '"confidence":"low|medium|high"}]}. '
            "The user must approve every proposal before anything becomes durable. "
            "Choose target_file yourself based on meaning: essentials.md for stable critical facts, "
            "now.md for current short-lived context, recent.md for recent working context, and "
            "user.md for durable preferences or work patterns. If nothing is worth proposing, "
            "return {\"proposals\":[]}. Do not include markdown fences or extra prose."
        )

    def _serialize_signal(self, signal: ActivitySignal) -> Dict[str, Any]:
        return {
            "source": signal.source,
            "occurred_at": signal.occurred_at,
            "summary": signal.summary,
            "metadata": signal.metadata,
        }

    def _parse_validated_response(self, response_text: str) -> List[MemoryProposal]:
        try:
            payload = json.loads(response_text)
            parsed = MemoryProposalList(**payload)
            return parsed.proposals
        except (TypeError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("MemoryEvaluator rejected invalid model response: %s", exc)
            return []
