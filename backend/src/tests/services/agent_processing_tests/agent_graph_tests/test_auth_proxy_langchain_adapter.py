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
