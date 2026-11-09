"""MlxChatEngine answers like llama_cpp.Llama for the calls Basil makes, with every MLX dependency faked."""

import pytest

from api.core.models.reasoning.mlx_engine import MlxChatEngine

from .mlx_fakes import FakeTokenizer, make_engine, response

USER_HI = [{"role": "user", "content": "hi"}]


def test_load_passes_the_folder_to_the_loader_and_reports_the_context_window():
    harness = make_engine([], context_window=2048, model_dir="some-folder")
    assert harness.loaded == ["some-folder"]
    assert harness.engine.n_ctx() == 2048


def test_tokenize_respects_add_bos_and_ignores_invalid_utf8():
    engine = make_engine([]).engine
    assert engine.tokenize(b"ab", add_bos=True) == [1097, 1098]
    assert engine.tokenize(b"ab", add_bos=False) == [97, 98]
    assert engine.tokenize(b"a\xffb", add_bos=False) == [97, 98]


def test_detokenize_returns_bytes():
    assert make_engine([]).engine.detokenize([97, 98]) == b"ab"


def test_chat_completion_returns_an_openai_style_dict_and_forwards_sampling():
    harness = make_engine([response("Hel", 1), response("lo", 2, finish_reason="stop", prompt_tokens=12)])

    output = harness.engine.create_chat_completion(
        messages=USER_HI,
        max_tokens=64,
        temperature=0.2,
        top_p=0.9,
        top_k=20,
        min_p=0.05,
        repeat_penalty=1.1,
    )

    assert output["object"] == "chat.completion"
    assert output["choices"][0]["message"] == {"role": "assistant", "content": "Hello"}
    assert output["choices"][0]["finish_reason"] == "stop"
    assert output["usage"] == {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}
    call = harness.stream.calls[0]
    assert call["max_tokens"] == 64
    assert call["sampler"] == "sampler"
    assert call["logits_processors"] == ["processor"]
    assert call["prompt"] == harness.tokenizer.encode("<user>hi<assistant>", add_special_tokens=False)
    assert harness.samplers == [{"temp": 0.2, "top_p": 0.9, "min_p": 0.05, "top_k": 20}]
    assert harness.processors == [{"repetition_penalty": 1.1}]


def test_neutral_sampling_builds_no_logits_processors():
    harness = make_engine([response("a", 1, finish_reason="stop")])
    harness.engine.create_chat_completion(messages=USER_HI, max_tokens=8)
    assert harness.samplers == [{"temp": 0.0, "top_p": 1.0, "min_p": 0.0, "top_k": 0}]
    assert harness.processors == []
    assert harness.stream.calls[0]["logits_processors"] is None


def test_chat_template_receives_tools_and_a_generation_prompt():
    harness = make_engine([response("a", 1, finish_reason="stop")])
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    harness.engine.create_chat_completion(messages=USER_HI, tools=tools, max_tokens=8)
    harness.engine.create_chat_completion(messages=USER_HI, max_tokens=8)
    first, second = harness.tokenizer.template_calls
    assert first["tools"] == tools
    assert second["tools"] is None
    assert first["add_generation_prompt"] is True
    assert first["tokenize"] is False


def test_llama_only_options_are_accepted_and_ignored():
    harness = make_engine([response("{}", 1, finish_reason="stop")])
    output = harness.engine.create_chat_completion(
        messages=USER_HI,
        max_tokens=8,
        response_format={"type": "json_object", "schema": {}},
        tool_choice="auto",
        seed=1,
    )
    assert output["choices"][0]["message"]["content"] == "{}"


def test_streaming_yields_role_content_and_final_finish_chunks():
    harness = make_engine([response("Hel", 1), response("lo", 2, finish_reason="stop")])

    chunks = list(harness.engine.create_chat_completion(messages=USER_HI, stream=True, max_tokens=8))

    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    contents = [chunk["choices"][0]["delta"]["content"] for chunk in chunks if "content" in chunk["choices"][0]["delta"]]
    assert contents == ["Hel", "lo"]
    assert chunks[-1]["choices"][0]["delta"] == {}
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_closing_a_stream_early_closes_the_underlying_generator():
    harness = make_engine([response(letter, index + 1) for index, letter in enumerate("abcde")])

    stream = harness.engine.create_chat_completion(messages=USER_HI, stream=True, max_tokens=8)
    next(stream)
    next(stream)
    stream.close()

    assert harness.stream.closed is True
    assert harness.stream.consumed == 1


