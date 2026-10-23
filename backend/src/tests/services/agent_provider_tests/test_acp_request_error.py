"""Coverage that a registered request handler's AcpRequestError forwards its exact JSON-RPC code (Package 4A)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from api.services.agent_providers.acp.protocol import AcpRequestError
from api.services.agent_providers.acp.session_transport import AcpSessionTransport


SOURCE_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _source_root_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))


@pytest.mark.asyncio
async def test_a_request_handler_raising_acprequesterror_forwards_its_exact_code() -> None:
    transport = AcpSessionTransport(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        cwd=None,
        env=None,
        start_new_session=False,
        request_timeout_seconds=5.0,
    )

    captured: list[tuple[str | int, int, str]] = []

    async def _capture_error_response(
        request_id: str | int, *, code: int, message_text: str
    ) -> None:
        captured.append((request_id, code, message_text))

    transport._write_error_response = _capture_error_response  # type: ignore[method-assign]

    async def _reject_with_invalid_params(params):
        raise AcpRequestError(-32602, "rejected by test handler")

    transport.register_request_handler("elicitation/create", _reject_with_invalid_params)
    await transport._run_incoming_request("req-1", "elicitation/create", {})

    assert captured == [("req-1", -32602, "rejected by test handler")]
