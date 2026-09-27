from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from api.services.agent_providers.acp.session_client import (
    ACP_PROTOCOL_VERSION,
    AcpAuthMethod,
    AcpClientClosedError,
    AcpClientError,
    AcpClientProtocolError,
    AcpClientTimeoutError,
    AcpRemoteRequestError,
    AcpSessionClient,
)
from api.services.agent_providers.acp.protocol import parse_acp_initialize_result


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_providers.testing.acp_session_fixture",
        "--fixture-mode",
        mode,
    )


@pytest.mark.asyncio
async def test_initialize_and_full_prompt_lifecycle_with_ordered_notifications_and_incoming_permission_request() -> None:
    received_notifications: list[dict[str, Any]] = []
    received_permission_params: list[dict[str, Any]] = []

    async def handle_update(params: Mapping[str, Any]) -> None:
        received_notifications.append(dict(params))

    async def handle_permission_request(params: Mapping[str, Any]) -> dict[str, Any]:
        received_permission_params.append(dict(params))
        return {"outcome": {"outcome": "selected", "optionId": "allow"}}

    async with AcpSessionClient(fixture_argv("success"), cwd=str(SOURCE_ROOT)) as client:
        client.register_notification_handler("session/update", handle_update)
        client.register_request_handler("session/request_permission", handle_permission_request)

        init_result = await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )
        assert init_result.protocol_version == ACP_PROTOCOL_VERSION
        assert init_result.agent_capabilities == {"session": {}}
        assert init_result.agent_info == {"name": "Basil ACP session fixture", "version": "1.0.0"}

        session = await client.create_session(cwd="/workspace/example")
        assert session.session_id == "fixture-session-1"

        prompt_result = await client.send_prompt(
            session_id=session.session_id,
            prompt=[{"type": "text", "text": "run the tests"}],
        )
        assert prompt_result == {}

    message_chunks = [
        notification["update"]["text"]
        for notification in received_notifications
        if notification["update"].get("kind") == "message_chunk"
    ]
    assert message_chunks == ["step 1", "step 2"]
    assert received_notifications[-1]["update"]["kind"] == "state_update"
    assert received_notifications[-1]["update"]["stopReason"] == "end_turn"
    assert len(received_permission_params) == 1
    assert received_permission_params[0]["title"] == "Run tests"
    assert received_permission_params[0]["description"] == (
        "The fixture requests permission to run its test command."
    )


@pytest.mark.asyncio
async def test_authenticate_selects_an_advertised_method_before_session_creation() -> None:
    async with AcpSessionClient(
        fixture_argv("auth_success"), cwd=str(SOURCE_ROOT)
    ) as client:
        result = await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )

        assert result.auth_methods == (
            AcpAuthMethod(
                method_id="api-key",
                name="API Key",
                description=None,
            ),
        )
        await client.authenticate(
            method_id="api-key",
            advertised_methods=result.auth_methods,
        )
        session = await client.create_session(cwd="/workspace/example")

    assert session.session_id == "fixture-session-1"


@pytest.mark.asyncio
async def test_authenticate_rejects_an_unadvertised_configured_method_without_sending_a_request() -> None:
    async with AcpSessionClient(
        fixture_argv("auth_unadvertised_method"), cwd=str(SOURCE_ROOT)
    ) as client:
        result = await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )

        with pytest.raises(
            AcpClientProtocolError,
            match="configured ACP authentication method was not advertised by the agent",
        ):
            await client.authenticate(
                method_id="api-key",
                advertised_methods=result.auth_methods,
            )


@pytest.mark.asyncio
async def test_authenticate_surfaces_a_remote_rejection_without_poisoning_the_transport() -> None:
    async with AcpSessionClient(
        fixture_argv("auth_remote_rejection"), cwd=str(SOURCE_ROOT)
    ) as client:
        result = await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )

        with pytest.raises(AcpRemoteRequestError) as error:
            await client.authenticate(
                method_id="api-key",
                advertised_methods=result.auth_methods,
            )

        assert error.value.code == -32001
        assert error.value.message_text == "Authentication required"
        assert client._transport.reader_error is None


@pytest.mark.parametrize(
    "auth_methods",
    (
        {},
        [{"name": "API Key"}],
        [{"id": 1}],
        [{"id": ""}],
        [{"id": "api key"}],
        [{"id": "api-key"}, {"id": "api-key"}],
    ),
)
def test_initialize_rejects_malformed_auth_methods(auth_methods: object) -> None:
    with pytest.raises(AcpClientProtocolError):
        parse_acp_initialize_result(
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "capabilities": {},
                "info": {"name": "fixture", "version": "1.0.0"},
                "authMethods": auth_methods,
            }
        )