def test_stop_string_cuts_the_output_and_never_leaks_a_partial_stop():
    harness = make_engine([response("Hello <", 1), response("/tool", 2), response("> ignored", 3)])

    output = harness.engine.create_chat_completion(messages=USER_HI, max_tokens=64, stop=["</tool>"])

    assert output["choices"][0]["message"]["content"] == "Hello "
    assert output["choices"][0]["finish_reason"] == "stop"
    assert harness.stream.consumed == 3
    assert harness.stream.closed is True


def test_stop_may_be_a_plain_string():
    harness = make_engine([response("abEND cd", 1)])
    output = harness.engine.create_chat_completion(messages=USER_HI, max_tokens=64, stop="END")
    assert output["choices"][0]["message"]["content"] == "ab"


def test_a_held_back_partial_stop_is_flushed_when_generation_ends():
    harness = make_engine([response("abc <", 1), response("/to", 2, finish_reason="stop")])
    output = harness.engine.create_chat_completion(messages=USER_HI, max_tokens=64, stop=["</tool>"])
    assert output["choices"][0]["message"]["content"] == "abc </to"
    assert output["choices"][0]["finish_reason"] == "stop"


def test_length_finish_reason_is_reported():
    harness = make_engine([response("a", 1), response("b", 2, finish_reason="length")])
    output = harness.engine.create_chat_completion(messages=USER_HI, max_tokens=2)
    assert output["choices"][0]["finish_reason"] == "length"


def test_missing_finish_reason_is_inferred_from_the_token_budget():
    capped = make_engine([response("a", 1), response("b", 2)])
    uncapped = make_engine([response("a", 1), response("b", 2)])
    assert capped.engine.create_chat_completion(messages=USER_HI, max_tokens=2)["choices"][0]["finish_reason"] == "length"
    assert uncapped.engine.create_chat_completion(messages=USER_HI, max_tokens=10)["choices"][0]["finish_reason"] == "stop"


def test_completion_tokens_are_counted_when_the_backend_reports_none():
    harness = make_engine([response("a", None), response("b", None, finish_reason="stop")])
    output = harness.engine.create_chat_completion(messages=USER_HI, max_tokens=8)
    assert output["usage"]["completion_tokens"] == 2


@pytest.mark.parametrize("stream", [False, True])
def test_a_prompt_longer_than_the_context_window_raises_before_any_generation(stream):
    harness = make_engine([response("a", 1)], context_window=10)
    with pytest.raises(ValueError, match="exceed context window"):
        harness.engine.create_chat_completion(messages=USER_HI, stream=stream, max_tokens=8)
    assert harness.stream.calls == []


def test_raw_completion_returns_text_and_finish_reason():
    harness = make_engine([response("ab", 2, finish_reason="stop")])
    output = harness.engine.create_completion("Once", max_tokens=8, temperature=0.1, top_p=0.9, top_k=20, repeat_penalty=1.15)
    assert output["choices"][0] == {"index": 0, "text": "ab", "finish_reason": "stop"}
    assert harness.stream.calls[0]["prompt"] == harness.tokenizer.encode("Once", add_special_tokens=False)


def test_an_unloaded_engine_refuses_every_call():
    engine = MlxChatEngine("folder", 10, loader=lambda path: (object(), FakeTokenizer()))
    with pytest.raises(RuntimeError, match="not loaded"):
        engine.create_chat_completion(messages=USER_HI, max_tokens=8)
    with pytest.raises(RuntimeError, match="not loaded"):
        engine.tokenize(b"a")
    with pytest.raises(RuntimeError, match="not loaded"):
        engine.create_completion("a")


def test_close_unloads_and_clears_the_cache():
    harness = make_engine([])
    harness.engine.close()
    assert harness.cleared == [True]
    with pytest.raises(RuntimeError, match="not loaded"):
        harness.engine.tokenize(b"a")


def test_close_survives_a_failing_cache_clear():
    def failing_clearer():
        raise RuntimeError("no metal")

    engine = MlxChatEngine("folder", 10, loader=lambda path: (object(), FakeTokenizer()), cache_clearer=failing_clearer)
    engine.load()
    engine.close()
