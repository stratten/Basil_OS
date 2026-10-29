"""One cloud transcription session: buffers captured PCM, streams it to a provider, and turns results into the live transcript."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from .models import (
    PCM_BYTES_PER_SAMPLE,
    PCM_SAMPLE_RATE,
    STATE_CONNECTING,
    STATE_FALLBACK,
    STATE_STREAMING,
    CloudAsrError,
    StreamingAsrProvider,
)
from .registry import CloudStatusRegistry, SessionStatus, cloud_status_registry
from .transcript_builder import CloudTranscriptBuilder, TimelineForSample

logger = logging.getLogger(__name__)

SEND_CHUNK_BYTES = PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE // 10
MIN_FINAL_CHUNK_BYTES = SEND_CHUNK_BYTES // 2
MAX_BUFFERED_SECONDS = 30.0
STOP_FLUSH_SECONDS = 5.0
_STOP = object()

SendJson = Callable[[dict], Awaitable[None]]
FailureCallback = Callable[[str], None]


class CloudAsrSession:
    def __init__(
        self,
        *,
        provider: StreamingAsrProvider,
        provider_id: str,
        tier: str,
        base_sample: int,
        timeline_for_sample: TimelineForSample,
        meeting_recorder: Any,
        send_json: SendJson,
        on_failure: FailureCallback,
        registry: Optional[CloudStatusRegistry] = None,
    ) -> None:
        self._provider = provider
        self._provider_id = provider_id
        self._tier = tier
        self._recorder = meeting_recorder
        self._send_json = send_json
        self._on_failure = on_failure
        self._registry = registry or cloud_status_registry
        self._builder = CloudTranscriptBuilder(
            base_sample=base_sample,
            timeline_for_sample=timeline_for_sample,
            add_segment=self._add_segment,
        )
        self._chunks: asyncio.Queue = asyncio.Queue()
        self._buffered_bytes = 0
        self._max_buffered_bytes = int(MAX_BUFFERED_SECONDS * PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
        self._sent_bytes = 0
        self._runner: Optional[asyncio.Task] = None
        self._receiver: Optional[asyncio.Task] = None
        self._stopped = False
        self._failed = False
        self._state_task: Optional[asyncio.Task] = None

    @property
    def failed(self) -> bool:
        return self._failed

    def start(self) -> None:
        self._runner = asyncio.create_task(self._run())

    def feed(self, pcm: bytes) -> None:
        """Queue captured audio; never blocks the socket receive loop."""
        if self._stopped or self._failed or not pcm:
            return
        self._buffered_bytes += len(pcm)
        if self._buffered_bytes > self._max_buffered_bytes:
            self._schedule_failure("Cloud transcription is falling behind.")
            return
        self._chunks.put_nowait(pcm)

    async def stop(self) -> None:
        """Flush, let the provider return its last results, and release the registry entry; safe to call twice."""
        if self._stopped:
            return
        self._stopped = True
        try:
            if self._runner is not None and not self._failed:
                self._chunks.put_nowait(_STOP)
                try:
                    await asyncio.wait_for(asyncio.shield(self._runner), timeout=STOP_FLUSH_SECONDS)
                except asyncio.TimeoutError:
                    self._runner.cancel()
            await self._shutdown_provider()
            if self._receiver is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self._receiver), timeout=STOP_FLUSH_SECONDS + 20.0)
                except asyncio.TimeoutError:
                    self._receiver.cancel()
            tasks = [task for task in (self._runner, self._receiver, self._state_task) if task is not None]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._registry.update(id(self), None)

    def _add_segment(self, **segment: Any) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder.add_transcript_segment(**segment)
        except Exception as error:
            logger.error("Failed to record a cloud transcript segment: %s", error, exc_info=True)

    async def _set_state(self, state: str, reason: Optional[str] = None) -> None:
        await self._registry.update(id(self), SessionStatus(state, self._provider_id, self._tier, reason))

    async def _run(self) -> None:
        try:
            await self._set_state(STATE_CONNECTING)
            await self._provider.open()
            self._receiver = asyncio.create_task(self._receive())
            await self._set_state(STATE_STREAMING)
            await self._send_loop()
        except asyncio.CancelledError:
            raise
        except CloudAsrError as error:
            await self._fail(str(error))
        except Exception as error:
            logger.error("Cloud transcription failed: %s", error, exc_info=True)
            await self._fail("Cloud transcription failed.")

    async def _send_loop(self) -> None:
        outbox = bytearray()
        while True:
            item = await self._chunks.get()
            if item is _STOP:
                break
            self._buffered_bytes = max(0, self._buffered_bytes - len(item))
            outbox.extend(item)
            while len(outbox) >= SEND_CHUNK_BYTES:
                await self._provider.send_audio(bytes(outbox[:SEND_CHUNK_BYTES]))
                self._sent_bytes += SEND_CHUNK_BYTES
                del outbox[:SEND_CHUNK_BYTES]
        if len(outbox) >= MIN_FINAL_CHUNK_BYTES:
            await self._provider.send_audio(bytes(outbox))
            self._sent_bytes += len(outbox)

    async def _receive(self) -> None:
        try:
            async for event in self._provider.events():
                self._update_lag(event.end_seconds)
                if self._builder.apply(event):
                    await self._send_json(self._builder.front_data(self._lag_seconds(event.end_seconds)))
        except asyncio.CancelledError:
            raise
        except CloudAsrError as error:
            await self._fail(str(error))
        except Exception as error:
            logger.error("Cloud transcription results failed: %s", error, exc_info=True)
            await self._fail("Cloud transcription failed.")

    def _lag_seconds(self, result_end_seconds: float) -> float:
        sent_seconds = self._sent_bytes / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
        return max(0.0, sent_seconds - result_end_seconds)

    def _update_lag(self, result_end_seconds: float) -> None:
        if self._recorder is not None:
            self._recorder.transcription_lag_seconds = self._lag_seconds(result_end_seconds)

    def _schedule_failure(self, reason: str) -> None:
        if self._state_task is None or self._state_task.done():
            self._state_task = asyncio.create_task(self._fail(reason))

    async def _fail(self, reason: str) -> None:
        if self._failed or self._stopped:
            return
        self._failed = True
        logger.warning("Cloud transcription ended: %s", reason)
        await self._set_state(STATE_FALLBACK, reason)
        self._on_failure(reason)
        current = asyncio.current_task()
        if self._runner is not None and self._runner is not current and not self._runner.done():
            self._runner.cancel()
        await self._shutdown_provider()

    async def _shutdown_provider(self) -> None:
        try:
            await self._provider.close()
        except Exception as error:
            logger.warning("Closing the cloud provider failed: %s", type(error).__name__)
