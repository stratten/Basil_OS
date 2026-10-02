"""Public contracts for canonical local-history retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Literal, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class RetrievalDocument:
    document_id: str
    source_kind: str
    source_id: str
    occurred_at: str
    updated_at: str
    title: str
    search_text: str
    content_digest: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalSourceDescriptor:
    source_kind: str
    display_name: str
    authority: Literal["primary", "derived"]
    evidence_kind: str
    browse_guidance: str
    detail_guidance: str
    supported_actions: tuple[Literal["browse", "search", "aggregate", "detail"], ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "display_name": self.display_name,
            "authority": self.authority,
            "evidence_kind": self.evidence_kind,
            "browse_guidance": self.browse_guidance,
            "detail_guidance": self.detail_guidance,
            "supported_actions": list(self.supported_actions),
        }


@dataclass(frozen=True)
class RetrievalCandidate:
    document_id: str
    score: float
    score_kind: str


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    source_kind: str
    source_id: str
    occurred_at: str
    title: str
    excerpt: str
    score: float
    score_kind: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    detail_available: bool = True


@dataclass(frozen=True)
class RetrievalSearchRequest:
    query: str
    source_kinds: Optional[list[str]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    mode: Literal["exact", "semantic", "hybrid"] = "hybrid"
    limit: int = 20


@dataclass(frozen=True)
class RetrievalBrowseRequest:
    source_kinds: Optional[list[str]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    outcome: Optional[str] = None
    limit: int = 200
    cursor: Optional[str] = None
    view: Literal["compact", "full"] = "full"
    max_output_chars: Optional[int] = None


@dataclass(frozen=True)
class RetrievalAggregateRequest:
    group_by: Literal["source_kind", "day", "outcome"]
    source_kinds: Optional[list[str]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    outcome: Optional[str] = None


@dataclass(frozen=True)
class RetrievalDetailRequest:
    source_kind: str
    source_id: str


@runtime_checkable
class RetrievalSource(Protocol):
    """A declared, user-retrievable canonical record family."""

    source_kind: str

    def describe(self) -> RetrievalSourceDescriptor:
        ...

    def iter_documents(self, conn) -> Iterable[RetrievalDocument]:
        ...

    def search_exact(
        self, conn, query: str, start: Optional[str], end: Optional[str], limit: int
    ) -> Iterable[RetrievalCandidate]:
        ...

    def hydrate(self, conn, source_id: str) -> Optional[RetrievalDocument]:
        ...

    def detail(self, conn, source_id: str) -> Optional[Dict[str, Any]]:
        ...
