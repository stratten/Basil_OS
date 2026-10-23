"""Tests for the Activity Capture contact identity observation layer.

These cover the safety boundary of the feature: candidate extraction stays
read-only with respect to ``contact_relationships``, low-quality candidates are
rejected, the preference gate and failure isolation hold, and observations only
enrich generation transiently or get promoted through an explicit save.
"""

import sqlite3
import logging
from types import SimpleNamespace

import pytest

from api.core.knowledge.migrations.add_personalization_tables import (
    PERSONALIZATION_INDICES,
    PERSONALIZATION_TABLES,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_contact_identity_observations_table,
)
from api.core.knowledge.personalization.contact_candidate_extractor import (
    ContactCandidateExtractor,
)
from api.core.knowledge.personalization_models import (
    ContactIdentityObservationCreate,
    ContextType,
)
from api.core.knowledge.personalization_service import PersonalizationService
from api.services.assistant_sessions.assistant_session_router_components.personalization_pipeline import (
    save_assistant_session_as_sample,
)
from api.services.capture.automatic.activity_contact_observation_processor import (
    ActivityContactObservationProcessor,
)


def _create_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        for statement in PERSONALIZATION_TABLES:
            conn.execute(statement)
        for statement in PERSONALIZATION_INDICES:
            conn.execute(statement)
        migrate_contact_identity_observations_table(conn)
        conn.commit()
    finally:
        conn.close()


