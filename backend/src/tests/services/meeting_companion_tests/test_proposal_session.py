import asyncio
from types import SimpleNamespace

import pytest

from api.services.meeting_companion import proposals as proposals_module
from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.investigator.coordinator import InvestigationCoordinator
from api.services.meeting_companion.investigator.escalation import ResearchRequest
from api.services.meeting_companion.investigator.models import ProposedAction
from api.services.meeting_companion.models import TimelineEvent
from api.services.meeting_companion.proposals import DEFAULT_POLICY, ProposalNotFound, ProposalPolicy, ProposalRejected

from .investigator_session_fakes import FakeInvestigator
from .proposal_fakes import FakeLauncher

RESEARCH = ResearchRequest(question="What is the vendor renewal term in the Acme contract?", reason="not in the transcript")
QUESTION = "How does the retry policy handle timeouts in billing?"
AUTO = ProposalPolicy(auto_capabilities=("todo", "agent_task"))
ACTIONS = [
    ProposedAction(action="agent_task", title="Draft vendor summary", instruction="Write a one page summary of the vendor comparison"),
    ProposedAction(action="todo", title="Add renewal reminder", instruction="Create a reminder for the contract renewal date"),
]


def research_outcome():
    return EvaluationOutcome(items=[], conversation_state="Reviewing the Acme contract.", research=RESEARCH)


async def started(make_session, *, policy=DEFAULT_POLICY, proposals=ACTIONS, status="completed"):
    fake = FakeInvestigator(status)
    fake.proposals = list(proposals)
    launcher = FakeLauncher()
    harness = make_session(investigator=fake, proposal_policy=lambda: policy, proposal_launcher=launcher)
    harness.add_member()
    await harness.session.start(run_loop=False)
    return harness, fake, launcher


def cards(harness):
    return [item for item in harness.session.snapshot("mic1").items if item.kind == "proposal"]


async def watch_run(harness, watch_instruction="show me the endpoint"):
    watch = harness.session.create_watch("billing", watch_instruction)
    harness.evaluator.override = research_outcome()
    harness.say("The billing endpoint is slow today.", 1.0, 4.0)
    await harness.settle()
    return watch


@pytest.mark.asyncio
async def test_a_supported_answer_brings_proposal_cards_that_wait_for_approval(make_session):
    harness, _fake, launcher = await started(make_session, policy=AUTO)
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    items = harness.session.snapshot("mic1").items
    assert [item.kind for item in items] == ["answer", "proposal", "proposal"]
    waiting = cards(harness)
    assert [card.proposal.action for card in waiting] == ["agent_task", "todo"]
    assert all(card.proposal.state == "proposed" and card.proposal.authority == "review" and card.researched for card in waiting)
    assert waiting[0].investigation_id == items[0].investigation_id and waiting[0].text == "Draft vendor summary"
    assert launcher.created == []


@pytest.mark.asyncio
async def test_no_proposals_without_a_supported_answer(make_session):
    harness, _fake, _launcher = await started(make_session, status="not_found")
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    assert cards(harness) == []


@pytest.mark.asyncio
async def test_the_policy_filters_which_actions_become_cards(make_session):
    harness, _fake, _launcher = await started(make_session, policy=ProposalPolicy(capabilities=("todo",)))
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    assert [card.proposal.action for card in cards(harness)] == ["todo"]


@pytest.mark.asyncio
async def test_a_question_from_the_transcript_never_starts_anything_by_itself(make_session):
    harness, _fake, launcher = await started(make_session, policy=AUTO)
    harness.evaluator.override = research_outcome()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    waiting = cards(harness)
    assert len(waiting) == 2 and all(card.proposal.authority == "review" and card.proposal.state == "proposed" for card in waiting)
    assert launcher.created == [] and launcher.launched == []


@pytest.mark.asyncio
async def test_a_chat_request_never_starts_anything_by_itself(make_session):
    harness, _fake, launcher = await started(make_session, policy=AUTO)
    harness.session.submit_chat("investigate the Acme renewal term")
    await harness.session.wait_idle()
    waiting = cards(harness)
    assert len(waiting) == 2 and all(card.proposal.authority == "review" for card in waiting)
    assert launcher.created == [] and launcher.launched == []


