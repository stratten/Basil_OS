from api.services.meeting_companion.prompts import RULES, TRIGGER_DESCRIPTIONS, build_evaluation_prompt


def test_question_trigger_allows_general_knowledge_answers_and_skips_private_facts():
    text = TRIGGER_DESCRIPTIONS["question"]
    assert "do not know" in text
    assert "From general knowledge:" in text
    assert "only a participant could know" in text


def test_rules_make_missing_attachments_no_reason_for_silence_and_keep_the_provenance_guard():
    assert "never a reason for silence on its own" in RULES
    assert "Never present general knowledge as coming from the transcript or the attached files" in RULES
    assert "Silence is the default." in RULES


def test_prompt_carries_the_rules_and_the_trigger_text():
    prompt = build_evaluation_prompt(
        trigger="question",
        conversation_state="",
        already_shown=[],
        context_status="none_attached",
        context_text="",
        watch_instruction=None,
        window_text="[t-00001 @ 00:05] Speaker: I don't know what the justification for this is.",
        new_line_ids=["t-00001"],
    )
    assert "From general knowledge:" in prompt
    assert "(no files are attached)" in prompt
