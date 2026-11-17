"""A skipped setup session keeps what is needed to pick it up again, never expires, and reports its age so the window can advise after a few days."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from api.core.utc_time import utc_now_naive
from api.services.setup_assistant import completion_service
from api.services.setup_assistant.completion_service import (
    MAX_RESUME_SUMMARY_CHARS,
    RESUME_ADVISORY_AFTER_DAYS,
    SetupAssistantCompletionService,
)

RESOLVED_ACCESS = {"mode": "cloud", "provider": "anthropic", "model_id": "claude", "resolved": True}
AGENDA = [{"id": "profile", "title": "Tell me about you", "status": "completed"}, {"id": "mail", "title": "Connect mail", "status": "pending"}]


@pytest.fixture
def service(tmp_path, monkeypatch) -> SetupAssistantCompletionService:
    monkeypatch.setattr(completion_service, "SETUP_ASSISTANT_STATE_FILE", tmp_path / "setup_assistant_state.json")
    return SetupAssistantCompletionService()


def _skip(service, **overrides):
    values = dict(
        configured=["p1"],
        skipped=[],
        deferred=[],
        session_goals=AGENDA,
        resume_stage="conversation",
        resume_summary="Saved so far: profile",
        resume_model_access=RESOLVED_ACCESS,
        resume_interaction_style=["Lead with the answer"],
    )
    values.update(overrides)
    return service.mark_setup_skipped(**values)


def test_a_skip_from_the_conversation_keeps_the_stage_agenda_summary_and_model(service):
    _skip(service)

    state = service.load_setup_state()
    assert state["resume_stage"] == "conversation"
    assert state["resume_summary"] == "Saved so far: profile"
    assert state["resume_model_access"] == RESOLVED_ACCESS
    assert state["resume_interaction_style"] == ["Lead with the answer"]
    assert state["session_goals"] == AGENDA
    assert state["resume_age_days"] == 0
    assert state["resume_advisory_after_days"] == RESUME_ADVISORY_AFTER_DAYS


@pytest.mark.parametrize(
    "overrides",
    [
        {"resume_stage": "welcome"},
        {"resume_stage": "express"},
        {"resume_stage": None},
        {"resume_model_access": None},
        {"resume_model_access": {**RESOLVED_ACCESS, "resolved": False}},
    ],
)
def test_a_session_that_cannot_be_continued_saves_no_resume_data_but_still_shows_the_reminder(service, overrides):
    _skip(service, **overrides)

    state = service.load_setup_state()
    assert state["pending_setup_assistant"] is True
    assert state["resume_stage"] is None and state["resume_summary"] is None and state["resume_model_access"] is None
    assert state["resume_age_days"] is None


def test_the_summary_is_trimmed_to_a_bounded_length(service):
    _skip(service, resume_summary="x" * (MAX_RESUME_SUMMARY_CHARS + 500))

    assert len(service.load_setup_state()["resume_summary"]) == MAX_RESUME_SUMMARY_CHARS


def test_an_old_session_is_never_expired_and_reports_its_age(service):
    _skip(service)
    path = completion_service.SETUP_ASSISTANT_STATE_FILE
    stored = json.loads(path.read_text())
    stored["last_skipped_at"] = stored["last_progress_at"] = (utc_now_naive() - timedelta(days=40, hours=2)).isoformat()
    path.write_text(json.dumps(stored))

    state = service.load_setup_state()

    assert state["resume_age_days"] == 40
    assert state["resume_stage"] == "conversation"
    assert state["pending_setup_assistant"] is True


def test_completing_setup_clears_the_saved_session(service):
    _skip(service)

    service.mark_setup_complete(configured=[], skipped=[], deferred=[])

    state = service.load_setup_state()
    assert state["resume_stage"] is None and state["resume_age_days"] is None


def test_dismissing_the_reminder_keeps_the_saved_session_and_does_not_write_derived_fields(service):
    _skip(service)

    service.dismiss_setup_reminder()

    on_disk = json.loads(completion_service.SETUP_ASSISTANT_STATE_FILE.read_text())
    assert "resume_age_days" not in on_disk and "resume_advisory_after_days" not in on_disk
    assert on_disk["resume_stage"] == "conversation" and on_disk["reminder_dismissed"] is True


def test_a_malformed_timestamp_gives_no_age_instead_of_failing(service):
    _skip(service)
    path = completion_service.SETUP_ASSISTANT_STATE_FILE
    stored = json.loads(path.read_text())
    stored["last_skipped_at"] = stored["last_progress_at"] = "not a date"
    path.write_text(json.dumps(stored))

    assert service.load_setup_state()["resume_age_days"] is None


def _progress(service, **overrides):
    values = dict(
        configured=["p1"],
        skipped=[],
        deferred=[],
        session_goals=AGENDA,
        resume_stage="conversation",
        resume_summary="Saved so far: profile",
        resume_model_access=RESOLVED_ACCESS,
        resume_interaction_style=["Lead with the answer"],
    )
    values.update(overrides)
    return service.save_setup_progress(**values)


def test_progress_saved_as_the_person_goes_can_be_picked_up_without_any_skip(service):
    _progress(service)

    state = service.load_setup_state()
    assert state["pending_setup_assistant"] is True and state["completed"] is False
    assert state["resume_stage"] == "conversation"
    assert state["session_goals"] == AGENDA
    assert state["resume_model_access"] == RESOLVED_ACCESS
    assert state["resume_age_days"] == 0
    assert state["last_skipped_at"] is None


def test_each_progress_save_replaces_the_last_and_moves_the_age_forward(service):
    _progress(service)
    path = completion_service.SETUP_ASSISTANT_STATE_FILE
    stored = json.loads(path.read_text())
    stored["last_progress_at"] = (utc_now_naive() - timedelta(days=5)).isoformat()
    path.write_text(json.dumps(stored))
    assert service.load_setup_state()["resume_age_days"] == 5

    _progress(service, session_goals=[{**AGENDA[1], "status": "completed"}], resume_summary="Saved so far: mail")

    state = service.load_setup_state()
    assert state["resume_age_days"] == 0
    assert state["session_goals"][0]["status"] == "completed"
    assert state["resume_summary"] == "Saved so far: mail"


@pytest.mark.parametrize(
    "overrides",
    [
        {"resume_stage": "welcome"},
        {"resume_stage": "express"},
        {"resume_stage": None},
        {"resume_model_access": None},
        {"resume_model_access": {**RESOLVED_ACCESS, "resolved": False}},
    ],
)
def test_an_early_stage_progress_call_never_wipes_an_earlier_good_save(service, overrides):
    _progress(service)

    _progress(service, session_goals=[], **overrides)

    state = service.load_setup_state()
    assert state["resume_stage"] == "conversation"
    assert state["session_goals"] == AGENDA


def test_an_early_stage_progress_call_on_a_fresh_install_saves_nothing(service):
    _progress(service, resume_stage="express")

    assert not completion_service.SETUP_ASSISTANT_STATE_FILE.exists()


def test_progress_after_completion_changes_nothing(service):
    service.mark_setup_complete(configured=["done"], skipped=[], deferred=[])

    _progress(service)

    state = service.load_setup_state()
    assert state["completed"] is True and state["pending_setup_assistant"] is False
    assert state["resume_stage"] is None


def test_progress_keeps_a_dismissed_reminder_dismissed_and_leaves_no_temporary_file(service):
    _skip(service)
    service.dismiss_setup_reminder()

    _progress(service)

    state = service.load_setup_state()
    assert state["reminder_dismissed"] is True
    assert not completion_service.SETUP_ASSISTANT_STATE_FILE.with_name("setup_assistant_state.json.tmp").exists()
    on_disk = json.loads(completion_service.SETUP_ASSISTANT_STATE_FILE.read_text())
    assert "resume_age_days" not in on_disk and "resume_advisory_after_days" not in on_disk


def test_the_progress_route_saves_the_session_and_the_state_route_offers_it(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.setup_assistant.completion_routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    body = {
        "configured": [],
        "skipped": [],
        "deferred": [],
        "session_goals": AGENDA,
        "resume_stage": "conversation",
        "resume_summary": "Agenda: 2 items",
        "resume_model_access": RESOLVED_ACCESS,
        "resume_interaction_style": [],
    }
    assert client.post("/state/progress", json=body).status_code == 200

    state = client.get("/state").json()["state"]
    assert state["pending_setup_assistant"] is True
    assert state["resume_stage"] == "conversation"
    assert state["session_goals"] == AGENDA
    assert state["resume_age_days"] == 0


def test_starting_from_the_top_forgets_the_saved_session_but_keeps_setup_pending(service):
    _skip(service)
    service.dismiss_setup_reminder()

    service.discard_saved_session()

    state = service.load_setup_state()
    assert state["resume_stage"] is None and state["resume_summary"] is None
    assert state["resume_model_access"] is None and state["resume_interaction_style"] == []
    assert state["session_goals"] == [] and state["configured"] == []
    assert state["resume_age_days"] is None
    assert state["pending_setup_assistant"] is True
    assert state["reminder_dismissed"] is True
    assert state["last_skipped_at"] is not None


def test_a_session_saved_after_starting_from_the_top_is_the_new_one(service):
    _skip(service)
    service.discard_saved_session()

    _progress(service, session_goals=[{"id": "new", "title": "Fresh start", "status": "pending"}])

    state = service.load_setup_state()
    assert state["session_goals"] == [{"id": "new", "title": "Fresh start", "status": "pending"}]
    assert state["resume_stage"] == "conversation"


def test_discarding_with_nothing_saved_writes_no_file(service):
    service.discard_saved_session()

    assert not completion_service.SETUP_ASSISTANT_STATE_FILE.exists()


def test_discarding_after_completion_changes_nothing(service):
    service.mark_setup_complete(configured=["done"], skipped=[], deferred=[])

    service.discard_saved_session()

    state = service.load_setup_state()
    assert state["completed"] is True and state["configured"] == ["done"]


def test_the_discard_route_clears_what_the_state_route_offers(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.setup_assistant.completion_routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    _skip(service)
    assert client.get("/state").json()["state"]["resume_stage"] == "conversation"

    assert client.post("/state/discard-saved-session").status_code == 200

    assert client.get("/state").json()["state"]["resume_stage"] is None
