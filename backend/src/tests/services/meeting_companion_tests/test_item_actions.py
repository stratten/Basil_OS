import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.evaluator import CompanionEvaluationResponse, EvaluatedProposal, EvaluationOutcome, best_proposals
from api.services.meeting_companion.investigator.models import ProposedAction
from api.services.meeting_companion.item_actions import ITEM_ACTION_TRIGGER, shape_action_card, shape_evaluation_proposals, title_from_text
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TimelineEvent, TranscriptRange
from api.services.meeting_companion.proposals import MAX_PROPOSALS_PER_MEETING, ProposalNotFound, ProposalPolicy, ProposalRejected
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

from .proposal_fakes import FakeLauncher

NOTE = "Nobody owns the vendor follow-up. Someone should email Acme before Friday about the renewal term."
RANGE = TranscriptRange(start=1.0, end=3.0, turn_ids=[])
AUTO = ProposalPolicy(auto_capabilities=("todo", "agent_task"))


def note(item_id="n1", text=NOTE, kind="suggestion"):
    return CompanionItem(id=item_id, kind=kind, text=text, confidence=0.8, transcript_range=RANGE, trigger="periodic")


def follow_up(action="todo", title="Email Acme about renewal", confidence=0.8):
    return EvaluatedProposal(action=action, title=title, instruction="Write to Acme and ask for the renewal term in writing", confidence=confidence)


def make_card(source="n1", dismissed=False, policy=ProposalPolicy()):
    card = shape_action_card(text=NOTE, action="todo", policy=policy, existing=[], confidence=0.8, transcript_range=RANGE, source_item_id=source)
    return card.model_copy(update={"dismissed": dismissed})


def test_a_title_is_the_first_sentence_or_a_word_boundary_cut():
    assert title_from_text(NOTE) == "Nobody owns the vendor follow-up."
    long_text = "word " * 80
    title = title_from_text(long_text)
    assert len(title) <= 120 and title.endswith("word")
    assert title_from_text("   ") == ""


