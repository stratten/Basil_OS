Basil Knowledge Layer — README
================================

Purpose
- Centralize how activities are stored, searched, and summarized.
- SQLite is the authoritative activity store for capture, metadata, and FTS5 search.
- The retrieval FAISS sidecar provides optional semantic history retrieval; it is
  independent from raw activity storage and is built only when requested.

Key components
- SQLite store: api/core/knowledge/sqlite/sqlite_knowledge_service.py
  - Public activity CRUD/search service used throughout the backend.
- Query processing: api/core/knowledge/query/
  - activity_query_processor.py parses activity queries and calls SQLite.
  - query_intent_handler.py optionally derives structured query parameters.
  - activity_summarizer.py produces model-generated summaries.

Current flow
1) UI/feature → QueryIntentHandler.process_query(query_text)
2) QueryIntentHandler → ActivityQueryProcessor.process_query(…)
3) ActivityQueryProcessor → SQLiteKnowledgeService.search_activities(…)

Activity ingestion
- SQLiteKnowledgeService.store_activity(…) writes the definitive activity row.
- No derived MP4, QR, or parallel activity-store artifact is written.

Retirement note
- MemVid, its hybrid wrapper, and its MP4/QR persistence were retired in 2026.
- The former derived directory at ~/.basil/data/memvid is cleaned during backend
  startup. SQLite activity rows and the retrieval FAISS sidecar are preserved.

Quick references
- SQLite: api/core/knowledge/sqlite/sqlite_knowledge_service.py
- Query handlers: api/core/knowledge/query/
- Unified retrieval: api/services/retrieval/