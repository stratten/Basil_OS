import asyncio
import json
from http import HTTPStatus
from typing import Any, List
from urllib.parse import parse_qs, urlsplit

import pytest

from api.services.meeting_cloud_asr.assemblyai_provider import AssemblyAIProvider
from api.services.meeting_cloud_asr.deepgram_provider import DeepgramProvider
from api.services.meeting_cloud_asr.models import EVENT_FINAL, EVENT_INTERIM, CloudAsrError

from .ws_server import vendor_server


def deepgram_results(text: str, *, is_final: bool, speech_final: bool = False, start: float = 0.0, duration: float = 1.0) -> str:
    return json.dumps(
        {
            "type": "Results",
            "start": start,
            "duration": duration,
            "is_final": is_final,
            "speech_final": speech_final,
            "channel": {"alternatives": [{"transcript": text, "words": []}]},
        }
    )


async def collect(provider: Any, count: int, timeout: float = 5.0) -> List[Any]:
    gathered: List[Any] = []

    async def gather() -> None:
        async for event in provider.events():
            gathered.append(event)
            if len(gathered) >= count:
                return

    await asyncio.wait_for(gather(), timeout=timeout)
    return gathered


def test_deepgram_sends_token_header_linear16_query_and_audio_then_close_stream() -> None:
    seen: dict = {"binary": [], "text": []}

    async def handler(connection: Any) -> None:
        seen["path"] = connection.request.path
        seen["authorization"] = connection.request.headers.get("Authorization")
        async for message in connection:
            if isinstance(message, bytes):
                seen["binary"].append(message)
                await connection.send(deepgram_results("hello wor", is_final=False))
                await connection.send(deepgram_results("hello world", is_final=True, speech_final=True, start=0.5, duration=1.5))
            else:
                seen["text"].append(json.loads(message))
                if json.loads(message).get("type") == "CloseStream":
                    await connection.send(deepgram_results("goodbye", is_final=True, start=2.0, duration=0.5))
                    await connection.close()

    async def scenario() -> List[Any]:
        async with vendor_server(handler) as url:
            provider = DeepgramProvider("dg-secret-key", base_url=url)
            await provider.open()
            await provider.send_audio(b"\x01\x00" * 1600)
            first = await collect(provider, 2)
            await provider.close()
            rest = [event async for event in provider.events()]
            return first + rest

    events = asyncio.run(scenario())
    query = parse_qs(urlsplit(seen["path"]).query)
    assert seen["authorization"] == "Token dg-secret-key"
    assert query["encoding"] == ["linear16"] and query["sample_rate"] == ["16000"] and query["channels"] == ["1"]
    assert query["interim_results"] == ["true"] and query["model"] == ["nova-3"]
    assert seen["binary"] == [b"\x01\x00" * 1600]
    assert {"type": "CloseStream"} in seen["text"]
    assert [(event.kind, event.text, event.utterance_end) for event in events] == [
        (EVENT_INTERIM, "hello wor", False),
        (EVENT_FINAL, "hello world", True),
        (EVENT_FINAL, "goodbye", False),
    ]
    assert (events[1].start_seconds, events[1].end_seconds) == (0.5, 2.0)


def test_deepgram_keep_alive_is_a_text_control_frame_while_no_audio_flows() -> None:
    frames: List[Any] = []

    async def handler(connection: Any) -> None:
        async for message in connection:
            frames.append(message)

    async def scenario() -> None:
        async with vendor_server(handler) as url:
            provider = DeepgramProvider("dg-secret-key", base_url=url, keepalive_seconds=0.05)
            await provider.open()
            await asyncio.sleep(0.3)
            await provider.close()

    asyncio.run(scenario())
    keep_alives = [frame for frame in frames if isinstance(frame, str) and json.loads(frame) == {"type": "KeepAlive"}]
    assert len(keep_alives) >= 2
    assert not [frame for frame in frames if isinstance(frame, bytes)]


def test_deepgram_ignores_non_results_and_empty_interims_but_keeps_an_empty_utterance_end() -> None:
    provider = DeepgramProvider("k")
    assert provider._parse({"type": "Metadata"}) == []
    assert provider._parse(json.loads(deepgram_results("", is_final=False))) == []
    marker = provider._parse(json.loads(deepgram_results("", is_final=True, speech_final=True)))
    assert [(event.kind, event.text, event.utterance_end) for event in marker] == [(EVENT_FINAL, "", True)]


