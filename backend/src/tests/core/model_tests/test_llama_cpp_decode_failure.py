"""A native llama_decode failure is classified, retried once at half the context when memory is the cause, and otherwise surfaced as a typed error."""

from types import SimpleNamespace

import pytest

from api.core.models.base_model import ModelState
from api.core.models.reasoning import llama_cpp_model
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.core.models.reasoning.local_model_failure import (
    LocalModelDecodeError,
    LocalModelFailureKind,
    failure_payload,
    find_local_model_failure,
    parse_decode_failure,
    recovery_actions,
)

GOOD_RESPONSE = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}


class FakeLlama:
    """A native context whose chat calls follow a script of outcomes: an Exception to raise or a response to return."""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.closed = 0
        self.calls = 0

    def close(self) -> None:
        self.closed += 1

    def create_chat_completion(self, stream=False, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if stream:
            return self._stream(outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _stream(self, outcome):
        for item in outcome:
            if isinstance(item, Exception):
                raise item
            yield item


@pytest.fixture
def isolated(monkeypatch):
    cache: dict = {}
    monkeypatch.setattr(llama_cpp_model, "_MODEL_CACHE", cache)
    monkeypatch.setattr(llama_cpp_model, "_WRAPPERS_BY_CACHE_KEY", {})
    monkeypatch.setattr(llama_cpp_model, "_CONTEXT_CEILINGS_BY_KEY", {})
    return cache


def decode_failure(code: int) -> RuntimeError:
    return RuntimeError(f"llama_decode returned {code}")


def make_model(tmp_path, cache, first_llama, *, n_ctx=32768, replacement=None):
    path = tmp_path / "model.gguf"
    cache[str(path.resolve())] = first_llama
    model = LlamaCppModel.__new__(LlamaCppModel)
    model.state = ModelState.READY
    model.model_path = path
    model.llm = first_llama
    model.n_ctx = n_ctx
    model.max_context_length = n_ctx
    reload_log = []

    def plan_native_load():
        return SimpleNamespace(n_ctx=(llama_cpp_model._context_ceiling_for(str(path.resolve())) or n_ctx))

    def open_native_context(cache_key, load_plan):
        reload_log.append((cache_key, load_plan.n_ctx))
        if replacement is None:
            raise RuntimeError("no replacement context available")
        cache[cache_key] = replacement
        return replacement

    model._plan_native_load = plan_native_load
    model._open_native_context = open_native_context
    return model, reload_log


@pytest.mark.parametrize(
    ("code", "kind"),
    [(-3, LocalModelFailureKind.MEMORY), (-2, LocalModelFailureKind.MEMORY), (1, LocalModelFailureKind.CONTEXT_FULL), (-1, LocalModelFailureKind.INVALID_INPUT)],
)
def test_decode_return_codes_are_classified(code, kind):
    failure = parse_decode_failure(decode_failure(code))

    assert failure.code == code
    assert failure.kind is kind


@pytest.mark.parametrize("message", ["llama_decode returned 2", "something else failed", "", "llama_decode returned"])
def test_aborted_decodes_and_unrelated_errors_are_not_failures(message):
    assert parse_decode_failure(RuntimeError(message)) is None


def test_a_memory_failure_reloads_at_half_the_context_and_the_call_succeeds(tmp_path, isolated):
    broken = FakeLlama([decode_failure(-3)])
    healthy = FakeLlama([GOOD_RESPONSE])
    model, reload_log = make_model(tmp_path, isolated, broken, replacement=healthy)

    result = model._create_chat_completion(messages=[{"role": "user", "content": "hi"}])

    assert result.response == GOOD_RESPONSE
    assert reload_log == [(str((tmp_path / "model.gguf").resolve()), 16384)]
    assert model.n_ctx == 16384 and model.max_context_length == 16384
    assert model.llm is healthy and model.state == ModelState.READY
    assert broken.closed == 1
    assert llama_cpp_model._context_ceiling_for(str((tmp_path / "model.gguf").resolve())) == 16384


def test_a_second_decode_failure_after_the_reload_raises_the_typed_error_with_the_retry_context(tmp_path, isolated):
    broken = FakeLlama([decode_failure(-3)])
    still_broken = FakeLlama([decode_failure(-3)])
    model, _ = make_model(tmp_path, isolated, broken, replacement=still_broken)

    with pytest.raises(LocalModelDecodeError) as caught:
        model._create_chat_completion(messages=[])

    error = caught.value
    assert error.kind is LocalModelFailureKind.MEMORY
    assert error.code == -3
    assert error.retried_at_context == 16384
    assert "ran out of memory" in str(error)
    assert isinstance(error.__cause__, RuntimeError)


def test_a_prompt_that_does_not_fit_is_not_retried_at_a_smaller_context(tmp_path, isolated):
    llama = FakeLlama([decode_failure(1)])
    model, reload_log = make_model(tmp_path, isolated, llama, replacement=FakeLlama([GOOD_RESPONSE]))

    with pytest.raises(LocalModelDecodeError) as caught:
        model._create_chat_completion(messages=[])

    assert caught.value.kind is LocalModelFailureKind.CONTEXT_FULL
    assert caught.value.retried_at_context is None
    assert reload_log == []
    assert llama.closed == 0


def test_a_context_already_at_the_floor_is_not_halved_again(tmp_path, isolated):
    llama = FakeLlama([decode_failure(-3)])
    model, reload_log = make_model(tmp_path, isolated, llama, n_ctx=6144, replacement=FakeLlama([GOOD_RESPONSE]))

    with pytest.raises(LocalModelDecodeError) as caught:
        model._create_chat_completion(messages=[])

    assert caught.value.retried_at_context is None
    assert reload_log == []


def test_a_reload_that_itself_fails_surfaces_the_typed_error_instead_of_the_reload_error(tmp_path, isolated):
    model, reload_log = make_model(tmp_path, isolated, FakeLlama([decode_failure(-3)]), replacement=None)

    with pytest.raises(LocalModelDecodeError) as caught:
        model._create_chat_completion(messages=[])

    assert caught.value.retried_at_context is None
    assert len(reload_log) == 1


def test_an_unrelated_runtime_error_passes_through_untouched(tmp_path, isolated):
    boom = RuntimeError("tokenizer exploded")
    model, reload_log = make_model(tmp_path, isolated, FakeLlama([boom]), replacement=FakeLlama([GOOD_RESPONSE]))

    with pytest.raises(RuntimeError) as caught:
        model._create_chat_completion(messages=[])

    assert caught.value is boom
    assert reload_log == []


def test_a_stream_that_fails_before_its_first_chunk_is_retried(tmp_path, isolated):
    broken = FakeLlama([[decode_failure(-3)]])
    healthy = FakeLlama([[{"id": 1}, {"id": 2}]])
    model, _ = make_model(tmp_path, isolated, broken, replacement=healthy)

    chunks = list(model._stream_chat_completion(messages=[]))

    assert chunks == [{"id": 1}, {"id": 2}]
    assert model.n_ctx == 16384


def test_a_stream_that_fails_after_producing_text_is_not_replayed(tmp_path, isolated):
    broken = FakeLlama([[{"id": 1}, decode_failure(-3)]])
    healthy = FakeLlama([[{"id": 9}]])
    model, reload_log = make_model(tmp_path, isolated, broken, replacement=healthy)

    received = []
    with pytest.raises(LocalModelDecodeError) as caught:
        for chunk in model._stream_chat_completion(messages=[]):
            received.append(chunk)

    assert received == [{"id": 1}]
    assert caught.value.retried_at_context is None
    assert reload_log == []


def test_the_failure_is_found_through_a_wrapped_cause_chain():
    error = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="m.gguf", n_ctx=32768)
    try:
        try:
            raise error
        except LocalModelDecodeError as inner:
            raise ValueError("agent step failed") from inner
    except ValueError as outer:
        assert find_local_model_failure(outer) is error
    assert find_local_model_failure(RuntimeError("other")) is None
    assert find_local_model_failure(None) is None


def test_the_payload_offers_every_recovery_action_for_memory_failures_and_carries_no_prompt_text():
    error = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="qwen.gguf", n_ctx=32768, retried_at_context=16384)

    payload = failure_payload(error)

    assert payload["type"] == "local_model_failure"
    assert payload["kind"] == "memory"
    assert [action["id"] for action in payload["actions"]] == ["retry", "smaller_model", "cloud_or_key", "show_logs", "report"]
    assert payload["retried_at_context"] == 16384
    assert payload["detail"] == "llama_decode returned -3 with a context of 32768 tokens"
    assert "llama_decode" not in payload["message"]


