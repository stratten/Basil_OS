"""Asks a running background program whether it is healthy or waiting on the person.

Some programs are running but not usable yet: a messaging bridge that has not been linked to a phone is the common case. The program reports that itself through a local status page. Basil reads that page, maps what it says to one of four phases, and keeps the one action the person may need to take (a code to scan) in memory only.

The page's address, the field that holds the state and the meaning of each value all come from the connection's probe settings, so nothing here knows about any particular program.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

import httpx

from api.core.models.preferences import MCPProbeSpec

from .local_server_placeholders import substitute_placeholders

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0
MAX_MESSAGE_CHARS = 300
MAX_ACTION_CHARS = 4096
MAX_EXPIRES_CHARS = 64
MAX_BODY_BYTES = 262_144

PHASE_STARTING = "starting"
PHASE_READY = "ready"
PHASE_NEEDS_ACTION = "needs_action"
PHASE_FAILED = "failed"


@dataclass(frozen=True)
class ProbeReading:
    """What the program said the last time Basil asked. The action value is a credential-like pairing code, so it is shown to the person and never logged or stored."""

    phase: str
    message: Optional[str] = None
    state_value: Optional[str] = None
    action_kind: Optional[str] = None
    action_value: Optional[str] = None
    action_expires_at: Optional[str] = None


class ProbeUnavailable(Exception):
    """The status page could not be read. The message says why in plain words."""


GetJson = Callable[[str, Mapping[str, str], float], Awaitable[Any]]


async def _default_get_json(url: str, headers: Mapping[str, str], timeout: float) -> Any:
    """GET ``url`` without following redirects, so a credential is never forwarded to another address. A JSON body is accepted on any status, because some programs report "not connected" with an error status."""
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.get(url, headers=dict(headers))
    except httpx.HTTPError as exc:
        raise ProbeUnavailable(f"Basil could not reach the program's status page ({type(exc).__name__}).") from exc
    if response.status_code in (401, 403):
        raise ProbeUnavailable("The program refused the credential Basil sent to its status page.")
    if 300 <= response.status_code < 400:
        raise ProbeUnavailable("The program's status page redirected, which Basil does not follow.")
    if len(response.content) > MAX_BODY_BYTES:
        raise ProbeUnavailable("The program's status page answered with too much data.")
    try:
        return response.json()
    except ValueError as exc:
        raise ProbeUnavailable("The program's status page did not answer with JSON.") from exc


def value_at(data: Any, path: str) -> Any:
    """The value at a dotted path such as ``state`` or ``a.b.0``, or None when any step is missing."""
    current = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _as_text(value: Any, limit: int) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    text = text.strip()
    return text[:limit] if text else None


def interpret(spec: MCPProbeSpec, data: Any) -> ProbeReading:
    """Turn the program's JSON answer into a reading. A state value the settings do not mention counts as starting."""
    state_value = _as_text(value_at(data, spec.state_path), 64)
    phase = spec.states.get(state_value, PHASE_STARTING) if state_value is not None else PHASE_STARTING
    message = _as_text(value_at(data, spec.message_path), MAX_MESSAGE_CHARS) if spec.message_path else None
    action_kind = action_value = expires = None
    if phase == PHASE_NEEDS_ACTION and spec.action_path:
        action_value = _as_text(value_at(data, spec.action_path), MAX_ACTION_CHARS)
        if action_value is not None:
            action_kind = spec.action_kind
            expires = _as_text(value_at(data, spec.expires_path), MAX_EXPIRES_CHARS) if spec.expires_path else None
    return ProbeReading(phase=phase, message=message, state_value=state_value, action_kind=action_kind, action_value=action_value, action_expires_at=expires)


def _bearer(spec: MCPProbeSpec, run_secret: Optional[str], secrets: Mapping[str, str]) -> Optional[str]:
    if spec.auth == "bearer_run_secret":
        return run_secret
    if spec.auth == "bearer_secret" and spec.secret_name:
        return secrets.get(spec.secret_name)
    return None


async def read_probe(
    spec: MCPProbeSpec,
    *,
    port: int,
    run_secret: Optional[str],
    secrets: Mapping[str, str],
    get_json: Optional[GetJson] = None,
) -> ProbeReading:
    """Ask the program once. Raises ProbeUnavailable when the page cannot be read."""
    headers = {"Accept": "application/json"}
    if spec.auth != "none":
        token = _bearer(spec, run_secret, secrets)
        if not token:
            raise ProbeUnavailable("Basil does not have the credential for the program's status page.")
        headers["Authorization"] = f"Bearer {token}"
    url = substitute_placeholders(spec.url, port=port)
    data = await (get_json or _default_get_json)(url, headers, PROBE_TIMEOUT_SECONDS)
    return interpret(spec, data)


UNREACHABLE_GRACE_READS = 3
"""How many reads in a row may fail before the program is reported as failed instead of still starting, so a brief hiccup does not flash an error."""


class ProbeMonitor:
    """Reads the status page again and again while a background program runs, and keeps the latest reading."""

    def __init__(
        self,
        spec: MCPProbeSpec,
        *,
        port: int,
        run_secret: Optional[str],
        secrets: Mapping[str, str],
        read: Callable[..., Awaitable[ProbeReading]] = read_probe,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        get_json: Optional[GetJson] = None,
    ) -> None:
        self._spec = spec
        self._port = port
        self._run_secret = run_secret
        self._secrets = dict(secrets)
        self._read = read
        self._sleep = sleep
        self._get_json = get_json
        self._task: Optional["asyncio.Task[None]"] = None
        self._failures = 0
        self.reading: ProbeReading = ProbeReading(phase=PHASE_STARTING, message="Waiting for the program to answer.")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def read_once(self) -> ProbeReading:
        """Ask now and store the answer. A page that cannot be read is reported as starting for a few reads, then as failed."""
        try:
            self.reading = await self._read(self._spec, port=self._port, run_secret=self._run_secret, secrets=self._secrets, get_json=self._get_json)
            self._failures = 0
        except ProbeUnavailable as exc:
            self._failures += 1
            phase = PHASE_FAILED if self._failures > UNREACHABLE_GRACE_READS else PHASE_STARTING
            self.reading = ProbeReading(phase=phase, message=str(exc))
        return self.reading

    async def _loop(self) -> None:
        while True:
            try:
                await self.read_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Reading a background program's status page failed")
                self.reading = ProbeReading(phase=PHASE_FAILED, message="Basil could not read the program's status page.")
            await self._sleep(self._spec.interval_seconds)
