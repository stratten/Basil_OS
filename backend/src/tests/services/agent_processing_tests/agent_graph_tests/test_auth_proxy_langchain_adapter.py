import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
)
from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_langchain_adapter import (
    AuthProxyLangChainAdapter,
    create_langchain_llm_from_auth_proxy,
)


class FakeStreamResponse:
    """Async-context-manager stand-in for httpx's streaming response."""

    def __init__(self, status_code: int, lines=None, body: bytes = b""):
        self.status_code = status_code
        self._lines = list(lines or [])
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, method, url, json, headers):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def ok_stream(content: str = "ok") -> FakeStreamResponse:
    return FakeStreamResponse(
        200,
        lines=[
            f'data: {{"choices": [{{"delta": {{"content": "{content}"}}}}]}}',
            "data: [DONE]",
        ],
    )


def error_stream(status_code: int, body: bytes = b"") -> FakeStreamResponse:
    return FakeStreamResponse(status_code, body=body)


def make_adapter(**overrides) -> AuthProxyLangChainAdapter:
    defaults = {
        "auth_service_url": "https://auth.example",
        "access_token": "account-token",
        "model_id": "anthropic/claude-sonnet-4-5",
        "model_name": "claude-sonnet-4-5",
        "provider": "anthropic",
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    defaults.update(overrides)
    return AuthProxyLangChainAdapter(**defaults)


@pytest.mark.asyncio
async def test_langchain_adapter_uses_bearer_token():
    adapter = make_adapter()
    client = FakeClient([ok_stream()])

    acc = await adapter._stream_route_request(client, {"messages": []}, None)

    assert acc.content == "ok"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer account-token"
    assert "X-Trial-Key" not in client.calls[0]["headers"]
    assert "X-Basil-Setup-Agent-Key" not in client.calls[0]["headers"]


@pytest.mark.asyncio
async def test_langchain_adapter_maps_payment_required_response():
    adapter = make_adapter()
    client = FakeClient([error_stream(402, b'{"error":"payment required"}')])

    with pytest.raises(ValueError, match="Payment required"):
        await adapter._stream_route_request(client, {"messages": []}, None)


def test_create_langchain_adapter_carries_account_token():
    class FakeAuthProxyModel:
        access_token = "account-token"
        openrouter_model_id = "anthropic/claude-sonnet-4-5"
        model_name = "claude-sonnet-4-5"
        provider = "anthropic"
        temperature = 0.7
        max_tokens_to_sample = 4096

    adapter = create_langchain_llm_from_auth_proxy(FakeAuthProxyModel())

    assert adapter.access_token == "account-token"


def test_agent_executor_detects_account_auth_proxy():
    class FakeAuthProxyModel:
        access_token = "account-token"
        openrouter_model_id = "anthropic/claude-sonnet-4-5"
        model_name = "claude-sonnet-4-5"
        provider = "anthropic"
        temperature = 0.7
        max_tokens_to_sample = 4096

    class FakeCoordinator:
        _llm_model = FakeAuthProxyModel()

    adapter = create_langchain_llm(FakeCoordinator())

    assert isinstance(adapter, AuthProxyLangChainAdapter)
    assert adapter.access_token == "account-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
async def test_langchain_adapter_maps_retryable_statuses_to_transient_error(status_code):
    from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError

    adapter = make_adapter()
    client = FakeClient([error_stream(status_code, b'{"error":"busy"}')])

    with pytest.raises(TransientModelError, match=f"Auth service error \\({status_code}\\)"):
        await adapter._stream_route_request(client, {"messages": []}, None)


@pytest.mark.asyncio
async def test_langchain_adapter_keeps_overflow_400_as_value_error():
    from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError

    adapter = make_adapter()
    client = FakeClient([error_stream(400, b'{"error":"prompt is too long: 203619 tokens > 200000 maximum"}')])

    with pytest.raises(ValueError, match="prompt is too long") as exc_info:
        await adapter._stream_route_request(client, {"messages": []}, None)
    assert not isinstance(exc_info.value, TransientModelError)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_name", ["ReadTimeout", "ConnectError"])
async def test_langchain_adapter_maps_transport_failures_to_transient_error(monkeypatch, error_name):
    import httpx
    from langchain_core.messages import HumanMessage

    from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError

    async def failing_stream(self, client, payload, run_manager):
        raise getattr(httpx, error_name)("transport failure")

    monkeypatch.setattr(AuthProxyLangChainAdapter, "_stream_route_request", failing_stream)
    adapter = make_adapter()

    with pytest.raises(TransientModelError):
        await adapter._agenerate([HumanMessage(content="hi")])


@pytest.mark.asyncio
async def test_agent_loop_retries_typed_transient_adapter_errors():
    from langchain_core.messages import AIMessage, HumanMessage

    from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import (
        AgentRunFlags,
        ModelRecoveryMiddleware,
        TRANSIENT_RETRIES,
    )
    from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError

    class StubRequest:
        messages = [HumanMessage(content="hi")]

        def override(self, **kwargs):
            return self

    attempts = []

    async def handler(_request):
        attempts.append(1)
        if len(attempts) <= TRANSIENT_RETRIES:
            raise TransientModelError("auth proxy busy")
        return AIMessage(content="done")

    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1)
    middleware.backoff_base_seconds = 0

    response = await middleware.awrap_model_call(StubRequest(), handler)

    assert response.content == "done"
    assert len(attempts) == TRANSIENT_RETRIES + 1
