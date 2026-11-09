"""Model-driven profile building: notes per part, merging when there are many, a bounded rewrite, and a shorten retry."""

import json

import pytest

from api.services.memory.context_import.models import ImportEmptyError
from api.services.memory.context_import.profile import (
    MERGE_PROMPT,
    NOTES_BUDGET_CHARS,
    NOTES_PROMPT,
    PROFILE_PROMPT,
    build_profile_draft,
)
from api.services.memory.context_import.structuring import ImportCanceledError, ImportModelError


class HandlerModel:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.handler(messages)


def _kind(messages):
    return {NOTES_PROMPT: "notes", MERGE_PROMPT: "merge", PROFILE_PROMPT: "profile"}[messages[0]["content"]]


async def _build(model, text="I am a designer.", **overrides):
    progress = []
    arguments = dict(
        current_essentials="- Lives in Boston",
        current_user="- Likes short answers",
        essentials_cap=2048,
        user_cap=4096,
        on_progress=lambda *args: progress.append(args),
        is_canceled=lambda: False,
    )
    arguments.update(overrides)
    return await build_profile_draft(model, text, **arguments), progress


def _profile(essentials="- e", user="- u", summary="s"):
    return json.dumps({"essentials_md": essentials, "user_md": user, "summary": summary})


@pytest.mark.asyncio
async def test_the_draft_rewrites_both_files_from_the_notes():
    def handler(messages):
        if _kind(messages) == "notes":
            return json.dumps({"notes": ["Works as a designer.", "Prefers short answers."]})
        payload = json.loads(messages[1]["content"])
        assert payload["notes"] == ["Works as a designer.", "Prefers short answers."]
        assert payload["current_essentials_md"] == "- Lives in Boston"
        assert payload["essentials_limit_bytes"] == 2048 and payload["user_limit_bytes"] == 4096
        return _profile("- Lives in Boston\n- Designer", "- Short answers", "You are a designer who likes short answers.")

    model = HandlerModel(handler)

    draft, progress = await _build(model)

    assert draft.essentials_md == "- Lives in Boston\n- Designer"
    assert draft.user_md == "- Short answers"
    assert draft.summary.startswith("You are a designer")
    assert [_kind(call) for call in model.calls] == ["notes", "profile"]
    assert progress[0] == (0, 1, "Reading part 1 of 1.")
    assert progress[1] == (1, 1, "Read part 1 of 1.")
    assert progress[-1][2] == "Writing your profile."


@pytest.mark.asyncio
async def test_a_model_that_reasons_before_its_json_is_read_from_its_last_object():
    reasoning = 'Let me think. A draft: {"notes":["draft only"]}. Checking the limits... fine. Final answer: {"notes":["Staff designer at Fernhill."]}'

    def handler(messages):
        return reasoning if _kind(messages) == "notes" else _profile()

    draft, _progress = await _build(HandlerModel(handler))

    assert draft.summary == "s"


@pytest.mark.asyncio
async def test_the_retry_after_an_unreadable_answer_adds_a_firm_reminder_instead_of_repeating_the_request():
    answers = iter(["still thinking about the notes", '{"notes":["A note."]}', _profile()])
    model = HandlerModel(lambda messages: next(answers))

    await _build(model)

    first, second = model.calls[0], model.calls[1]
    assert len(second) == len(first) + 1
    assert second[:-1] == first
    assert "only the JSON object" in second[-1]["content"]
    assert "Do not write out your reasoning" in first[0]["content"]


@pytest.mark.asyncio
async def test_an_over_limit_file_is_sent_back_once_to_be_shortened():
    answers = iter([_profile(essentials="- " + "x" * 200), _profile(essentials="- short")])

    def handler(messages):
        return json.dumps({"notes": ["A note."]}) if _kind(messages) == "notes" else next(answers)

    model = HandlerModel(handler)

    draft, _ = await _build(model, essentials_cap=100)

    assert draft.essentials_md == "- short"
    assert [_kind(call) for call in model.calls] == ["notes", "profile", "profile"]
    assert "shorten it" in model.calls[2][-1]["content"]


@pytest.mark.asyncio
async def test_a_file_still_over_its_limit_after_the_retry_is_returned_for_the_person_to_edit():
    long_answer = _profile(essentials="- " + "x" * 200)

    def handler(messages):
        return json.dumps({"notes": ["A note."]}) if _kind(messages) == "notes" else long_answer

    draft, _ = await _build(HandlerModel(handler), essentials_cap=100)

    assert len(draft.essentials_md.encode("utf-8")) > 100


@pytest.mark.asyncio
async def test_a_blank_file_in_the_answer_keeps_the_current_text():
    def handler(messages):
        return json.dumps({"notes": ["A note."]}) if _kind(messages) == "notes" else _profile(essentials="", user="- new")

    draft, _ = await _build(HandlerModel(handler))

    assert draft.essentials_md == "- Lives in Boston"
    assert draft.user_md == "- new"


@pytest.mark.asyncio
async def test_no_lasting_notes_is_an_empty_error():
    model = HandlerModel(lambda messages: json.dumps({"notes": []}))

    with pytest.raises(ImportEmptyError, match="nothing lasting"):
        await _build(model)


@pytest.mark.asyncio
async def test_unreadable_parts_are_an_error_when_none_can_be_read():
    model = HandlerModel(lambda messages: "bad")

    with pytest.raises(ImportModelError, match="any part"):
        await _build(model)


@pytest.mark.asyncio
async def test_an_unreadable_final_answer_is_an_error():
    def handler(messages):
        return json.dumps({"notes": ["A note."]}) if _kind(messages) == "notes" else "bad"

    with pytest.raises(ImportModelError, match="could not write your profile"):
        await _build(HandlerModel(handler))


@pytest.mark.asyncio
async def test_cancel_is_checked_before_the_first_part():
    model = HandlerModel(lambda messages: "{}")

    with pytest.raises(ImportCanceledError):
        await _build(model, is_canceled=lambda: True)

    assert model.calls == []


@pytest.mark.asyncio
async def test_many_notes_are_merged_before_the_rewrite():
    text = "\n\n".join(chr(97 + index) * 5000 for index in range(6))
    counter = {"notes": 0}

    def handler(messages):
        kind = _kind(messages)
        if kind == "notes":
            counter["notes"] += 1
            return json.dumps({"notes": [f"Part {counter['notes']} fact {index} " + "z" * 200 for index in range(40)]})
        if kind == "merge":
            return json.dumps({"notes": ["Merged note."]})
        payload = json.loads(messages[1]["content"])
        assert sum(len(note) for note in payload["notes"]) <= NOTES_BUDGET_CHARS
        return _profile()

    model = HandlerModel(handler)

    await _build(model, text=text)

    kinds = [_kind(call) for call in model.calls]
    assert kinds.count("notes") == 6
    assert "merge" in kinds
    assert kinds[-1] == "profile"
