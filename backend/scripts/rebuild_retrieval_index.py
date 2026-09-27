"""Rebuild Basil's local, rebuildable FAISS retrieval index."""

from __future__ import annotations

import argparse
import json

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.retrieval.indexer import DEFAULT_EMBEDDING_MODEL, RetrievalIndexer
from api.services.retrieval.registry import build_default_retrieval_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--db-path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    service = SQLiteKnowledgeService(db_path=args.db_path) if args.db_path else SQLiteKnowledgeService()
    result = RetrievalIndexer(
        service.db_path, build_default_retrieval_registry(), model=args.model
    ).rebuild()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
