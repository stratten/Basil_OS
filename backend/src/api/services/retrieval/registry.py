"""Source policy for local retrieval.

A source is eligible only when its adapter declares canonical identity, bounded
index text, authoritative hydration, lossless-on-demand detail behavior,
redaction policy, and a deterministic freshness digest.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from .contracts import RetrievalSource


class RetrievalSourceRegistry:
    def __init__(self, sources: Iterable[RetrievalSource] = ()) -> None:
        self._sources: Dict[str, RetrievalSource] = {}
        for source in sources:
            self.register(source)

    def register(self, source: RetrievalSource) -> None:
        if source.source_kind in self._sources:
            raise ValueError(f"Duplicate retrieval source kind: {source.source_kind}")
        self._sources[source.source_kind] = source

    def require(self, source_kind: str) -> RetrievalSource:
        try:
            return self._sources[source_kind]
        except KeyError as exc:
            raise ValueError(f"Unsupported retrieval source kind: {source_kind}") from exc

    def sources(self, selected: list[str] | None = None) -> list[RetrievalSource]:
        kinds = selected if selected is not None else self.known_kinds()
        return [self.require(kind) for kind in kinds]

    def known_kinds(self) -> list[str]:
        return sorted(self._sources)

    def describe_sources(self) -> list[dict[str, Any]]:
        return [
            self._sources[source_kind].describe().as_dict()
            for source_kind in self.known_kinds()
        ]


def build_default_retrieval_registry() -> RetrievalSourceRegistry:
    """Construct the only import boundary for retrieval source adapters."""
    from .sources.agent_task_root_source import AgentTaskRootSource
    from .sources.zettel_source import ZettelBackedRetrievalSource

    return RetrievalSourceRegistry(
        [
            AgentTaskRootSource(),
            *(ZettelBackedRetrievalSource(kind) for kind in (
                "transcription",
                "assistant_output",
                "scheduled_run",
                "conversation",
                "screen_block",
                "meeting",
            )),
        ]
    )
