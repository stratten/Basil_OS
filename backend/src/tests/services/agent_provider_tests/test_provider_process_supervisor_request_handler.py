"""Coverage that ProviderProcessSupervisor.register_request_handler passes through to the client (Package 4A)."""

from __future__ import annotations

from api.services.agent_providers.runtime.process_supervisor import ProviderProcessSupervisor


class _FakeClient:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register_request_handler(self, method, handler) -> None:
        self.registered[method] = handler

    def register_notification_handler(self, method, handler) -> None:
        pass


def test_register_request_handler_delegates_to_the_underlying_client() -> None:
    supervisor = ProviderProcessSupervisor.__new__(ProviderProcessSupervisor)
    fake_client = _FakeClient()
    supervisor._client = fake_client

    async def _handler(params):
        return {"outcome": "decline"}

    supervisor.register_request_handler("elicitation/create", _handler)

    assert fake_client.registered["elicitation/create"] is _handler