def test_an_invalid_input_failure_does_not_suggest_a_smaller_model():
    assert [action["id"] for action in recovery_actions(LocalModelFailureKind.INVALID_INPUT)] == ["retry", "show_logs", "report"]


def test_the_setup_error_event_carries_the_plain_message_and_the_recovery_actions():
    from api.services.setup_assistant.agent_graph.setup_agent_errors import setup_error_payload

    error = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="qwen.gguf", n_ctx=32768)

    payload = setup_error_payload(RuntimeError("agent failed"), "run-1")
    assert payload == {"message": "agent failed", "run_id": "run-1"}

    try:
        raise error
    except LocalModelDecodeError as caught:
        wrapped = ValueError("turn failed")
        wrapped.__cause__ = caught
    described = setup_error_payload(wrapped, "run-2")

    assert described["message"] == str(error)
    assert described["local_model_failure"]["kind"] == "memory"
    assert "llama_decode" not in described["message"]


@pytest.mark.asyncio
async def test_a_failed_agent_task_reports_the_plain_explanation_not_the_native_message(monkeypatch):
    from api.services.agent_processing.lifecycle.submission.agent_task_processing import agent_task_workflow_result_service as module

    error = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="qwen.gguf", n_ctx=32768)

    class FailingCoordinator:
        def __init__(self, **kwargs):
            pass

        async def _execute_with_tools(self, *args, **kwargs):
            try:
                raise error
            except LocalModelDecodeError as inner:
                raise RuntimeError("workflow step failed") from inner

    class LedgerlessDatabase:
        async def get_agent_task(self, agent_task_id):
            return None

    monkeypatch.setattr(module, "WorkflowCoordinator", FailingCoordinator)
    service = module.AgentTaskWorkflowResultService(db_service=LedgerlessDatabase())
    request = SimpleNamespace(
        agent_task="summarize my day",
        agent_task_id=None,
        active_app="Mail",
        full_screen_text="",
        screen_text="",
    )

    result = await service.execute_multi_step_workflow({}, request)

    assert result.success is False
    assert result.user_feedback == str(error)
    assert result.error_message == str(error)
    assert "llama_decode" not in result.user_feedback
    assert "Workflow execution failed" not in result.user_feedback


