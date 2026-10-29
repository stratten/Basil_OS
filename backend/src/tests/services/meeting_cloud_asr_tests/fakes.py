"""Shared fakes: a scriptable provider, a recorder, and a recording status registry."""

import asyncio
from typing import Any, Dict, List, Optional

from api.services.meeting_cloud_asr.models import AsrEvent
from api.services.meeting_cloud_asr.registry import CloudStatusRegistry

END = object()


class FakeProvider:
    name = "fake"

    def __init__(self, *, open_error: Optional[Exception] = None, final_on_close: Optional[AsrEvent] = None) -> None:
        self.open_error = open_error
        self.final_on_close = final_on_close
        self.sent: List[bytes] = []
        self.opened = False
        self.closed = 0
        self.open_gate: Optional[asyncio.Event] = None
        self._queue: asyncio.Queue = asyncio.Queue()

    async def open(self) -> None:
        if self.open_gate is not None:
            await self.open_gate.wait()
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    async def send_audio(self, pcm: bytes) -> None:
        self.sent.append(pcm)

    def push(self, item: Any) -> None:
        self._queue.put_nowait(item)

    async def events(self):
        while True:
            item = await self._queue.get()
            if item is END:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        self.closed += 1
        if self.final_on_close is not None and self.closed == 1:
            self._queue.put_nowait(self.final_on_close)
        self._queue.put_nowait(END)


class FakeRecorder:
    def __init__(self) -> None:
        self.segments: List[Dict[str, Any]] = []
        self.transcription_lag_seconds = 0.0

    def add_transcript_segment(self, **segment: Any) -> None:
        self.segments.append(segment)


def recording_registry() -> tuple:
    frames: List[Dict[str, Any]] = []

    async def broadcaster(frame: Dict[str, Any]) -> None:
        frames.append(frame)

    return CloudStatusRegistry(broadcaster), frames


async def settle(times: int = 6) -> None:
    for _ in range(times):
        await asyncio.sleep(0)
