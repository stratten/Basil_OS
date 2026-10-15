"""Neutral value types shared by every cloud streaming speech recognition provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

PCM_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2

PROVIDER_DEEPGRAM = "deepgram"
PROVIDER_ASSEMBLYAI = "assemblyai"
PROVIDER_IDS = (PROVIDER_DEEPGRAM, PROVIDER_ASSEMBLYAI)
PROVIDER_LABELS = {PROVIDER_DEEPGRAM: "Deepgram", PROVIDER_ASSEMBLYAI: "AssemblyAI"}

CONNECTION_OWN_KEY = "own_key"
CONNECTION_BASIL_ACCOUNT = "basil_account"
CONNECTION_MODES = (CONNECTION_OWN_KEY, CONNECTION_BASIL_ACCOUNT)

TIER_STREAMING = "streaming"
TIER_CHUNKED = "chunked"

STATE_OFF = "off"
STATE_CONNECTING = "connecting"
STATE_STREAMING = "streaming"
STATE_FALLBACK = "fallback"

EVENT_INTERIM = "interim"
EVENT_FINAL = "final"

CLOUD_STATUS_EVENT_TYPE = "cloud_transcription_status"


class CloudAsrError(Exception):
    """A cloud recognition failure whose message is safe to show to the user."""


@dataclass(frozen=True)
class AsrEvent:
    """One recognition result in stream seconds measured from the first audio byte sent to the provider."""

    kind: str
    text: str
    start_seconds: float
    end_seconds: float
    utterance_end: bool = False


class StreamingAsrProvider(Protocol):
    """The contract the cloud session drives; implementations never touch the recorder or the socket."""

    name: str

    async def open(self) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    def events(self) -> AsyncIterator[AsrEvent]: ...

    async def close(self) -> None: ...
