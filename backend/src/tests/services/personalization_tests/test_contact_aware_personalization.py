import sqlite3
from importlib import import_module
from types import SimpleNamespace

import pytest

from api.core.knowledge.migrations.add_personalization_tables import (
    PERSONALIZATION_INDICES,
    PERSONALIZATION_TABLES,
)
from api.core.knowledge.personalization.contact_context import (
    EmailInteractionKind,
    extract_email_participant_context,
    parse_email_participant_list,
)
from api.core.knowledge.personalization_models import ContextType
from api.core.knowledge.personalization_service import PersonalizationService
from api.core.knowledge.personalization.mac_contacts_provider import (
    MacContactIdentity,
    MacContactsAuthorizationStatus,
    MacContactsProvider,
)
from api.services.assistant_sessions.context_enhancers.assistant_session_context_enhancer import (
    AssistantSessionContextEnhancer,
)
from api.services.assistant_sessions.assistant_session_router_components.personalization_pipeline import (
    save_assistant_session_as_sample,
)


def _create_personalization_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        for statement in PERSONALIZATION_TABLES:
            conn.execute(statement)
        for statement in PERSONALIZATION_INDICES:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _contact_row(db_path, email: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT contact_email, contact_name, message_count
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


def test_participant_parser_normalizes_display_names_and_multiple_recipients():
    participants = parse_email_participant_list(
        'Casey Jones <CASEY@example.com>, "Jordan Lee" <jordan@example.org>',
        source_header="To",
    )

    assert [participant.email for participant in participants] == [
        "casey@example.com",
        "jordan@example.org",
    ]
    assert participants[0].display_name == "Casey Jones"
    assert participants[1].display_name == "Jordan Lee"


def test_participant_context_uses_sender_for_reply_and_recipient_for_compose():
    reply_context = extract_email_participant_context(
        """
From: Casey Jones <casey@example.com>
To: User <user@example.com>
Subject: Timeline
        """,
        EmailInteractionKind.REPLY,
    )
    compose_context = extract_email_participant_context(
        """
To: Jordan Lee <jordan@example.org>
Cc: Casey Jones <casey@example.com>
Subject: Follow up
        """,
        EmailInteractionKind.COMPOSE,
    )

    assert reply_context.primary is not None
    assert reply_context.primary.email == "casey@example.com"
    assert compose_context.primary is not None
    assert compose_context.primary.email == "jordan@example.org"
    assert [participant.email for participant in compose_context.cc_participants] == ["casey@example.com"]


@pytest.mark.asyncio
async def test_personalization_context_lookup_does_not_create_unknown_contact(tmp_path):
    db_path = tmp_path / "personalization.db"
    _create_personalization_db(db_path)
    service = PersonalizationService(str(db_path))

    context = await service.build_personalization_context(
        context_type=ContextType.EMAIL_REPLY,
        recipient="New Person <new.person@example.com>",
    )

    assert context.contact is None
    assert _contact_row(db_path, "new.person@example.com") is None


def test_mac_contacts_provider_unavailable_path_is_non_fatal(monkeypatch):
    provider = MacContactsProvider()
    mac_contacts_provider_module = import_module(
        "api.core.knowledge.personalization.mac_contacts_provider"
    )

    monkeypatch.setattr(mac_contacts_provider_module.platform, "system", lambda: "Linux")

    status = provider.status()

    assert status.available is False
    assert status.authorization_status == MacContactsAuthorizationStatus.UNAVAILABLE
    assert status.can_lookup is False


@pytest.mark.asyncio
async def test_mac_contacts_lookup_not_called_when_preference_is_false(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_personalization_db(db_path)
    service = PersonalizationService(str(db_path))

    import api.core.knowledge.personalization_service as personalization_service_module

    monkeypatch.setattr(
        personalization_service_module,
        "load_preferences",
        lambda: SimpleNamespace(
            behavior=SimpleNamespace(allow_mac_contacts_for_generation=False)
        ),
    )

    def _unexpected_lookup(_email):
        raise AssertionError("Mac Contacts lookup should not be called")

    monkeypatch.setattr(
        personalization_service_module.mac_contacts_provider,
        "lookup_by_email",
        _unexpected_lookup,
    )

    context = await service.build_personalization_context(
        context_type=ContextType.EMAIL_REPLY,
        recipient="casey@example.com",
    )

    assert context.contact is None
    assert _contact_count(db_path) == 0


@pytest.mark.asyncio
async def test_mac_contacts_identity_enriches_prompt_context_read_only(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_personalization_db(db_path)
    service = PersonalizationService(str(db_path))

    import api.core.knowledge.personalization_service as personalization_service_module

    monkeypatch.setattr(
        personalization_service_module,
        "load_preferences",
        lambda: SimpleNamespace(
            behavior=SimpleNamespace(allow_mac_contacts_for_generation=True)
        ),
    )
    monkeypatch.setattr(
        personalization_service_module.mac_contacts_provider,
        "lookup_by_email",
        lambda _email: MacContactIdentity(
            email_addresses=["casey@example.com"],
            display_name="Casey Jones",
            organization_name="Example Corp",
        ),
    )

    context = await service.build_personalization_context(
        context_type=ContextType.EMAIL_REPLY,
        recipient="Casey <CASEY@example.com>",
    )

    assert context.contact is not None
    assert context.contact.contact_email == "casey@example.com"
    assert context.contact.contact_name == "Casey Jones"
    assert context.contact.contact_company == "Example Corp"
    assert _contact_count(db_path) == 0


@pytest.mark.asyncio
async def test_assistant_session_email_prompts_use_reply_sender_and_compose_recipient(tmp_path):
    db_path = tmp_path / "personalization.db"
    _create_personalization_db(db_path)
    enhancer = AssistantSessionContextEnhancer()
    enhancer.personalization_service = PersonalizationService(str(db_path))

    reply_result = await enhancer.enhance_suggestion_context(
        """
From: Casey Jones <casey@example.com>
To: User <user@example.com>
Subject: Timeline
Can you send the updated project timeline?
        """,
        "Draft a short reply.",
        app_name="Mail",
    )
    compose_result = await enhancer.enhance_suggestion_context(
        """
To: Jordan Lee <jordan@example.org>
Subject: Follow up
        """,
        "Draft a follow-up email.",
        app_name="Mail",
    )

    assert "Primary participant: Casey Jones <casey@example.com>" in reply_result["enhanced_prompt"]
    assert "Interaction type: reply" in reply_result["enhanced_prompt"]
    assert "Primary participant: Jordan Lee <jordan@example.org>" in compose_result["enhanced_prompt"]
    assert "Interaction type: compose" in compose_result["enhanced_prompt"]


@pytest.mark.asyncio
async def test_save_sample_tracks_contact_interaction_by_normalized_email(tmp_path, monkeypatch):
    db_path = tmp_path / "personalization.db"
    _create_personalization_db(db_path)

    import api.core.knowledge.personalization_service as personalization_service_module

    real_service_class = personalization_service_module.PersonalizationService
    personalization_service = real_service_class(str(db_path))

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

    session_service = SimpleNamespace(
        sessions={
            "session-1": {
                "suggestion": "I can send the updated timeline today.",
                "context_type": "email_reply",
                "metadata": {
                    "primary_participant_email": "CASEY@example.com",
                    "primary_participant_name": "Casey Jones",
                    "subject": "Timeline",
                },
            }
        }
    )

    response = await save_assistant_session_as_sample(
        "session-1",
        request_body=None,
        service=session_service,
    )
    row = _contact_row(db_path, "casey@example.com")

    assert response.status == "saved"
    assert response.contact_tracked is True
    assert row is not None
    assert row["contact_name"] == "Casey Jones"
    assert row["message_count"] == 1
