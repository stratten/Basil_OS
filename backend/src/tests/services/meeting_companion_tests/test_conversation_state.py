from api.services.meeting_companion.conversation_state import (
    ConversationState,
    MAX_STATE_CHARS,
    MAX_TURN_CHARS,
    SINGLE_SOURCE_NOTE,
    clock_label,
    format_transcript,
    format_turn_line,
)
from api.services.meeting_companion.models import CompanionTurn


def make_turn(index, text, start, role="other", speaker="Zoom"):
    return CompanionTurn(id=f"t-{index:05d}", source_meeting_id="m", role=role, speaker=speaker, start=start, end=start + 2, text=text)


def test_state_apply_replaces_trims_and_ignores_blank():
    state = ConversationState()
    assert state.apply("  Team is   deciding on   retries. ", 12.0) is True
    assert state.text == "Team is deciding on retries." and state.updated_at == 12.0
    assert state.apply("   ", 20.0) is False
    assert state.text == "Team is deciding on retries." and state.updated_at == 12.0
    state.apply("x" * 5000, 30.0)
    assert len(state.text) == MAX_STATE_CHARS


def test_clock_label_and_speaker_labels():
    assert clock_label(0) == "00:00" and clock_label(83.9) == "01:23" and clock_label(6065) == "101:05" and clock_label(-5) == "00:00"
    assert format_turn_line(make_turn(1, "hello there", 83, role="self", speaker="Microphone")) == "[t-00001 @ 01:23] You: hello there"
    assert format_turn_line(make_turn(2, "hi", 5, speaker="Zoom")).endswith("Zoom: hi")
    assert format_turn_line(make_turn(3, "hi", 5, speaker="")).endswith("Other: hi")


def test_long_turn_is_truncated_with_ellipsis():
    line = format_turn_line(make_turn(1, "word " * 200, 0))
    assert line.endswith("…") and len(line) < MAX_TURN_CHARS + 60


def test_transcript_keeps_newest_turns_in_order_within_budget():
    turns = [make_turn(index, f"line number {index} " + "pad " * 10, index * 3) for index in range(1, 21)]
    rendered = format_transcript(turns, max_chars=400)
    ids = [line.split(" ")[0].strip("[") for line in rendered.split("\n")]
    assert ids[-1] == "t-00020" and ids == sorted(ids) and len(rendered) <= 400
    assert format_transcript([], 400) == ""


def test_microphone_only_window_is_labeled_speaker_and_led_by_the_note():
    turns = [make_turn(1, "What is the justification for this?", 5, role="self", speaker="Microphone"), make_turn(2, "I think it is the audit rule.", 9, role="self", speaker="Microphone")]
    rendered = format_transcript(turns, max_chars=400)
    assert rendered.startswith(SINGLE_SOURCE_NOTE + "\n")
    assert "[t-00001 @ 00:05] Speaker: What is the justification for this?" in rendered
    assert "You:" not in rendered
    assert "Treat the lines as a dialogue" in SINGLE_SOURCE_NOTE


def test_microphone_only_window_keeps_diarized_labels():
    turns = [make_turn(1, "hello", 5, role="self", speaker="Speaker 2"), make_turn(2, "hi", 8, role="self", speaker="Speaker 1")]
    rendered = format_transcript(turns, max_chars=400)
    assert "Speaker 2: hello" in rendered and "Speaker 1: hi" in rendered


def test_window_with_another_source_keeps_you_and_adds_no_note():
    turns = [make_turn(1, "hello there", 5, role="self", speaker="Microphone"), make_turn(2, "hi", 8, speaker="Zoom")]
    rendered = format_transcript(turns, max_chars=400)
    assert "You: hello there" in rendered and "Zoom: hi" in rendered
    assert SINGLE_SOURCE_NOTE not in rendered