@pytest.mark.asyncio
async def test_a_users_watch_starts_its_own_wording_as_agent_work(make_session):
    harness, _fake, launcher = await started(make_session, policy=AUTO)
    watch = await watch_run(harness)
    waiting = cards(harness)
    assert [card.proposal.state for card in waiting] == ["started", "started"] and all(card.proposal.authority == "watch" and card.proposal.auto_started for card in waiting)
    assert [created["title"] for created in launcher.created] == ["show me the endpoint", "show me the endpoint"]
    assert all(created["system_created"] is True for created in launcher.created)
    assert launcher.launched == ["todo-1"] and waiting[0].proposal.agent_task_id == "task-1" and waiting[1].proposal.agent_task_id is None
    assert waiting[0].watch_id == watch.id
    automatic = [event for event in harness.event_kinds("proposal") if event.payload.get("auto")]
    assert [event.payload["state"] for event in automatic] == ["started", "started"]
    assert any(frame.get("event_type") == "meeting_companion_event" and frame["event"]["kind"] == "proposal" for frame in harness.broadcasts)


@pytest.mark.asyncio
async def test_suggestion_only_mode_leaves_watch_cards_waiting(make_session):
    harness, _fake, launcher = await started(make_session, policy=DEFAULT_POLICY)
    await watch_run(harness)
    waiting = cards(harness)
    assert [card.proposal.state for card in waiting] == ["proposed", "proposed"] and all(card.proposal.authority == "watch" for card in waiting)
    assert launcher.created == []


@pytest.mark.asyncio
async def test_a_todo_only_auto_policy_creates_a_todo_and_launches_no_worker(make_session):
    harness, _fake, launcher = await started(make_session, policy=ProposalPolicy(auto_capabilities=("todo",)))
    await watch_run(harness)
    states = {card.proposal.action: card.proposal.state for card in cards(harness)}
    assert states == {"agent_task": "proposed", "todo": "started"} and len(launcher.created) == 1 and launcher.launched == []


@pytest.mark.asyncio
async def test_a_watch_canceled_before_the_answer_arrives_loses_its_authority(make_session):
    harness, fake, launcher = await started(make_session, policy=AUTO)
    fake.release = asyncio.Event()
    watch = harness.session.create_watch("billing", "show me the endpoint")
    harness.evaluator.override = research_outcome()
    harness.say("The billing endpoint is slow today.", 1.0, 4.0)
    await harness.session.tick()
    for _ in range(20):
        if fake.requests:
            break
        await asyncio.sleep(0)
    assert harness.session.cancel_watch(watch.id) is True
    fake.release.set()
    await harness.session.wait_idle()
    waiting = cards(harness)
    assert len(waiting) == 2 and all(card.proposal.authority == "review" and card.proposal.state == "proposed" for card in waiting)
    assert launcher.created == []


@pytest.mark.asyncio
async def test_an_automatic_start_is_rechecked_against_the_watch_at_the_last_moment(make_session):
    fake = FakeInvestigator()
    fake.proposals = list(ACTIONS)
    launcher = FakeLauncher()
    current = [DEFAULT_POLICY]
    harness = make_session(investigator=fake, proposal_policy=lambda: current[0], proposal_launcher=launcher)
    harness.add_member()
    await harness.session.start(run_loop=False)
    watch = await watch_run(harness)
    waiting = cards(harness)
    assert [card.proposal.state for card in waiting] == ["proposed", "proposed"] and launcher.created == []
    current[0] = AUTO
    harness.session._auto_start_proposal(waiting[1], watch)
    await harness.session.wait_idle()
    assert [card.proposal.state for card in cards(harness)] == ["proposed", "started"] and len(launcher.created) == 1
    harness.session.cancel_watch(watch.id)
    harness.session._auto_start_proposal(waiting[0], watch)
    await harness.session.wait_idle()
    assert [card.proposal.state for card in cards(harness)] == ["proposed", "started"] and len(launcher.created) == 1


