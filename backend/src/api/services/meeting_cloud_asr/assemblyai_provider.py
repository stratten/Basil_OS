"""AssemblyAI Universal-Streaming provider: pcm_s16le over a WebSocket with a raw-key Authorization header."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

from .models import EVENT_FINAL, EVENT_INTERIM, PCM_SAMPLE_RATE, PROVIDER_ASSEMBLYAI, AsrEvent
from .websocket_provider import WebSocketAsrProvider

ASSEMBLYAI_URL = "wss://streaming.assemblyai.com/v3/ws"


def _word_seconds(words: List[Any], index: int, field: str) -> float:
    if not words:
        return 0.0
    try:
        return float((words[index] or {}).get(field) or 0.0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


class AssemblyAIProvider(WebSocketAsrProvider):
    name = PROVIDER_ASSEMBLYAI
    label = "AssemblyAI"

    def __init__(self, api_key: str, *, base_url: str = ASSEMBLYAI_URL, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key
        self._base_url = base_url
        self._finalized_turns: Set[Any] = set()

    def _url(self) -> str:
        query = urlencode({"sample_rate": str(PCM_SAMPLE_RATE), "encoding": "pcm_s16le"})
        return f"{self._base_url}?{query}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": self._api_key}

    def _close_payload(self) -> Optional[str]:
        return '{"type": "Terminate"}'

    def _error_text(self, message: Dict[str, Any]) -> Optional[str]:
        error = message.get("error")
        return str(error) if error else None

    def _parse(self, message: Dict[str, Any]) -> List[AsrEvent]:
        if message.get("type") != "Turn":
            return []
        text = str(message.get("transcript") or "").strip()
        words = message.get("words") or []
        start = _word_seconds(words, 0, "start")
        end = _word_seconds(words, -1, "end")
        if message.get("end_of_turn"):
            turn = message.get("turn_order")
            if turn in self._finalized_turns:
                return []
            self._finalized_turns.add(turn)
            return [AsrEvent(EVENT_FINAL, text, start, end, True)]
        if not text:
            return []
        return [AsrEvent(EVENT_INTERIM, text, start, end)]
