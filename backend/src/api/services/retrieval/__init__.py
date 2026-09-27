"""Canonical local-history retrieval service."""

from .contracts import (
    RetrievalAggregateRequest,
    RetrievalBrowseRequest,
    RetrievalDetailRequest,
    RetrievalDocument,
    RetrievalHit,
    RetrievalSearchRequest,
)
from .registry import RetrievalSourceRegistry, build_default_retrieval_registry

__all__ = [
    "RetrievalAggregateRequest",
    "RetrievalBrowseRequest",
    "RetrievalDetailRequest",
    "RetrievalDocument",
    "RetrievalHit",
    "RetrievalSearchRequest",
    "RetrievalSourceRegistry",
    "build_default_retrieval_registry",
]