def test_a_rejected_key_is_reported_without_echoing_the_key() -> None:
    async def handler(connection: Any) -> None:
        await connection.wait_closed()

    async def scenario() -> CloudAsrError:
        async with vendor_server(handler, reject_status=HTTPStatus.UNAUTHORIZED) as url:
            provider = DeepgramProvider("dg-secret-key", base_url=url)
            with pytest.raises(CloudAsrError) as raised:
                await provider.open()
            return raised.value

    error = asyncio.run(scenario())
    assert str(error) == "Deepgram rejected the API key."
    assert "dg-secret-key" not in str(error)


def test_an_unreachable_endpoint_raises_a_user_safe_error() -> None:
    async def scenario() -> CloudAsrError:
        provider = DeepgramProvider("dg-secret-key", base_url="ws://127.0.0.1:1/listen", connect_timeout_seconds=2.0)
        with pytest.raises(CloudAsrError) as raised:
            await provider.open()
        return raised.value

    assert str(asyncio.run(scenario())) == "Could not connect to Deepgram."


def test_a_dropped_connection_ends_the_event_stream_with_an_error() -> None:
    async def handler(connection: Any) -> None:
        await connection.recv()
        await connection.close(code=1011)

    async def scenario() -> None:
        async with vendor_server(handler) as url:
            provider = DeepgramProvider("k", base_url=url)
            await provider.open()
            await provider.send_audio(b"\x00\x00" * 160)
            with pytest.raises(CloudAsrError) as raised:
                async for _ in provider.events():
                    pass
            assert "connection" in str(raised.value)
            await provider.close()

    asyncio.run(scenario())


def test_a_vendor_error_message_fails_the_stream_with_its_description() -> None:
    async def handler(connection: Any) -> None:
        await connection.recv()
        await connection.send(json.dumps({"type": "Error", "description": "quota exceeded"}))
        await connection.wait_closed()

    async def scenario() -> str:
        async with vendor_server(handler) as url:
            provider = DeepgramProvider("k", base_url=url)
            await provider.open()
            await provider.send_audio(b"\x00\x00" * 160)
            with pytest.raises(CloudAsrError) as raised:
                async for _ in provider.events():
                    pass
            await provider.close()
            return str(raised.value)

    assert "quota exceeded" in asyncio.run(scenario())


def test_assemblyai_uses_a_raw_key_pcm_query_converts_milliseconds_and_dedupes_formatted_turns() -> None:
    seen: dict = {"text": []}

    async def handler(connection: Any) -> None:
        seen["path"] = connection.request.path
        seen["authorization"] = connection.request.headers.get("Authorization")
        async for message in connection:
            if isinstance(message, bytes):
                words = [{"text": "hello", "start": 500, "end": 900}, {"text": "world", "start": 950, "end": 1400}]
                await connection.send(json.dumps({"type": "Begin", "id": "s1"}))
                await connection.send(json.dumps({"type": "Turn", "turn_order": 0, "end_of_turn": False, "transcript": "hello", "words": words[:1]}))
                await connection.send(json.dumps({"type": "Turn", "turn_order": 0, "end_of_turn": True, "transcript": "hello world", "words": words}))
                await connection.send(json.dumps({"type": "Turn", "turn_order": 0, "end_of_turn": True, "turn_is_formatted": True, "transcript": "Hello, world.", "words": words}))
                await connection.send(json.dumps({"type": "Turn", "turn_order": 1, "end_of_turn": False, "transcript": "", "words": []}))
            else:
                seen["text"].append(json.loads(message))
                if json.loads(message).get("type") == "Terminate":
                    await connection.send(json.dumps({"type": "Termination", "audio_duration_seconds": 1}))
                    await connection.close()

    async def scenario() -> List[Any]:
        async with vendor_server(handler) as url:
            provider = AssemblyAIProvider("aai-secret-key", base_url=url)
            await provider.open()
            await provider.send_audio(b"\x01\x00" * 1600)
            events = await collect(provider, 2)
            await provider.close()
            events.extend([event async for event in provider.events()])
            return events

    events = asyncio.run(scenario())
    query = parse_qs(urlsplit(seen["path"]).query)
    assert seen["authorization"] == "aai-secret-key"
    assert query == {"sample_rate": ["16000"], "encoding": ["pcm_s16le"]}
    assert {"type": "Terminate"} in seen["text"]
    assert [(event.kind, event.text, event.utterance_end) for event in events] == [
        (EVENT_INTERIM, "hello", False),
        (EVENT_FINAL, "hello world", True),
    ]
    assert (events[1].start_seconds, events[1].end_seconds) == (0.5, 1.4)
