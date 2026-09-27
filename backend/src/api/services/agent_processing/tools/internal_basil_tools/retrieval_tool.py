"""Agent tool for all local historical retrieval operations."""

from __future__ import annotations

import json
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from api.services.retrieval.contracts import (
    RetrievalAggregateRequest,
    RetrievalBrowseRequest,
    RetrievalDetailRequest,
    RetrievalSearchRequest,
)
from api.services.retrieval.factory import get_unified_retrieval_service


class RetrievalToolInput(BaseModel):
    action: Literal["catalog", "search", "browse", "aggregate", "detail"] = "search"
    query: Optional[str] = None
    mode: Literal["exact", "semantic", "hybrid"] = "hybrid"
    source_kinds: Optional[list[str]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    outcome: Optional[str] = None
    group_by: Optional[Literal["source_kind", "day", "outcome"]] = None
    source_kind: Optional[str] = None
    source_id: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "search" and not (self.query or "").strip():
            raise ValueError("query is required for action='search'")
        if self.action == "aggregate" and self.group_by is None:
            raise ValueError("group_by is required for action='aggregate'")
        if self.action == "detail" and not (self.source_kind and self.source_id):
            raise ValueError("source_kind and source_id are required for action='detail'")
        return self


async def _retrieve_basil_history(**kwargs) -> str:
    args = RetrievalToolInput(**kwargs)
    service = get_unified_retrieval_service()
    if args.action == "catalog":
        result = service.catalog()
    elif args.action == "search":
        result = service.search(RetrievalSearchRequest(
            query=args.query or "", source_kinds=args.source_kinds, start=args.start_time,
            end=args.end_time, mode=args.mode, limit=args.limit,
        ))
    elif args.action == "browse":
        result = service.browse(RetrievalBrowseRequest(
            source_kinds=args.source_kinds, start=args.start_time, end=args.end_time,
            outcome=args.outcome, limit=args.limit,
        ))
    elif args.action == "aggregate":
        result = service.aggregate(RetrievalAggregateRequest(
            group_by=args.group_by, source_kinds=args.source_kinds, start=args.start_time,
            end=args.end_time, outcome=args.outcome,
        ))
    else:
        result = service.detail(RetrievalDetailRequest(
            source_kind=args.source_kind or "", source_id=args.source_id or "",
        ))
    return json.dumps(result, ensure_ascii=False, default=str)


def create_retrieval_tool(profile=None) -> StructuredTool:
    return StructuredTool.from_function(
        func=_retrieve_basil_history,
        coroutine=_retrieve_basil_history,
        name="retrieve_basil_history",
        description=(
            "Discover and query Basil's local record types. Call action='catalog' when "
            "source selection depends on newly discovered input; then use browse, search, "
            "aggregate, or detail on the selected source kinds."
        ),
        args_schema=RetrievalToolInput,
    )