def _contact_row(db_path, email):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT contact_email, contact_name, contact_company, message_count
            FROM contact_relationships
            WHERE contact_email = ?
            """,
            (email,),
        ).fetchone()
    finally:
        conn.close()


def _contact_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM contact_relationships").fetchone()[0]
    finally:
        conn.close()


def _observation_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM contact_identity_observations"
        ).fetchone()[0]
    finally:
        conn.close()


class _FakeModel:
    def __init__(self, response):
        self._response = response

    async def generate_response(self, prompt):
        return self._response


class _FakeKnowledgeService:
    def __init__(self, db_path):
        self.db_path = db_path
        self.metadata_updates = []

    async def update_activity_metadata(self, activity_id, metadata):
        self.metadata_updates.append((activity_id, metadata))


class _NoModelImageProcessor:
    async def _get_model_for_task(self, capabilities, model_id=None):
        return None


def _activity(activity_id="act-1", app_name="Mail", window_title="Inbox"):
    return SimpleNamespace(
        id=activity_id,
        app_name=app_name,
        window_title=window_title,
        metadata={},
    )


def _enable_extraction(monkeypatch, enabled=True, processing_model="model-x"):
    import api.core.preferences.preferences_io as preferences_io

    monkeypatch.setattr(
        preferences_io,
        "load_preferences",
        lambda: SimpleNamespace(
            activity_capture=SimpleNamespace(
                contact_candidate_extraction_enabled=enabled,
                processing_model=processing_model,
            )
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic + agentic extraction
# ---------------------------------------------------------------------------

def test_deterministic_extraction_from_headers_and_body():
    extractor = ContactCandidateExtractor()
    text = (
        "From: Jane Doe <jane@example.com>\n"
        "To: bob@acme.io\n"
        "Subject: Q3\n\n"
        "Loop in carol@partner.org please.\n"
    )

    candidates = {
        c.normalized_email: c
        for c in extractor.extract_deterministic_candidates(
            extracted_text=text,
            app_name="Mail",
            window_title="Inbox",
            source_activity_id="act-1",
        )
    }

    assert candidates["jane@example.com"].display_name == "Jane Doe"
    assert candidates["jane@example.com"].relationship_hint == "sender"
    assert candidates["jane@example.com"].confidence >= 0.8
    # Bare header address has no name and lower confidence than a named one.
    assert candidates["bob@acme.io"].display_name is None
    assert candidates["bob@acme.io"].relationship_hint == "recipient"
    # Loose body address is weakest.
    assert candidates["carol@partner.org"].confidence < 0.5


@pytest.mark.asyncio
async def test_agentic_candidates_validate_and_reject_invalid():
    extractor = ContactCandidateExtractor(min_agentic_confidence=0.5)
    response = (
        '{"candidates": ['
        '{"email": "jane@example.com", "display_name": "Jane Doe", '
        '"organization_name": "Example Corp", "job_title": "VP", '
        '"confidence": 1.5, "reason": "signature", "evidence": "Jane Doe, VP"},'
        '{"email": "not-an-email", "confidence": 0.9},'
        '{"email": "weak@x.com", "confidence": 0.2}'
        ']}'
    )

    candidates = await extractor.extract_agentic_candidates(
        model=_FakeModel(response),
        extracted_text="some screen text with jane@example.com",
        app_name="Mail",
    )

    emails = {c.normalized_email: c for c in candidates}
    assert set(emails) == {"jane@example.com"}
    jane = emails["jane@example.com"]
    assert jane.organization_name == "Example Corp"
    assert jane.job_title == "VP"
    # Confidence is clamped into [0, 1].
    assert jane.confidence == 1.0


@pytest.mark.asyncio
async def test_agentic_stage_skipped_without_model():
    extractor = ContactCandidateExtractor()
    candidates = await extractor.extract_candidates(
        extracted_text="From: Jane <jane@example.com>\n",
        model=None,
    )
    # Only deterministic candidates, agentic skipped cleanly.
    assert [c.normalized_email for c in candidates] == ["jane@example.com"]


# ---------------------------------------------------------------------------
# Activity Capture post-processing hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activity_processing_stores_observations_without_creating_contacts(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)
    _enable_extraction(monkeypatch, enabled=True)

    knowledge_service = _FakeKnowledgeService(str(db_path))
    processor = ActivityContactObservationProcessor(
        knowledge_service, _NoModelImageProcessor()
    )

    result = {
        "extracted_text": "From: Jane Doe <jane@example.com>\nTo: bob@acme.io\n",
        "analysis": SimpleNamespace(entities=[{"type": "person", "name": "Jane"}]),
    }

    recorded = await processor.process(_activity(), result)

    assert recorded == 2
    assert _observation_count(db_path) == 2
    # The safety boundary: no learned contacts are created by Activity Capture.
    assert _contact_count(db_path) == 0
    # Traceability metadata was written.
    assert any(
        "contact_observation_count" in meta for _, meta in knowledge_service.metadata_updates
    )


@pytest.mark.asyncio
async def test_activity_processing_disabled_preference_skips_extraction(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)
    _enable_extraction(monkeypatch, enabled=False)

    knowledge_service = _FakeKnowledgeService(str(db_path))
    processor = ActivityContactObservationProcessor(
        knowledge_service, _NoModelImageProcessor()
    )

    result = {
        "extracted_text": "From: Jane Doe <jane@example.com>\n",
        "analysis": SimpleNamespace(entities=[]),
    }

    caplog.set_level(logging.INFO)
    recorded = await processor.process(_activity(), result, run_id="run-test")

    assert recorded == 0
    assert _observation_count(db_path) == 0
    diagnostic_messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "contact_enrichment_skipped" in record.getMessage()
    )
    assert "reason=preference_disabled" in diagnostic_messages
    assert "jane@example.com" not in diagnostic_messages


@pytest.mark.asyncio
async def test_activity_processing_failure_is_non_fatal(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)
    _enable_extraction(monkeypatch, enabled=True)

    knowledge_service = _FakeKnowledgeService(str(db_path))
    processor = ActivityContactObservationProcessor(
        knowledge_service, _NoModelImageProcessor()
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(processor.observations_manager, "record_observation", _boom)

    result = {
        "extracted_text": "From: Jane Doe <jane@example.com>\n",
        "analysis": SimpleNamespace(entities=[]),
    }

    # Must not raise; contact observation failure never fails the activity.
    recorded = await processor.process(_activity(), result)

    assert recorded == 0
    assert _observation_count(db_path) == 0


# ---------------------------------------------------------------------------
# Generation enrichment (transient, read-only)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generation_uses_high_confidence_observation_transiently(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)
    service = PersonalizationService(str(db_path))

    import api.core.knowledge.personalization_service as personalization_service_module

    # Keep Mac Contacts disabled so only observation enrichment runs.
    monkeypatch.setattr(
        personalization_service_module,
        "load_preferences",
        lambda: SimpleNamespace(
            behavior=SimpleNamespace(allow_mac_contacts_for_generation=False)
        ),
    )

    await service.contact_observations.record_observation(
        ContactIdentityObservationCreate(
            normalized_email="jane@example.com",
            display_name="Jane Doe",
            organization_name="Example Corp",
            confidence=0.85,
            source_app_name="Mail",
        )
    )

    context = await service.build_personalization_context(
        context_type=ContextType.EMAIL_REPLY,
        recipient="Jane <JANE@example.com>",
    )

    assert context.contact is not None
    assert context.contact.contact_name == "Jane Doe"
    assert context.contact.contact_company == "Example Corp"
    # Transient only: relationship is never asserted and nothing is persisted.
    assert str(context.contact.relationship_type) == "unknown"
    assert _contact_count(db_path) == 0


@pytest.mark.asyncio
async def test_generation_ignores_low_confidence_observation(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)
    service = PersonalizationService(str(db_path))

    import api.core.knowledge.personalization_service as personalization_service_module

    monkeypatch.setattr(
        personalization_service_module,
        "load_preferences",
        lambda: SimpleNamespace(
            behavior=SimpleNamespace(allow_mac_contacts_for_generation=False)
        ),
    )

    await service.contact_observations.record_observation(
        ContactIdentityObservationCreate(
            normalized_email="weak@example.com",
            display_name="Weak Signal",
            confidence=0.35,
            source_app_name="Mail",
        )
    )

    context = await service.build_personalization_context(
        context_type=ContextType.EMAIL_REPLY,
        recipient="weak@example.com",
    )

    assert context.contact is None
    assert _contact_count(db_path) == 0


# ---------------------------------------------------------------------------
# Explicit promotion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_sample_promotes_observation_identity_into_contact(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_db(db_path)

    import api.core.knowledge.personalization_service as personalization_service_module

    personalization_service = personalization_service_module.PersonalizationService(str(db_path))

    async def _skip_style_analysis(*args, **kwargs):
        return None

    monkeypatch.setattr(
        personalization_service.communication_styles,
        "analyze_and_update_style",
        _skip_style_analysis,
    )
    monkeypatch.setattr(
        personalization_service_module,
        "PersonalizationService",
        lambda: personalization_service,
    )

    await personalization_service.contact_observations.record_observation(
        ContactIdentityObservationCreate(
            normalized_email="jordan@example.org",
            display_name="Jordan Lee",
            organization_name="Partner LLC",
            confidence=0.85,
            source_app_name="Mail",
        )
    )

    session_service = SimpleNamespace(
        sessions={
            "session-1": {
                "suggestion": "Sounds good, talk soon.",
                "context_type": "email_compose",
                "metadata": {
                    "primary_participant_email": "jordan@example.org",
                    "subject": "Follow up",
                },
            }
        }
    )

    response = await save_assistant_session_as_sample(
        "session-1",
        request_body=None,
        service=session_service,
    )

    row = _contact_row(db_path, "jordan@example.org")

    assert response.status == "saved"
    assert response.contact_tracked is True
    assert row is not None
    # Identity fields were promoted from the high-confidence observation.
    assert row["contact_name"] == "Jordan Lee"
    assert row["contact_company"] == "Partner LLC"
    assert row["message_count"] == 1
