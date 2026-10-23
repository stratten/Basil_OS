"""Shared WebSocket plumbing for vendor streaming providers: connect, read loop, keep-alive, and orderly close."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from .models import AsrEvent, CloudAsrError

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 10.0
KEEPALIVE_SECONDS = 8.0
CLOSE_DRAIN_SECONDS = 4.0

ConnectFactory = Callable[..., Awaitable[Any]]
_END = object()


async def default_connect(url: str, *, additional_headers: Dict[str, str]) -> Any:
    """Open a client WebSocket with the websockets library; imported lazily so tests can inject a factory."""
    from websockets.asyncio.client import connect

    return await connect(url, additional_headers=additional_headers, open_timeout=None, max_size=None)


def describe_connect_error(label: str, error: BaseException) -> str:
    """A user-safe sentence for a failed connection; never includes headers or keys."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status in (401, 403):
        return f"{label} rejected the API key."
    if status == 429:
        return f"{label} is rate limiting new sessions."
    if status is not None:
        return f"{label} refused the connection (HTTP {status})."
    return f"Could not connect to {label}."


class WebSocketAsrProvider:
    """Base class: subclasses supply the URL, headers, message parsing, and the vendor's control messages."""

    name = ""
    label = ""

    def __init__(
        self,
        *,
        connect: Optional[ConnectFactory] = None,
        keepalive_seconds: float = KEEPALIVE_SECONDS,
        connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS,
        close_drain_seconds: float = CLOSE_DRAIN_SECONDS,
    ) -> None:
        self._connect = connect or default_connect
        self._keepalive_seconds = keepalive_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._close_drain_seconds = close_drain_seconds
        self._socket: Any = None
        self._events: asyncio.Queue = asyncio.Queue()
        self._reader: Optional[asyncio.Task] = None
        self._keepalive: Optional[asyncio.Task] = None
        self._failure: Optional[CloudAsrError] = None
        self._closing = False

    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _parse(self, message: Dict[str, Any]) -> List[AsrEvent]:
        raise NotImplementedError

    def _error_text(self, message: Dict[str, Any]) -> Optional[str]:
        return None

    def _keepalive_payload(self) -> Optional[str]:
        return None

    def _close_payload(self) -> Optional[str]:
        return None

    async def open(self) -> None:
        try:
            self._socket = await asyncio.wait_for(
                self._connect(self._url(), additional_headers=self._headers()),
                timeout=self._connect_timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise CloudAsrError(f"Timed out connecting to {self.label}.") from error
        except CloudAsrError:
            raise
        except Exception as error:
            logger.warning("%s connection failed: %s", self.label, type(error).__name__)
            raise CloudAsrError(describe_connect_error(self.label, error)) from error
        self._reader = asyncio.create_task(self._read_loop())
        if self._keepalive_payload() is not None:
            self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def send_audio(self, pcm: bytes) -> None:
        if self._socket is None or self._failure is not None:
            raise self._failure or CloudAsrError(f"{self.label} is not connected.")
        try:
            await self._socket.send(pcm)
        except Exception as error:
            raise CloudAsrError(f"The {self.label} connection was lost.") from error

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            item = await self._events.get()
            if item is _END:
                break
            yield item
        if self._failure is not None:
            raise self._failure

    async def close(self) -> None:
        self._closing = True
        if self._keepalive is not None:
            self._keepalive.cancel()
        payload = self._close_payload()
        if self._socket is not None and payload is not None:
            try:
                await self._socket.send(payload)
            except Exception:
                pass
        if self._reader is not None and not self._reader.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._reader), timeout=self._close_drain_seconds)
            except asyncio.TimeoutError:
                self._reader.cancel()
        tasks = [task for task in (self._reader, self._keepalive) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._socket is not None:
            try:
                await self._socket.close()
            except Exception:
                pass
        self._events.put_nowait(_END)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._socket:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                error_text = self._error_text(message)
                if error_text:
                    self._failure = CloudAsrError(f"{self.label} reported an error: {error_text}")
                    break
                for event in self._parse(message):
                    self._events.put_nowait(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closing:
                self._failure = CloudAsrError(f"The {self.label} connection was lost.")
                logger.warning("%s read loop ended: %s", self.label, type(error).__name__)
        finally:
            if not self._closing and self._failure is None:
                self._failure = CloudAsrError(f"{self.label} closed the connection.")
            self._events.put_nowait(_END)

    async def _keepalive_loop(self) -> None:
        payload = self._keepalive_payload()
        try:
            while True:
                await asyncio.sleep(self._keepalive_seconds)
                await self._socket.send(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