@pytest.mark.asyncio
async def test_other_agent_task_failures_keep_their_original_text(monkeypatch):
    from api.services.agent_processing.lifecycle.submission.agent_task_processing import agent_task_workflow_result_service as module

    class FailingCoordinator:
        def __init__(self, **kwargs):
            pass

        async def _execute_with_tools(self, *args, **kwargs):
            raise RuntimeError("tool crashed")

    class LedgerlessDatabase:
        async def get_agent_task(self, agent_task_id):
            return None

    monkeypatch.setattr(module, "WorkflowCoordinator", FailingCoordinator)
    service = module.AgentTaskWorkflowResultService(db_service=LedgerlessDatabase())
    request = SimpleNamespace(agent_task="x", agent_task_id=None, active_app="", full_screen_text="", screen_text="")

    result = await service.execute_multi_step_workflow({}, request)

    assert result.user_feedback == "Workflow execution failed: tool crashed"


def test_the_message_claims_a_smaller_retry_only_when_one_happened():
    retried = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="m.gguf", n_ctx=16384, retried_at_context=16384)
    not_retried = LocalModelDecodeError(code=-3, kind=LocalModelFailureKind.MEMORY, model_name="m.gguf", n_ctx=6144)

    assert "already tried again" in str(retried)
    assert "already tried again" not in str(not_retried)
