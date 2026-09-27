"""Dependency factory for the canonical retrieval service."""

from __future__ import annotations

from functools import lru_cache

from api.dependencies import get_sqlite_knowledge_service

from .registry import build_default_retrieval_registry
from .service import UnifiedRetrievalService


@lru_cache()
def get_unified_retrieval_service() -> UnifiedRetrievalService:
    service = get_sqlite_knowledge_service()
    return UnifiedRetrievalService(service.db_path, build_default_retrieval_registry())
