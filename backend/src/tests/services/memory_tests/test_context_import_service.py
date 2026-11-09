"""Model jobs, preview, commit, undo and retrieval of imported personal context against a real SQLite stream."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_retrieval_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.fts.tables import (
    ensure_fts_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.services.memory.context_import.models import ImportEmptyError, ImportItem, ImportTooLargeError, MAX_IMPORT_CHARS, ParsedImport
from api.services.memory.context_import.profile_store import ProfileTooLargeError
from api.services.memory.context_import.service import (
    ContextImportService,
    PreviewExpiredError,
    UnknownBatchError,
)
from api.services.retrieval.registry import build_default_retrieval_registry
from api.services.retrieval.sources.zettel_source import ZettelBackedRetrievalSource

FACT = ImportItem(category="stable_fact", text="I live in Boston and work in biotech.", title="I live in Boston and work in biotech.", section="About me")
DATED = ImportItem(
    category="dated",
    text="Ran the Boston marathon",
    title="Ran the Boston marathon",
    section="Log",
    occurred_at="2019-06-01T00:00:00+00:00",
)
STARTER = ImportItem(category="undated", text="My sourdough starter is called Dolores.", title="My sourdough starter is called Dolores.", section="Log")
SAMPLE_ITEMS = [FACT, DATED, STARTER]


def _note(text):
    return ImportItem(category="undated", text=text, title=text)


def _fact(text):
    return ImportItem(category="stable_fact", text=text, title=text)


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    for statement in get_schema_statements():
        connection.execute(statement)
    migrate_zettel_backreference(connection)
    migrate_retrieval_tables(connection)
    ensure_fts_tables(connection)
    connection.commit()
    yield connection
    connection.close()


class _FakeMemory:
    def __init__(self, user_md="", essentials_md=""):
        self.files = {"user.md": user_md, "essentials.md": essentials_md}

    def read_memory_file(self, name):
        content = self.files[name]
        return SimpleNamespace(content=content, size_bytes=len(content.encode("utf-8")))

    def replace_memory_file(self, name, content):
        self.files[name] = content


class _FakeProposals:
    def __init__(self, pending=None):
        self.pending = list(pending or [])
        self.enqueued = []

    def list_pending_memory_proposals(self):
        return [SimpleNamespace(entry=entry) for entry in self.pending]

    def enqueue_memory_proposals(self, proposals, *, source):
        self.enqueued.append((list(proposals), source))
        self.pending.extend(proposal.observation for proposal in proposals)


class _Model:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def complete(self, messages):
        return self.answers.pop(0)


def _loader(model):
    async def load():
        return model

    return load


def _service(conn, memory=None, proposals=None, clock=None, backup_dir=None):
    return ContextImportService(
        connection_factory=lambda: conn,
        proposal_store_factory=lambda: proposals or _FakeProposals(),
        memory_service_factory=lambda: memory or _FakeMemory(),
        backup_dir=backup_dir,
        **({"clock": clock} if clock else {}),
    )


def _preview(service, items=None, filename="me.md", label=""):
    parsed = ParsedImport(source_format="model", items=list(SAMPLE_ITEMS if items is None else items))
    return service.register_preview(parsed, filename, label)


def _entry_count(conn):
    return conn.execute("SELECT COUNT(*) FROM zettel_entries WHERE source_kind = 'imported_context'").fetchone()[0]


def test_preview_counts_categories_and_samples_without_writing_anything(conn):
    service = _service(conn)

    preview = _preview(service)

    assert preview["counts"] == {"dated": 1, "undated": 1, "stable_fact": 1}
    assert preview["total"] == 3
    assert preview["earliest"].startswith("2019-06-01")
    assert preview["samples"]["dated"][0]["title"] == "Ran the Boston marathon"
    assert preview["label"] == "me.md"
    assert _entry_count(conn) == 0


def test_commit_writes_dated_and_undated_entries_final_and_queues_stable_facts_as_proposals(conn):
    proposals = _FakeProposals()
    service = _service(conn, proposals=proposals)
    preview = _preview(service)

    result = service.commit(preview["preview_id"], ["dated", "undated", "stable_fact"])

    assert result["entries_added"] == 2
    assert result["proposals_queued"] == 1
    assert result["batch_id"].startswith("import-")
    assert proposals.enqueued[0][1] == "import"
    proposal = proposals.enqueued[0][0][0]
    assert (proposal.target_file, proposal.observation) == ("user.md", "I live in Boston and work in biotech.")
    rows = conn.execute("SELECT * FROM zettel_entries WHERE source_kind = 'imported_context' ORDER BY occurred_at").fetchall()
    assert [row["narrative_state"] for row in rows] == ["final", "final"]
    assert rows[0]["occurred_at"].startswith("2019-06-01")
    assert rows[0]["memory_swept_at"] is None


def test_only_the_chosen_categories_are_written(conn):
    proposals = _FakeProposals()
    service = _service(conn, proposals=proposals)
    preview = _preview(service)

    result = service.commit(preview["preview_id"], ["undated"])

    assert result["entries_added"] == 1
    assert result["proposals_queued"] == 0
    assert proposals.enqueued == []


def test_importing_the_same_records_twice_adds_nothing_new(conn):
    proposals = _FakeProposals()
    service = _service(conn, proposals=proposals)
    first = service.commit(_preview(service)["preview_id"], ["dated", "undated", "stable_fact"])
    second = service.commit(_preview(service)["preview_id"], ["dated", "undated", "stable_fact"])

    assert first["entries_added"] == 2
    assert second["entries_added"] == 0
    assert second["entries_already_present"] == 2
    assert second["batch_id"] is None
    assert second["proposals_queued"] == 0
    assert second["proposals_already_known"] == 1
    assert _entry_count(conn) == 2


def test_stable_facts_already_in_the_memory_files_or_pending_are_not_proposed_again(conn):
    memory = _FakeMemory(user_md="- I live in Boston and work in biotech.\n")
    proposals = _FakeProposals(pending=["I prefer short answers"])
    service = _service(conn, memory=memory, proposals=proposals)
    facts = [_fact("I live in Boston and work in biotech."), _fact("I prefer short answers."), _fact("I take my coffee black.")]

    result = service.commit(_preview(service, facts, "p.md")["preview_id"], ["stable_fact"])

    assert result["proposals_queued"] == 1
    assert result["proposals_already_known"] == 2
    assert proposals.enqueued[0][0][0].observation == "I take my coffee black."


def test_stable_facts_that_would_overflow_the_memory_file_produce_a_plain_warning(conn):
    memory = _FakeMemory(user_md="x" * 4000)
    service = _service(conn, memory=memory)
    facts = [_fact(f"Fact number {index} " + "y" * 100) for index in range(5)]

    result = service.commit(_preview(service, facts, "p.md")["preview_id"], ["stable_fact"])

    assert result["proposals_queued"] == 5
    assert "user.md" in result["memory_file_warning"]
    assert "bytes free" in result["memory_file_warning"]


def test_an_undated_imported_record_is_found_by_text_search_through_retrieval(conn):
    service = _service(conn)
    service.commit(_preview(service)["preview_id"], ["dated", "undated"])
    source = ZettelBackedRetrievalSource("imported_context")

    candidates = list(source.search_exact(conn, "sourdough Dolores", None, None, 10))

    assert candidates, "the undated imported record must be reachable by text"
    document = source.hydrate(conn, candidates[0].document_id.split(":", 1)[1])
    assert "Dolores" in document.search_text
    assert "imported_context" in build_default_retrieval_registry().known_kinds()


def test_undo_removes_the_batch_entries_and_their_search_results(conn):
    service = _service(conn)
    committed = service.commit(_preview(service)["preview_id"], ["dated", "undated"])
    source = ZettelBackedRetrievalSource("imported_context")
    assert list(source.search_exact(conn, "Dolores", None, None, 10))

    batches = service.list_batches()
    assert batches[0]["batch_id"] == committed["batch_id"]
    assert batches[0]["entry_count"] == 2
    assert batches[0]["label"] == "me.md"

    removed = service.undo(committed["batch_id"])

    assert removed["entries_removed"] == 2
    assert _entry_count(conn) == 0
    assert list(source.search_exact(conn, "Dolores", None, None, 10)) == []
    assert service.list_batches() == []


def test_undoing_one_batch_leaves_other_batches_and_other_sources_alone(conn):
    conn.execute(
        "INSERT INTO zettel_entries (id, source_kind, source_id, event_type, occurred_at, title, payload_json, narrative_state, materialized_at) "
        "VALUES ('transcription:t1', 'transcription', 't1', 'transcription', '2026-01-01T00:00:00+00:00', 'Spoken', '{}', 'final', '2026-01-01T00:00:00+00:00')"
    )
    service = _service(conn)
    first = service.commit(_preview(service, [_note("first batch note")], "a.md")["preview_id"], ["undated"])
    second = service.commit(_preview(service, [_note("second batch note")], "b.md")["preview_id"], ["undated"])

    service.undo(first["batch_id"])

    remaining = [row["source_kind"] for row in conn.execute("SELECT source_kind FROM zettel_entries ORDER BY source_kind")]
    assert remaining == ["imported_context", "transcription"]
    assert [batch["batch_id"] for batch in service.list_batches()] == [second["batch_id"]]


def test_undo_of_an_unknown_or_already_undone_batch_is_a_clear_error(conn):
    service = _service(conn)
    committed = service.commit(_preview(service, [_note("one note")], "a.md")["preview_id"], ["undated"])
    service.undo(committed["batch_id"])

    with pytest.raises(UnknownBatchError):
        service.undo(committed["batch_id"])
    with pytest.raises(UnknownBatchError):
        service.undo("import-doesnotexist")


def test_commit_with_an_unknown_preview_or_category_is_rejected(conn):
    service = _service(conn)
    preview = _preview(service, [_note("one note")], "a.md")

    with pytest.raises(PreviewExpiredError):
        service.commit("preview-missing", ["undated"])
    with pytest.raises(ValueError, match="Unknown categories"):
        service.commit(preview["preview_id"], ["everything"])
    assert _entry_count(conn) == 0


def test_a_preview_expires_after_an_hour_and_a_committed_preview_cannot_be_reused(conn):
    now = {"value": 0.0}
    service = _service(conn, clock=lambda: now["value"])
    expiring = _preview(service, [_note("one note")], "a.md")
    now["value"] = 3601.0
    with pytest.raises(PreviewExpiredError):
        service.commit(expiring["preview_id"], ["undated"])

    fresh = _preview(service, [_note("another note")], "b.md")
    service.commit(fresh["preview_id"], ["undated"])
    with pytest.raises(PreviewExpiredError):
        service.commit(fresh["preview_id"], ["undated"])


def test_the_oldest_previews_are_dropped_beyond_the_cache_limit(conn):
    service = _service(conn)
    first = _preview(service, [_note("note zero")], "0.md")
    for index in range(1, 10):
        _preview(service, [_note(f"note {index}")], f"{index}.md")

    with pytest.raises(PreviewExpiredError):
        service.commit(first["preview_id"], ["undated"])


def test_a_long_label_is_shortened_and_whitespace_collapsed(conn):
    service = _service(conn)

    preview = _preview(service, [_note("note")], "a.md", label="  My   very " + "long " * 40)

    assert len(preview["label"]) <= 80
    assert "  " not in preview["label"]


@pytest.mark.asyncio
async def test_a_records_job_ends_in_the_preview_that_commit_takes(conn):
    service = _service(conn)
    answer = json.dumps({"items": [{"category": "undated", "title": "Starter", "text": "My sourdough starter is called Dolores."}]})

    started = service.start_records_job("some notes about me", "me.md", "", _loader(_Model(answer)))
    job = service.jobs.get(started["job_id"])
    await job.task

    assert started["chunks_total"] == 1
    assert job.state == "done"
    assert job.result["counts"]["undated"] == 1
    assert job.result["label"] == "me.md"
    assert service.commit(job.result["preview_id"], ["undated"])["entries_added"] == 1


def test_blank_and_oversized_text_are_refused_before_a_job_starts(conn):
    service = _service(conn)

    with pytest.raises(ImportEmptyError, match="nothing to import"):
        service.start_records_job("   ", "a.md", "", _loader(_Model()))
    with pytest.raises(ImportTooLargeError, match="Split it"):
        service.start_profile_job("a" * (MAX_IMPORT_CHARS + 1), "a.md", "", _loader(_Model()))


@pytest.mark.asyncio
async def test_a_model_that_cannot_be_loaded_fails_the_job_in_plain_words(conn):
    service = _service(conn)

    async def load_nothing():
        raise RuntimeError("model file missing")

    started = service.start_records_job("some notes", "n.md", "", load_nothing)
    job = service.jobs.get(started["job_id"])
    await job.task

    assert job.state == "failed"
    assert "couldn't start the model" in job.error


@pytest.mark.asyncio
async def test_a_profile_job_drafts_and_commit_writes_only_the_reviewed_text_with_an_undo(conn, tmp_path):
    memory = _FakeMemory(user_md="- old user", essentials_md="- old essentials")
    service = _service(conn, memory=memory, backup_dir=tmp_path / "backups")
    notes = json.dumps({"notes": ["Works in biotech."]})
    profile = json.dumps({"essentials_md": "- Biotech", "user_md": "- old user\n- Short answers", "summary": "You work in biotech."})

    started = service.start_profile_job("notes about me", "me.md", "", _loader(_Model(notes, profile)))
    job = service.jobs.get(started["job_id"])
    await job.task

    draft = job.result
    assert job.state == "done"
    assert draft["summary"] == "You work in biotech."
    assert [file["name"] for file in draft["files"]] == ["essentials.md", "user.md"]
    assert draft["files"][0]["current"] == "- old essentials"
    assert draft["files"][0]["proposed"] == "- Biotech"
    assert draft["files"][0]["cap_bytes"] == 2048 and draft["files"][1]["cap_bytes"] == 4096
    assert memory.files["essentials.md"] == "- old essentials", "nothing is written until the person approves"

    result = service.commit_profile(draft["draft_id"], "- Biotech (edited)", "")

    assert result["files_updated"] == ["essentials.md"]
    assert memory.files == {"essentials.md": "- Biotech (edited)", "user.md": "- old user"}
    service.undo_profile(result["backup_id"])
    assert memory.files["essentials.md"] == "- old essentials"


@pytest.mark.asyncio
async def test_an_over_limit_edit_keeps_the_draft_so_the_person_can_shorten_and_save_again(conn, tmp_path):
    memory = _FakeMemory(user_md="- old user", essentials_md="- old essentials")
    service = _service(conn, memory=memory, backup_dir=tmp_path / "backups")
    notes = json.dumps({"notes": ["Works in biotech."]})
    profile = json.dumps({"essentials_md": "- Biotech", "user_md": "- u", "summary": "s"})
    started = service.start_profile_job("notes about me", "me.md", "", _loader(_Model(notes, profile)))
    job = service.jobs.get(started["job_id"])
    await job.task
    draft_id = job.result["draft_id"]

    with pytest.raises(ProfileTooLargeError):
        service.commit_profile(draft_id, "- " + "x" * 5000, "")
    result = service.commit_profile(draft_id, "- Biotech", "")

    assert result["files_updated"] == ["essentials.md"]
    with pytest.raises(PreviewExpiredError):
        service.commit_profile(draft_id, "- Biotech", "")


def test_committing_an_unknown_profile_draft_is_an_expired_error(conn, tmp_path):
    service = _service(conn, backup_dir=tmp_path / "backups")

    with pytest.raises(PreviewExpiredError, match="profile draft has expired"):
        service.commit_profile("draft-missing", "- a", "- b")


class _ReportingModel:
    """A model with the same activity hook as ImportModel, writing tokens as it answers."""

    def __init__(self, answer):
        self.answer = answer
        self.on_activity = None
        self.on_thinking = None
        self.stages_seen = []

    async def complete(self, messages):
        assert self.on_activity is not None
        self.on_activity(300)
        self.on_activity(700)
        self.on_thinking("Reading the note about Boston.")
        return self.answer


@pytest.mark.asyncio
async def test_a_job_shows_the_loading_stage_while_the_model_loads_then_counts_the_models_writing(conn):
    service = _service(conn)
    answer = json.dumps({"items": [{"category": "undated", "title": "Starter", "text": "My sourdough starter is called Dolores."}]})
    model = _ReportingModel(answer)
    stage_while_loading = []

    async def load():
        stage_while_loading.append(service.jobs.get(started["job_id"]).payload()["stage"])
        return model

    started = service.start_records_job("some notes about me", "me.md", "", load)
    job = service.jobs.get(started["job_id"])
    await job.task

    assert stage_while_loading == ["loading"]
    assert job.payload()["stage"] == "reading"
    assert job.payload()["tokens_written"] == 700
    assert model.on_activity == job.note_activity
    assert model.on_thinking == job.note_thinking
    assert job.payload()["thinking"] == "Reading the note about Boston."