@pytest.mark.asyncio
async def test_cancel_session_sends_notification_and_receives_final_state_update() -> None:
    received_event = asyncio.Event()
    received_updates: list[dict[str, Any]] = []

    async def handle_update(params: Mapping[str, Any]) -> None:
        received_updates.append(dict(params))
        received_event.set()

    async with AcpSessionClient(fixture_argv("cancel_notification"), cwd=str(SOURCE_ROOT)) as client:
        client.register_notification_handler("session/update", handle_update)
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        session = await client.create_session(cwd="/workspace/example")

        await client.cancel_session(session_id=session.session_id)
        await asyncio.wait_for(received_event.wait(), timeout=2.0)

    assert received_updates[0]["update"]["stopReason"] == "cancelled"


@pytest.mark.asyncio
async def test_initialize_negotiates_v1_and_preserves_common_session_lifecycle() -> None:
    updates: list[dict[str, Any]] = []

    async def handle_update(params: Mapping[str, Any]) -> None:
        updates.append(dict(params))

    async with AcpSessionClient(fixture_argv("v1_success"), cwd=str(SOURCE_ROOT)) as client:
        client.register_notification_handler("session/update", handle_update)
        result = await client.initialize(
            client_capabilities={"elicitation": {"form": {}}},
            client_info={"name": "Basil", "version": "0.1.0"},
        )
        assert result.protocol_version == 1
        assert result.agent_capabilities == {"sessionCapabilities": {"close": {}}}
        session = await client.create_session(cwd="/workspace/example")
        prompt_result = await client.send_prompt(
            session_id=session.session_id,
            prompt=[{"type": "text", "text": "read only"}],
        )

    assert prompt_result == {"stopReason": "end_turn"}
    assert [item["update"]["sessionUpdate"] for item in updates] == [
        "agent_message_chunk",
        "tool_call",
        "tool_call_update",
    ]


@pytest.mark.asyncio
async def test_initialize_accepts_v1_result_without_optional_agent_info() -> None:
    async with AcpSessionClient(
        fixture_argv("v1_without_agent_info"), cwd=str(SOURCE_ROOT)
    ) as client:
        result = await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )

    assert result.protocol_version == 1
    assert result.agent_capabilities == {"sessionCapabilities": {"close": {}}}
    assert result.agent_info is None


@pytest.mark.asyncio
async def test_v1_fallback_cancellation_uses_the_common_session_cancel_notification() -> None:
    cancelled = asyncio.Event()
    updates: list[dict[str, Any]] = []

    async def handle_update(params: Mapping[str, Any]) -> None:
        updates.append(dict(params))
        if params["update"].get("stopReason") == "cancelled":
            cancelled.set()

    async with AcpSessionClient(fixture_argv("v1_cancel_notification"), cwd=str(SOURCE_ROOT)) as client:
        client.register_notification_handler("session/update", handle_update)
        await client.initialize(
            client_capabilities={},
            client_info={"name": "Basil", "version": "0.1.0"},
        )
        session = await client.create_session(cwd="/workspace/example")
        await client.cancel_session(session_id=session.session_id)
        await asyncio.wait_for(cancelled.wait(), timeout=2.0)

    assert updates[0]["update"]["sessionUpdate"] == "state_update"
    assert updates[0]["update"]["stopReason"] == "cancelled"


@pytest.mark.asyncio
async def test_initialize_rejects_v1_result_without_agent_capabilities() -> None:
    async with AcpSessionClient(
        fixture_argv("v1_missing_agent_capabilities"), cwd=str(SOURCE_ROOT)
    ) as client:
        with pytest.raises(
            AcpClientProtocolError,
            match="initialize response agentCapabilities must be an object",
        ):
            await client.initialize(
                client_capabilities={},
                client_info={"name": "Basil", "version": "0.1.0"},
            )


@pytest.mark.asyncio
async def test_initialize_rejects_unsupported_protocol_version() -> None:
    async with AcpSessionClient(
        fixture_argv("unsupported_protocol_version"), cwd=str(SOURCE_ROOT)
    ) as client:
        with pytest.raises(
            AcpClientProtocolError, match="unsupported ACP protocol version"
        ):
            await client.initialize(
                client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
            )


