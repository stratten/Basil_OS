"""Shared constructor for ManagedFileHistoryService.

Kept outside api.dependencies to avoid a circular import: this module is
imported from file_system_service.py (an agent tool), and api.dependencies
already imports tool-layer modules at module scope.
"""

from __future__ import annotations

from pathlib import Path

from api.settings import get_settings

from ..text_file_write import LocalTextFileWriter
from .blob_store import ManagedHistoryBlobStore
from .managed_file_history_service import ManagedFileHistoryService


def get_managed_file_history_service(*, text_writer: LocalTextFileWriter) -> ManagedFileHistoryService:
    """Construct a managed-history service bound to the given text writer.

    Deliberately not process-cached: LocalTextFileWriter instances differ by
    their allowed_roots between call sites (agent-tool writes vs. UI-driven
    restores), and the repository/blob-store objects this wraps are cheap,
    stateless, per-call constructs -- the same convention already used by
    ExecutionApprovalRepository and the other component-service repositories.
    """
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    blob_root = Path(get_settings().data_dir) / "managed_file_history" / "blobs"
    return ManagedFileHistoryService(
        db_path=knowledge_service.db_path,
        blob_store=ManagedHistoryBlobStore(blob_root),
        text_writer=text_writer,
    )