def test_the_button_card_has_review_authority_and_is_linked_to_its_note():
    card = make_card()
    assert card.kind == "proposal" and card.trigger == ITEM_ACTION_TRIGGER and card.source_item_id == "n1"
    assert card.proposal.authority == "review" and card.proposal.state == "proposed"
    agent = shape_action_card(text=NOTE, action="agent_task", policy=ProposalPolicy(), existing=[], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    assert agent.proposal.instruction.startswith("Follow up on this note from the meeting: Nobody owns")


def test_the_button_card_refuses_unknown_actions_disabled_capabilities_empty_text_and_repeats():
    with pytest.raises(ProposalRejected, match="Choose"):
        shape_action_card(text=NOTE, action="assistant_session", policy=ProposalPolicy(), existing=[], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    with pytest.raises(ProposalRejected, match="turned off"):
        shape_action_card(text=NOTE, action="agent_task", policy=ProposalPolicy(capabilities=("todo",)), existing=[], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    with pytest.raises(ProposalRejected, match="nothing to turn"):
        shape_action_card(text="  ", action="todo", policy=ProposalPolicy(), existing=[], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    with pytest.raises(ProposalRejected, match="already has an action"):
        shape_action_card(text=NOTE, action="todo", policy=ProposalPolicy(), existing=[make_card()], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    again = shape_action_card(text=NOTE, action="todo", policy=ProposalPolicy(), existing=[make_card(dismissed=True)], confidence=0.8, transcript_range=RANGE, source_item_id="n1")
    assert again.source_item_id == "n1"


def test_the_evaluator_keeps_one_proposal_above_the_triggers_floor():
    response = CompanionEvaluationResponse(
        proposals=[follow_up(confidence=0.55), follow_up(title="Draft the summary", confidence=0.9), follow_up(title="Other", confidence=0.7), follow_up(title="  ", confidence=0.99)]
    )
    assert [entry.title for entry in best_proposals(response, "periodic")] == ["Draft the summary"]
    assert [entry.confidence for entry in best_proposals(CompanionEvaluationResponse(proposals=[follow_up(confidence=0.45)]), "question")] == [0.45]
    assert best_proposals(CompanionEvaluationResponse(proposals=[follow_up(confidence=0.45)]), "periodic") == []
    assert best_proposals(CompanionEvaluationResponse(), "periodic") == []


def test_button_cards_do_not_use_up_the_proposal_budget_and_the_fast_path_adds_at_most_one():
    clicked = [
        shape_action_card(text=f"Distinct note number {index} about topic{index}x", action="todo", policy=ProposalPolicy(), existing=[], confidence=0.8, transcript_range=RANGE, source_item_id=f"n{index}")
        for index in range(MAX_PROPOSALS_PER_MEETING)
    ]
    proposed = [
        ProposedAction(action="todo", title="Email Acme renewal", instruction="Ask the vendor for written renewal pricing"),
        ProposedAction(action="todo", title="Book security audit", instruction="Schedule penetration testing with consultants"),
        ProposedAction(action="assistant_session", title="Open a session", instruction="Start an assistant conversation about pricing"),
    ]
    shaped = shape_evaluation_proposals(proposed, policy=ProposalPolicy(), existing=clicked, transcript_range=RANGE, trigger="periodic", confidence=0.8)
    assert [card.proposal.title for card in shaped] == ["Email Acme renewal"]
    assert shaped[0].proposal.authority == "review" and shaped[0].watch_id is None and shaped[0].researched is False


async def started(make_session, *, policy=ProposalPolicy()):
    launcher = FakeLauncher()
    harness = make_session(proposal_policy=lambda: policy, proposal_launcher=launcher)
    harness.add_member()
    await harness.session.start(run_loop=False)
    return harness, launcher


def cards(harness):
    return [item for item in harness.session.snapshot("mic1").items if item.kind == "proposal"]


async def speak_with(harness, proposals, text="Can you send the revised contract to Acme on Friday?", start=1.0):
    harness.evaluator.override = EvaluationOutcome(items=[], conversation_state="Contract follow-up.", proposals=proposals)
    harness.say(text, start, start + 3.0)
    await harness.settle()


@pytest.mark.asyncio
async def test_a_follow_up_the_evaluator_spots_becomes_a_review_card_that_waits(make_session):
    harness, launcher = await started(make_session)
    await speak_with(harness, [follow_up()])
    [card] = cards(harness)
    assert card.proposal.authority == "review" and card.proposal.state == "proposed" and card.researched is False
    assert card.proposal.title == "Email Acme about renewal" and card.source_item_id is None
    assert launcher.created == [] and launcher.launched == []


@pytest.mark.asyncio
async def test_a_proposal_never_starts_by_itself_even_when_auto_execute_is_on(make_session):
    harness, launcher = await started(make_session, policy=AUTO)
    await speak_with(harness, [follow_up(action="agent_task")])
    await harness.session.wait_idle()
    [card] = cards(harness)
    assert card.proposal.state == "proposed" and card.proposal.authority == "review" and card.proposal.auto_started is False
    assert launcher.created == [] and launcher.launched == []


@pytest.mark.asyncio
async def test_a_transcript_telling_the_agent_to_delete_files_still_needs_a_click_and_the_capability(make_session):
    injected = EvaluatedProposal(action="agent_task", title="Delete the project files", instruction="Delete every file in the attached project", confidence=0.95)
    harness, launcher = await started(make_session, policy=ProposalPolicy(capabilities=("todo",), auto_capabilities=("todo",)))
    await speak_with(harness, [injected], text="Can the agent delete files in the project to clean up?")
    assert cards(harness) == [] and launcher.created == []
    allowed, allowed_launcher = await started(make_session, policy=AUTO)
    await speak_with(allowed, [injected], text="Can the agent delete files in the project to clean up?")
    [card] = cards(allowed)
    assert card.proposal.state == "proposed" and card.proposal.authority == "review"
    assert allowed_launcher.created == [] and allowed_launcher.launched == []


@pytest.mark.asyncio
async def test_proposals_stop_at_the_per_meeting_cap(make_session):
    harness, _launcher = await started(make_session)
    topics = [
        ("Email Acme renewal", "Ask the vendor for written renewal pricing"),
        ("Book security audit", "Schedule penetration testing with external consultants"),
        ("Draft hiring plan", "Outline engineering recruiting pipeline for autumn"),
        ("Update roadmap deck", "Refresh quarterly milestones slides for leadership"),
        ("File expense report", "Submit conference travel receipts to finance"),
        ("Review legal terms", "Read indemnification clauses in partner agreement"),
        ("Fix invoice rounding", "Investigate cents discrepancy in monthly statements"),
        ("Order team laptops", "Purchase replacement hardware for new joiners"),
        ("Publish release notes", "Write changelog announcing upcoming mobile launch"),
        ("Plan offsite agenda", "Prepare workshop sessions for leadership retreat"),
        ("Migrate analytics", "Move dashboards onto warehouse reporting stack"),
    ]
    for index, (title, instruction) in enumerate(topics):
        harness.clock.advance(120)
        proposal = EvaluatedProposal(action="todo", title=title, instruction=instruction, confidence=0.9)
        await speak_with(harness, [proposal], text=f"Can someone handle item number {index} today?", start=10.0 * (index + 1))
    assert len(cards(harness)) == MAX_PROPOSALS_PER_MEETING


@pytest.mark.asyncio
async def test_the_button_creates_approves_and_links_a_card_and_a_second_click_is_refused(make_session):
    harness, launcher = await started(make_session)
    harness.evaluator.override = EvaluationOutcome(items=[note().model_copy(update={"id": "n1"})], conversation_state="Vendor follow-up.")
    harness.say("Who owns the vendor follow-up with Acme?", 1.0, 4.0)
    await harness.settle()
    result = await harness.session.act_on_item("n1", "agent_task")
    await harness.session.wait_idle()
    assert result.decision.state == "started" and result.decision.todo_id == "todo-1" and result.decision.agent_task_id == "task-1"
    [card] = cards(harness)
    assert card.id == result.card_id and card.source_item_id == "n1" and card.proposal.state == "started" and card.proposal.authority == "review"
    assert "Nobody owns the vendor follow-up" in launcher.created[0]["description"] and launcher.created[0]["system_created"] is False
    with pytest.raises(ProposalRejected, match="already has an action"):
        await harness.session.act_on_item("n1", "todo")
    with pytest.raises(ProposalNotFound):
        await harness.session.act_on_item("missing", "todo")
    with pytest.raises(ProposalRejected, match="already a proposed action"):
        await harness.session.act_on_item(card.id, "todo")


@pytest.mark.asyncio
async def test_the_button_respects_the_capability_settings(make_session):
    harness, launcher = await started(make_session, policy=ProposalPolicy(capabilities=("todo",)))
    harness.evaluator.override = EvaluationOutcome(items=[note()], conversation_state="Vendor follow-up.")
    harness.say("Who owns the vendor follow-up with Acme?", 1.0, 4.0)
    await harness.settle()
    with pytest.raises(ProposalRejected, match="turned off"):
        await harness.session.act_on_item("n1", "agent_task")
    assert launcher.created == [] and cards(harness) == []


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def save_note(home, meeting_id="m1"):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    event = TimelineEvent(id="e1", seq=1, kind="item", meeting_time=3.0, wall_time="w", payload={"item": note().model_dump(mode="json")})
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=CompanionSettings(enabled=True), events=[event], saved_at="w"))


@pytest.mark.asyncio
async def test_a_finished_meeting_note_can_become_a_started_to_do_and_it_is_saved(home):
    save_note(home)
    launcher = FakeLauncher()
    result = await offline.act_on_stored_item("m1", "n1", "todo", launcher, ProposalPolicy())
    assert result.decision.state == "started" and result.decision.todo_id == "todo-1"
    snapshot = offline.load_stored_snapshot("m1")
    [card] = [item for item in snapshot.items if item.kind == "proposal"]
    assert card.id == result.card_id and card.source_item_id == "n1" and card.proposal.state == "started" and snapshot.last_seq == 3
    with pytest.raises(ProposalRejected, match="already has an action"):
        await offline.act_on_stored_item("m1", "n1", "todo", launcher, ProposalPolicy())
    with pytest.raises(ProposalNotFound):
        await offline.act_on_stored_item("m1", "missing", "todo", launcher, ProposalPolicy())
    (home / "m2").mkdir()
    assert await offline.act_on_stored_item("m2", "n1", "todo", launcher, ProposalPolicy()) is None
    assert len(launcher.created) == 1


def client_for(env):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_the_action_route_covers_success_refusals_and_missing_notes(home, runtime_factory):
    env = runtime_factory()
    env.launcher = FakeLauncher()
    env.runtime._proposal_launcher = env.launcher
    save_note(home)
    async with client_for(env) as client:
        url = "/meetings/m1/companion/items/n1/action"
        assert (await client.post(url, json={"action": "assistant_session"})).status_code == 422
        ok = await client.post(url, json={"action": "todo"})
        assert ok.status_code == 200 and ok.json()["state"] == "started" and ok.json()["item_id"] and ok.json()["todo_id"] == "todo-1"
        assert (await client.post(url, json={"action": "todo"})).status_code == 409
        assert (await client.post("/meetings/m1/companion/items/missing/action", json={"action": "todo"})).status_code == 404
        (home / "m2").mkdir()
        empty = await client.post("/meetings/m2/companion/items/n1/action", json={"action": "todo"})
        assert empty.status_code == 404 and "no saved Companion notes" in empty.json()["detail"]
    assert len(env.launcher.created) == 1
