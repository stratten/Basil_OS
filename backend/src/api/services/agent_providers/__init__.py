"""Non-persisting, non-launching validation services for attended generic ACP providers.

This package validates already-persisted provider profiles and workspace grants (see `api/core/knowledge/sqlite/sqlite_knowledge_service_component_services/provider_run_repository.py`) against the live filesystem. It never launches, probes, or spawns an external provider process; that remains owned by a later package.
"""
