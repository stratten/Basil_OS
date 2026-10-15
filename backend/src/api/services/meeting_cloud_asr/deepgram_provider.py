"""Deepgram live streaming provider: linear16 over a WebSocket with Token authorization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .models import EVENT_FINAL, EVENT_INTERIM, PCM_SAMPLE_RATE, PROVIDER_DEEPGRAM, AsrEvent
from .websocket_provider import WebSocketAsrProvider

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_MODEL = "nova-3"
DEEPGRAM_LANGUAGE = "en"


class DeepgramProvider(WebSocketAsrProvider):
    name = PROVIDER_DEEPGRAM
    label = "Deepgram"

    def __init__(self, api_key: str, *, base_url: str = DEEPGRAM_URL, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key
        self._base_url = base_url

    def _url(self) -> str:
        query = urlencode(
            {
                "model": DEEPGRAM_MODEL,
                "language": DEEPGRAM_LANGUAGE,
                "encoding": "linear16",
                "sample_rate": str(PCM_SAMPLE_RATE),
                "channels": "1",
                "interim_results": "true",
                "smart_format": "true",
                "punctuate": "true",
                "endpointing": "300",
            }
        )
        return f"{self._base_url}?{query}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Token {self._api_key}"}

    def _keepalive_payload(self) -> Optional[str]:
        return '{"type": "KeepAlive"}'

    def _close_payload(self) -> Optional[str]:
        return '{"type": "CloseStream"}'

    def _error_text(self, message: Dict[str, Any]) -> Optional[str]:
        if message.get("type") != "Error":
            return None
        return str(message.get("description") or message.get("message") or "unknown error")

    def _parse(self, message: Dict[str, Any]) -> List[AsrEvent]:
        if message.get("type") != "Results":
            return []
        channel = message.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        text = str((alternatives[0] or {}).get("transcript") or "").strip() if alternatives else ""
        is_final = bool(message.get("is_final"))
        utterance_end = is_final and bool(message.get("speech_final"))
        if not text and not utterance_end:
            return []
        start = float(message.get("start") or 0.0)
        end = start + float(message.get("duration") or 0.0)
        return [AsrEvent(EVENT_FINAL if is_final else EVENT_INTERIM, text, start, end, utterance_end)]