@pytest.mark.asyncio
async def test_automatic_starts_stop_at_the_per_meeting_budget(make_session, monkeypatch):
    monkeypatch.setattr(proposals_module, "MAX_AUTO_STARTS_PER_MEETING", 1)
    harness, _fake, launcher = await started(make_session, policy=AUTO)
    await watch_run(harness)
    assert [card.proposal.state for card in cards(harness)] == ["started", "proposed"] and len(launcher.created) == 1


@pytest.mark.asyncio
async def test_automatic_attempts_are_counted_again_after_a_restart():
    coordinator = InvestigationCoordinator(None, SimpleNamespace())
    events = [
        TimelineEvent(id="e1", seq=1, kind="proposal", meeting_time=1.0, wall_time="w", payload={"item_id": "a", "state": "started", "auto": True}),
        TimelineEvent(id="e2", seq=2, kind="proposal", meeting_time=2.0, wall_time="w", payload={"item_id": "b", "state": "failed", "auto": True}),
        TimelineEvent(id="e3", seq=3, kind="proposal", meeting_time=3.0, wall_time="w", payload={"item_id": "c", "state": "started"}),
        TimelineEvent(id="e4", seq=4, kind="proposal", meeting_time=4.0, wall_time="w", payload={"item_id": "d", "state": "dismissed", "auto": True}),
    ]
    coordinator.restore(events)
    assert coordinator._auto_starts == 2


@pytest.mark.asyncio
async def test_approving_a_card_starts_it_records_it_and_tells_the_client(make_session):
    harness, _fake, launcher = await started(make_session)
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    first = cards(harness)[0]
    outcome = await harness.session.decide_proposal(first.id, "approve")
    await harness.session.wait_idle()
    assert outcome.state == "started" and outcome.todo_id == "todo-1" and outcome.agent_task_id == "task-1"
    approved = cards(harness)[0]
    assert approved.proposal.state == "started" and approved.proposal.auto_started is False and approved.proposal.todo_id == "todo-1"
    assert "Write a one page summary of the vendor comparison" in launcher.created[0]["description"] and launcher.created[0]["system_created"] is False
    proposal_events = harness.event_kinds("proposal")
    assert [event.payload["state"] for event in proposal_events] == ["started"]
    assert any(frame.get("event_type") == "meeting_companion_event" and frame["event"]["kind"] == "proposal" for frame in harness.broadcasts)
    with pytest.raises(ProposalRejected, match="already started"):
        await harness.session.decide_proposal(first.id, "approve")


@pytest.mark.asyncio
async def test_dismissing_a_card_hides_it_and_blocks_a_later_approval(make_session):
    harness, _fake, launcher = await started(make_session)
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    target = cards(harness)[1]
    await harness.session.decide_proposal(target.id, "dismiss")
    dismissed = cards(harness)[1]
    assert dismissed.dismissed is True and dismissed.proposal.state == "dismissed"
    with pytest.raises(ProposalRejected, match="dismissed"):
        await harness.session.decide_proposal(target.id, "approve")
    with pytest.raises(ProposalNotFound):
        await harness.session.decide_proposal("nope", "approve")
    assert launcher.created == []


@pytest.mark.asyncio
async def test_an_assistant_session_card_is_handed_off_not_started(make_session):
    harness, _fake, launcher = await started(
        make_session,
        proposals=[ProposedAction(action="assistant_session", title="Talk through renewal options", instruction="Help me compare the renewal options with the vendor")],
    )
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    outcome = await harness.session.decide_proposal(cards(harness)[0].id, "approve")
    assert outcome.state == "handed_off" and outcome.instruction == "Help me compare the renewal options with the vendor"
    assert cards(harness)[0].proposal.state == "handed_off" and launcher.created == []


@pytest.mark.asyncio
async def test_approving_a_card_attaches_the_meetings_sources_to_the_todo(make_session, project):
    harness, _fake, launcher = await started(make_session)
    root = harness.session.attach_root(str(project))
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    first = cards(harness)[0]
    await harness.session.decide_proposal(first.id, "approve")
    await harness.session.wait_idle()
    assert launcher.references == [{"todo_id": "todo-1", "paths": [root.path]}]
