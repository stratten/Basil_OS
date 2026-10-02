"""In-band paste directive for AssistantSession replies.

In the "auto" paste mode the model ends its reply with ``<basil_paste>insert</basil_paste>`` or ``<basil_paste>show</basil_paste>``. ``PasteDirectiveFilter`` removes that tag from the token stream before anything is streamed, stored on the session, or persisted to history, and records the model's choice.
"""

from typing import Optional

from api.core.preferences.preferences_io import load_preferences

PASTE_DIRECTIVE_OPEN = "<basil_paste>"
PASTE_DIRECTIVE_CLOSE = "</basil_paste>"
_VALID_DECISIONS = ("insert", "show")
# Longest value tolerated between the tags; past this the opening tag is treated as literal reply text.
_MAX_DIRECTIVE_VALUE_CHARS = 16
_DIRECTIVE_SEARCH_WINDOW = _MAX_DIRECTIVE_VALUE_CHARS + len(PASTE_DIRECTIVE_CLOSE)

PASTE_DECISION_INSTRUCTION = (
    "PASTE DECISION: After your complete response, add one final line containing exactly "
    "<basil_paste>insert</basil_paste> or <basil_paste>show</basil_paste>, with nothing after it. "
    "Choose insert when your response is text the user will put into what they are writing or editing right now: "
    "a reply, a draft, a rewrite, a message, a field value, or code to insert. "
    "Choose show when your response is for the user to read: an explanation, an answer, a summary, research, analysis, or advice. "
    "If you are unsure, choose show. Do not mention this line or the paste decision anywhere else in your response."
)


def resolve_paste_mode() -> str:
    """Return the saved AssistantSession paste mode, falling back to "always" when preferences cannot be read."""
    try:
        return load_preferences().models.assistant_output_paste_mode
    except Exception:
        return "always"


def with_paste_instruction(prompt: str) -> str:
    return f"{prompt}\n\n{PASTE_DECISION_INSTRUCTION}"


def _partial_prefix_length(text: str, tag: str) -> int:
    """Length of the longest suffix of ``text`` that is a proper prefix of ``tag``."""
    for length in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:length]):
            return length
    return 0


class PasteDirectiveFilter:
    """Streaming filter that strips ``<basil_paste>`` directives and keeps the last valid decision."""

    def __init__(self) -> None:
        self._pending = ""
        self.decision: Optional[str] = None
        self.removed_directive = False

    def feed(self, token: str) -> str:
        """Add a streamed token and return the text that is safe to show now."""
        self._pending += token
        return self._drain(final=False)

    def finish(self) -> str:
        """Flush held-back text at the end of the stream."""
        return self._drain(final=True)

    def _drain(self, final: bool) -> str:
        visible = []
        while True:
            start = self._pending.find(PASTE_DIRECTIVE_OPEN)
            if start == -1:
                keep = 0 if final else _partial_prefix_length(self._pending, PASTE_DIRECTIVE_OPEN)
                cut = len(self._pending) - keep
                visible.append(self._pending[:cut])
                self._pending = self._pending[cut:]
                break
            visible.append(self._pending[:start])
            remainder = self._pending[start + len(PASTE_DIRECTIVE_OPEN):]
            end = remainder.find(PASTE_DIRECTIVE_CLOSE, 0, _DIRECTIVE_SEARCH_WINDOW)
            if end == -1:
                if len(remainder) >= _DIRECTIVE_SEARCH_WINDOW:
                    visible.append(PASTE_DIRECTIVE_OPEN)
                    self._pending = remainder
                    continue
                if final:
                    self.removed_directive = True
                    self._pending = ""
                    break
                self._pending = self._pending[start:]
                break
            value = remainder[:end].strip().lower()
            if value in _VALID_DECISIONS:
                self.decision = value
            self.removed_directive = True
            self._pending = remainder[end + len(PASTE_DIRECTIVE_CLOSE):]
        return "".join(visible)
