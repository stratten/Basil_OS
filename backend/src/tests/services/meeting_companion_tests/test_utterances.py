from api.services.meeting_companion.utterances import SessionClock, UtteranceAssembler, join_fragments


def make_assembler(**overrides):
    return UtteranceAssembler(
        source_meeting_id="m1",
        role="other",
        default_speaker="System Audio",
        id_prefix="t-",
        **overrides,
    )


def feed(assembler, start, end, text, now, speaker=None):
    return assembler.add_fragment(start=start, end=end, text=text, speaker=speaker, now_wall=now)


def test_fragments_join_until_sentence_end():
    assembler = make_assembler()
    assert feed(assembler, 0.0, 0.5, " how does", 1.0) == []
    assert feed(assembler, 0.5, 1.2, " the retry", 1.7) == []
    turns = feed(assembler, 1.2, 2.0, " policy work?", 2.5)
    assert len(turns) == 1
    assert turns[0].text == "how does the retry policy work?"
    assert turns[0].start == 0.0 and turns[0].end == 2.0
    assert turns[0].id == "t-00001"
    assert turns[0].speaker == "System Audio"
    assert turns[0].role == "other"


def test_silence_gap_splits_utterances():
    assembler = make_assembler()
    assert feed(assembler, 0.0, 1.0, " we should ship friday", 1.0) == []
    turns = feed(assembler, 5.0, 6.0, " next topic is billing", 6.0)
    assert [turn.text for turn in turns] == ["we should ship friday"]
    assert [turn.text for turn in assembler.flush_all()] == ["next topic is billing"]


def test_idle_flush_uses_wall_clock():
    assembler = make_assembler()
    feed(assembler, 0.0, 1.0, " we should ship friday", 10.0)
    assert assembler.flush_idle(10.5) == []
    turns = assembler.flush_idle(11.7)
    assert [turn.text for turn in turns] == ["we should ship friday"]
    assert assembler.flush_idle(30.0) == []


def test_speaker_change_splits_utterances():
    assembler = make_assembler()
    feed(assembler, 0.0, 1.0, " first speaker talks", 1.0, speaker="Alice")
    turns = feed(assembler, 1.1, 2.0, " second speaker talks", 2.0, speaker="Bob")
    assert [turn.speaker for turn in turns] == ["Alice"]


def test_length_cap_finalizes():
    assembler = make_assembler(max_chars=40)
    turns = feed(assembler, 0.0, 3.0, " " + "word " * 12, 3.0)
    assert len(turns) == 1


def test_span_cap_finalizes():
    assembler = make_assembler(max_span_seconds=5.0)
    turns = feed(assembler, 0.0, 6.0, " still talking without punctuation", 6.0)
    assert len(turns) == 1


def test_blank_fragment_is_ignored():
    assembler = make_assembler()
    assert feed(assembler, 0.0, 0.1, "   ", 0.1) == []
    feed(assembler, 0.0, 0.5, " the understanding", 0.5)
    turns = feed(assembler, 0.5, 1.0, "is clear.", 1.0)
    assert turns[0].text == "the understanding is clear."


def test_short_sentence_does_not_finalize_until_idle():
    assembler = make_assembler()
    assert feed(assembler, 0.0, 0.4, " Right.", 0.4) == []
    assert [turn.text for turn in assembler.flush_idle(3.0)] == ["Right."]


def test_session_clock_offsets_later_member_onto_shared_origin():
    clock = SessionClock()
    assert clock.register_member("mic", 1000.0) == 0.0
    assert clock.register_member("system", 1001.3) == 1.3
    assert clock.register_member("system", 5000.0) == 1.3
    assert clock.to_meeting_time("system", 10.0) == 11.3
    assert clock.to_meeting_time("mic", 10.0) == 10.0
    assert clock.to_meeting_time("unknown", 4.0) == 4.0


def test_session_clock_member_without_start_time_gets_zero_offset():
    clock = SessionClock()
    assert clock.register_member("a", None) == 0.0
    assert clock.register_member("b", 2000.0) == 0.0
    assert clock.register_member("c", 2002.0) == 2.0


def test_numeric_and_unknown_speaker_ids_never_break_assembly():
    """The live recorder emits numeric diarization ids, with -1 meaning no speaker was identified (this crashed Companion enable)."""
    unknown = make_assembler()
    turns = feed(unknown, 0.0, 2.0, " this finishes a sentence now.", 2.0, speaker=-1)
    assert [turn.speaker for turn in turns] == ["System Audio"]
    numbered = make_assembler()
    turns = feed(numbered, 0.0, 2.0, " this finishes a sentence now.", 2.0, speaker=0)
    assert [turn.speaker for turn in turns] == ["Speaker 1"]
    blank = make_assembler()
    turns = feed(blank, 0.0, 2.0, " this finishes a sentence now.", 2.0, speaker="  ")
    assert [turn.speaker for turn in turns] == ["System Audio"]
    named = make_assembler()
    turns = feed(named, 0.0, 2.0, " this finishes a sentence now.", 2.0, speaker=" Dana ")
    assert [turn.speaker for turn in turns] == ["Dana"]


def test_bare_word_fragments_from_a_local_engine_do_not_run_together():
    assembler = make_assembler()
    assert feed(assembler, 0.0, 1.0, "probably move", 1.0) == []
    assert feed(assembler, 1.0, 1.6, "forward", 1.6) == []
    turns = feed(assembler, 1.6, 2.4, "on that outside.", 2.4)
    assert [turn.text for turn in turns] == ["probably move forward on that outside."]


def test_join_fragments_handles_both_token_conventions():
    assert join_fragments("", "hello") == "hello"
    assert join_fragments("hello", "") == "hello"
    assert join_fragments("whatever", "time") == "whatever time"
    assert join_fragments("whatever", " time") == "whatever time"
    assert join_fragments("whatever ", "time") == "whatever time"
    assert join_fragments("discuss", ",") == "discuss,"
    assert join_fragments("really", "?") == "really?"
    assert join_fragments("thirteen", "Yeah") == "thirteen Yeah"

