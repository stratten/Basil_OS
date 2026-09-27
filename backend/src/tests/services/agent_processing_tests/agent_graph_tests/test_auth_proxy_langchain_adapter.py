import pytest

from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_langchain_adapter import (
    AuthProxyLangChainAdapter,
    create_langchain_llm_from_auth_proxy,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
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
            'data: {"choices": [{"delta": {"content": "%s"}}]}' % content,
            "data: [DONE]",
        ],
    )


def error_stream(status_code: int, body: dict) -> FakeStreamResponse:
    import json as _json

    return FakeStreamResponse(status_code, body=_json.dumps(body).encode())


def make_adapter(**overrides) -> AuthProxyLangChainAdapter:
    defaults = {
        "auth_service_url": "https://auth.example",
        "access_token": None,
        "trial_key": "trial-key",
        "model_id": "anthropic/claude-sonnet-4-5",
        "model_name": "claude-sonnet-4-5",
        "provider": "anthropic",
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    defaults.update(overrides)
    return AuthProxyLangChainAdapter(**defaults)


@pytest.mark.asyncio
async def test_langchain_adapter_uses_trial_key_first():
    adapter = make_adapter(access_token="account-token")
    client = FakeClient([ok_stream()])

    acc = await adapter._stream_route_request(client, {"messages": []}, None)

    assert acc.content == "ok"
    assert client.calls[0]["headers"]["X-Trial-Key"] == "trial-key"
    assert "Authorization" not in client.calls[0]["headers"]


@pytest.mark.asyncio
async def test_langchain_adapter_retries_with_account_after_trial_exhaustion():
    adapter = make_adapter(access_token="account-token")
    client = FakeClient([
        error_stream(402, {"error": "trial exhausted"}),
        ok_stream(),
    ])

    acc = await adapter._stream_route_request(client, {"messages": []}, None)

    assert acc.content == "ok"
    assert client.calls[0]["headers"]["X-Trial-Key"] == "trial-key"
    assert client.calls[1]["headers"]["Authorization"] == "Bearer account-token"
    assert "X-Trial-Key" not in client.calls[1]["headers"]


def test_create_langchain_adapter_carries_trial_key_without_account_token():
    class FakeAuthProxyModel:
        access_token = None
        trial_key = "trial-key"
        openrouter_model_id = "anthropic/claude-sonnet-4-5"
        model_name = "claude-sonnet-4-5"
        provider = "anthropic"
        temperature = 0.7
        max_tokens_to_sample = 4096

    adapter = create_langchain_llm_from_auth_proxy(FakeAuthProxyModel())

    assert adapter.trial_key == "trial-key"
    assert adapter.access_token is None


def test_langchain_adapter_uses_setup_agent_header_without_trial_or_bearer_headers():
    adapter = make_adapter(
        access_token=None,
        trial_key=None,
        setup_agent_key="setup-agent-secret",
    )

    headers = adapter._build_headers()

    assert headers["X-Basil-Setup-Agent-Key"] == "setup-agent-secret"
    assert "X-Trial-Key" not in headers
    assert "Authorization" not in headers
    assert adapter._auth_label() == "setup_agent"


def test_agent_executor_detects_trial_only_auth_proxy():
    class FakeAuthProxyModel:
        access_token = None
        trial_key = "trial-key"
        openrouter_model_id = "anthropic/claude-sonnet-4-5"
        model_name = "claude-sonnet-4-5"
        provider = "anthropic"
        temperature = 0.7
        max_tokens_to_sample = 4096

    class FakeCoordinator:
        _llm_model = FakeAuthProxyModel()

    adapter = create_langchain_llm(FakeCoordinator())

    assert isinstance(adapter, AuthProxyLangChainAdapter)
    assert adapter.trial_key == "trial-key"
