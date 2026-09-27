"""Tests for final-only exact-NumPy indexer behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.fts.tables import (
    ensure_fts_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_retrieval_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.retrieval.repository import (
    RetrievalRepository,
)
from api.services.retrieval.contracts import RetrievalDocument
from api.services.retrieval.indexer import RetrievalIndexer, DEFAULT_EMBEDDING_MODEL
from api.services.retrieval.numpy_vector_sidecar import NumpyVectorSidecar
from api.services.retrieval.registry import build_default_retrieval_registry
from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft


def apply_zettel_schema(connection: sqlite3.Connection) -> None:
    for statement in get_schema_statements():
        connection.execute(statement)
    migrate_zettel_backreference(connection)


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = tmp_path / "retrieval.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    apply_zettel_schema(conn)
    migrate_retrieval_tables(conn)
    ensure_fts_tables(conn)
    conn.commit()
    conn.close()
    return str(path)


def _insert_final(conn, source_id: str, narrative: str) -> None:
    draft = ZettelDraft(
        source_kind="transcription",
        source_id=source_id,
        event_type="transcription",
        occurred_at="2026-07-24T10:00:00+00:00",
        title=f"Title {source_id}",
        summary=f"Summary {source_id}",
    )
    store.insert_card(conn, draft)
    store.write_narrative(
        conn,
        f"transcription:{source_id}",
        narrative=narrative,
        model="m",
        is_open=False,
        open_note=None,
    )


def _fake_manager(monkeypatch, dimension: int = 4):
    manager = MagicMock()
    model = MagicMock()

    def _encode(texts, **kwargs):
        count = len(texts)
        return np.ones((count, dimension), dtype=np.float32)

    model.encode.side_effect = _encode
    manager.get.return_value = model
    monkeypatch.setattr(
        "api.services.retrieval.indexer.get_global_embedding_manager",
        lambda: manager,
    )
    return manager


def test_rebuild_if_stale_skips_current_generation(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    _fake_manager(monkeypatch)
    published = {"count": 0}

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return None

        def publish(self, generation_id, vectors, dimension, count):
            assert vectors.dtype == np.float32
            assert vectors.shape == (count, dimension)
            published["count"] += 1

        def load(self, generation_id, dimension, count):
            return np.ones((count, dimension), dtype=np.float32)

        def restore_current_manifest(self, manifest):
            pass

        def remove_current_generation(self):
            pass

        def remove_legacy_faiss_generations(self):
            pass

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())

    first = indexer.rebuild_if_stale()
    second = indexer.rebuild_if_stale()

    assert first["rebuilt"] is True
    assert second["rebuilt"] is False
    assert second["reason"] == "current"
    assert published["count"] == 1


def test_rebuild_after_narrative_change(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    _fake_manager(monkeypatch)
    published = {"count": 0}

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return None

        def publish(self, generation_id, vectors, dimension, count):
            assert vectors.dtype == np.float32
            assert vectors.shape == (count, dimension)
            published["count"] += 1

        def restore_current_manifest(self, manifest):
            pass

        def remove_current_generation(self):
            pass

        def remove_legacy_faiss_generations(self):
            pass

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())
    indexer.rebuild_if_stale()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store.write_narrative(
        conn,
        "transcription:one",
        narrative="Updated narrative.",
        model="m",
        is_open=False,
        open_note=None,
    )
    conn.commit()
    conn.close()

    result = indexer.rebuild_if_stale()
    assert result["rebuilt"] is True
    assert published["count"] == 2


def test_legacy_faiss_manifest_forces_numpy_generation_rebuild(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    _fake_manager(monkeypatch)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())
    first = indexer.rebuild_if_stale()
    sidecar = NumpyVectorSidecar(db_path, DEFAULT_EMBEDDING_MODEL)
    sidecar.manifest_path.write_text(
        json.dumps(
            {
                "generation_id": first["generation_id"],
                "model": DEFAULT_EMBEDDING_MODEL,
                "dimension": first["dimension"],
                "document_count": first["document_count"],
                "index_file": "legacy.faiss",
            }
        )
    )
    (sidecar.root / "legacy.faiss").write_bytes(b"legacy")

    rebuilt = indexer.rebuild_if_stale()

    assert rebuilt["rebuilt"] is True
    assert sidecar.load(
        rebuilt["generation_id"],
        rebuilt["dimension"],
        rebuilt["document_count"],
    ) is not None
    assert not (sidecar.root / "legacy.faiss").exists()


def test_empty_corpus_publishes_zero_generation(db_path, monkeypatch):
    _fake_manager(monkeypatch)
    removed = {"current": False, "legacy": False}

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return None

        def publish(self, *args, **kwargs):
            raise AssertionError("publish should not be called for empty corpus")

        def restore_current_manifest(self, manifest):
            pass

        def remove_current_generation(self):
            removed["current"] = True

        def remove_legacy_faiss_generations(self):
            removed["legacy"] = True

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())
    result = indexer.rebuild()

    assert result["document_count"] == 0
    assert result["dimension"] == 0
    assert removed == {"current": True, "legacy": True}


def test_failure_preserves_last_successful_generation(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    _fake_manager(monkeypatch)
    publish_calls = {"count": 0}

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return None

        def publish(self, generation_id, vectors, dimension, count):
            assert vectors.dtype == np.float32
            assert vectors.shape == (count, dimension)
            publish_calls["count"] += 1
            if publish_calls["count"] > 1:
                raise RuntimeError("publish failed")

        def restore_current_manifest(self, manifest):
            pass

        def remove_current_generation(self):
            pass

        def remove_legacy_faiss_generations(self):
            pass

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())
    first = indexer.rebuild_if_stale()
    assert first["rebuilt"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store.write_narrative(
        conn,
        "transcription:one",
        narrative="Changed narrative.",
        model="m",
        is_open=False,
        open_note=None,
    )
    conn.commit()
    state_before = RetrievalRepository(db_path).state(conn, DEFAULT_EMBEDDING_MODEL)
    conn.close()

    with pytest.raises(RuntimeError):
        indexer.rebuild_if_stale()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    state_after = RetrievalRepository(db_path).state(conn, DEFAULT_EMBEDDING_MODEL)
    conn.close()

    assert state_after["generation_id"] == state_before["generation_id"]
    assert state_after["document_count"] == state_before["document_count"]
    assert state_after["last_error"]


def test_metadata_commit_failure_restores_previous_manifest(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    _fake_manager(monkeypatch)
    events = []

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return b'{"generation_id":"previous"}'

        def publish(self, *args, **kwargs):
            events.append("publish")

        def restore_current_manifest(self, manifest):
            events.append(("restore", manifest))

        def remove_current_generation(self):
            pass

        def remove_legacy_faiss_generations(self):
            pass

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())

    def fail_replace(*args, **kwargs):
        raise sqlite3.OperationalError("metadata write failed")

    monkeypatch.setattr(indexer._repository, "replace_generation", fail_replace)

    with pytest.raises(sqlite3.OperationalError):
        indexer.rebuild()

    assert events == ["publish", ("restore", b'{"generation_id":"previous"}')]


def test_embedding_manager_use_is_balanced(db_path, monkeypatch):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_final(conn, "one", "First narrative.")
    conn.commit()
    conn.close()

    manager = _fake_manager(monkeypatch)

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot_current_manifest(self):
            return None

        def publish(self, generation_id, vectors, dimension, count):
            assert vectors.dtype == np.float32
            assert vectors.shape == (count, dimension)
            pass

        def restore_current_manifest(self, manifest):
            pass

        def remove_current_generation(self):
            pass

        def remove_legacy_faiss_generations(self):
            pass

    monkeypatch.setattr("api.services.retrieval.indexer.NumpyVectorSidecar", FakeSidecar)
    indexer = RetrievalIndexer(db_path, build_default_retrieval_registry())
    indexer.rebuild_if_stale()

    assert manager.begin_use.call_count == manager.end_use.call_count