@pytest.mark.asyncio
async def test_initialize_rejects_malformed_result_missing_agent_capabilities() -> None:
    async with AcpSessionClient(
        fixture_argv("malformed_initialize_result"), cwd=str(SOURCE_ROOT)
    ) as client:
        with pytest.raises(
            AcpClientProtocolError, match="initialize response capabilities must be an object"
        ):
            await client.initialize(
                client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
            )


@pytest.mark.asyncio
async def test_initialize_rejects_malformed_agent_info() -> None:
    async with AcpSessionClient(
        fixture_argv("malformed_agent_info"), cwd=str(SOURCE_ROOT)
    ) as client:
        with pytest.raises(
            AcpClientProtocolError,
            match="initialize response info must contain non-empty name and version strings",
        ):
            await client.initialize(
                client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
            )


@pytest.mark.asyncio
async def test_read_loop_poisons_client_after_an_unprompted_malformed_message() -> None:
    async with AcpSessionClient(fixture_argv("malformed_message"), cwd=str(SOURCE_ROOT)) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        with pytest.raises(AcpClientProtocolError, match="invalid JSON-RPC payload"):
            await client.create_session(cwd="/workspace/example-2")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_duplicate_response_for_resolved_request() -> None:
    async with AcpSessionClient(fixture_argv("duplicate_response"), cwd=str(SOURCE_ROOT)) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        with pytest.raises(AcpClientProtocolError, match="unknown or already-resolved id"):
            await client.create_session(cwd="/workspace/example-2")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_a_boolean_response_id() -> None:
    async with AcpSessionClient(
        fixture_argv("boolean_response_id"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})

        with pytest.raises(AcpClientProtocolError, match="unknown or already-resolved id"):
            await client.create_session(cwd="/workspace/example")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_a_response_with_result_and_error() -> None:
    async with AcpSessionClient(
        fixture_argv("response_with_result_and_error"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})

        with pytest.raises(AcpClientProtocolError, match="must not contain both result and error"):
            await client.create_session(cwd="/workspace/example")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_an_invalid_error_object_without_waiting_for_timeout() -> None:
    async with AcpSessionClient(
        fixture_argv("invalid_error_object"),
        cwd=str(SOURCE_ROOT),
        request_timeout_seconds=0.05,
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})

        with pytest.raises(AcpClientProtocolError, match="response error must be a JSON-RPC error object"):
            await client.create_session(cwd="/workspace/example")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_non_object_notification_params() -> None:
    async with AcpSessionClient(
        fixture_argv("invalid_notification_params"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        with pytest.raises(AcpClientProtocolError, match="notification params must be an object"):
            await client.create_session(cwd="/workspace/example-2")


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_a_boolean_incoming_request_id() -> None:
    async with AcpSessionClient(
        fixture_argv("invalid_incoming_request_id"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        with pytest.raises(AcpClientProtocolError, match="request id must be a string or non-boolean integer"):
            await client.create_session(cwd="/workspace/example-2")


@pytest.mark.asyncio
async def test_incoming_request_with_unsupported_method_receives_method_not_found_and_client_stays_healthy() -> None:
    async with AcpSessionClient(
        fixture_argv("unsupported_incoming_request"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        session_two = await client.create_session(cwd="/workspace/example-2")
        assert session_two.session_id == "fixture-session-2"


@pytest.mark.asyncio
async def test_incoming_duplicate_request_id_is_rejected_while_the_first_is_answered() -> None:
    received_markers: list[str] = []

    async def handle_permission_request(params: Mapping[str, Any]) -> dict[str, Any]:
        received_markers.append(params.get("marker", "unknown"))
        return {"outcome": {"outcome": "selected", "optionId": "allow"}}

    async with AcpSessionClient(
        fixture_argv("duplicate_incoming_request_id"), cwd=str(SOURCE_ROOT)
    ) as client:
        client.register_request_handler("session/request_permission", handle_permission_request)
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        assert client._process is not None
        await asyncio.wait_for(client._process.wait(), timeout=2.0)
        assert client._process.returncode == 0

    assert received_markers == ["A"]


@pytest.mark.asyncio
async def test_concurrent_requests_are_correlated_correctly_despite_out_of_order_responses() -> None:
    async with AcpSessionClient(
        fixture_argv("out_of_order_responses"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})

        session_a, session_b = await asyncio.gather(
            client.create_session(cwd="/workspace/a"),
            client.create_session(cwd="/workspace/b"),
        )

    assert session_a.session_id == "session-for-/workspace/a"
    assert session_b.session_id == "session-for-/workspace/b"


@pytest.mark.asyncio
async def test_send_prompt_times_out_when_peer_never_responds() -> None:
    async with AcpSessionClient(
        fixture_argv("no_response_after_prompt"),
        cwd=str(SOURCE_ROOT),
        request_timeout_seconds=1.0,
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        session = await client.create_session(cwd="/workspace/example")

        with pytest.raises(
            AcpClientTimeoutError, match="timed out waiting for JSON-RPC response id"
        ):
            await client.send_prompt(
                session_id=session.session_id, prompt=[{"type": "text", "text": "hi"}]
            )


@pytest.mark.asyncio
async def test_read_loop_accepts_large_valid_line_below_explicit_cap() -> None:
    async with AcpSessionClient(
        fixture_argv("large_valid_line"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(
            client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
        )
        await client.create_session(cwd="/workspace/example")
        large_session = await client.create_session(cwd="/workspace/example-2")

    assert large_session.session_id.startswith("fixture-session-large-")
    assert len(large_session.session_id) > 64 * 1024


@pytest.mark.asyncio
async def test_read_loop_poisons_client_on_oversized_line() -> None:
    async with AcpSessionClient(
        fixture_argv("transport_oversized_line"), cwd=str(SOURCE_ROOT)
    ) as client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        await client.create_session(cwd="/workspace/example")

        with pytest.raises(AcpClientProtocolError, match="exceeding the stream limit"):
            await client.create_session(cwd="/workspace/example-2")


@pytest.mark.asyncio
async def test_client_rejects_reinitialization_and_restart() -> None:
    client = AcpSessionClient(fixture_argv("success"), cwd=str(SOURCE_ROOT))
    async with client:
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        with pytest.raises(AcpClientError, match="already initialized"):
            await client.initialize(
                client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
            )

    with pytest.raises(AcpClientError, match="already started"):
        await client.start()


@pytest.mark.asyncio
async def test_client_rejects_session_operations_until_initialize_succeeds() -> None:
    async with AcpSessionClient(fixture_argv("success"), cwd=str(SOURCE_ROOT)) as client:
        with pytest.raises(AcpClientError, match="must be initialized before session operations"):
            await client.create_session(cwd="/workspace/example")
        with pytest.raises(AcpClientError, match="must be initialized before session operations"):
            await client.send_prompt(
                session_id="fixture-session-1", prompt=[{"type": "text", "text": "hi"}]
            )
        with pytest.raises(AcpClientError, match="must be initialized before session operations"):
            await client.cancel_session(session_id="fixture-session-1")

        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})
        session = await client.create_session(cwd="/workspace/example")
        assert session.session_id == "fixture-session-1"


@pytest.mark.asyncio
async def test_initialize_before_start_does_not_consume_the_single_initialize_attempt() -> None:
    client = AcpSessionClient(fixture_argv("success"), cwd=str(SOURCE_ROOT))

    with pytest.raises(AcpClientClosedError, match="not started or has been closed"):
        await client.initialize(client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"})

    async with client:
        result = await client.initialize(
            client_capabilities={}, client_info={"name": "Basil", "version": "0.1.0"}
        )
    assert result.protocol_version == ACP_PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_close_is_safe_to_call_multiple_times_and_without_starting() -> None:
    client = AcpSessionClient(fixture_argv("success"), cwd=str(SOURCE_ROOT))
    await client.close()
    await client.close()
    async with client:
        pass
    await client.close()


def test_client_rejects_empty_or_invalid_argv() -> None:
    with pytest.raises(ValueError, match="argv must contain at least one non-empty string"):
        AcpSessionClient([])
    with pytest.raises(ValueError, match="argv must contain at least one non-empty string"):
        AcpSessionClient([""])


def test_client_rejects_non_positive_request_timeout() -> None:
    with pytest.raises(ValueError, match="request_timeout_seconds must be greater than zero"):
        AcpSessionClient(["fixture"], request_timeout_seconds=0)
    with pytest.raises(ValueError, match="request_timeout_seconds must be greater than zero"):
        AcpSessionClient(["fixture"], request_timeout_seconds=float("nan"))
    with pytest.raises(ValueError, match="request_timeout_seconds must be greater than zero"):
        AcpSessionClient(["fixture"], request_timeout_seconds=float("inf"))
