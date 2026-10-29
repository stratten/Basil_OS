"""Incremental extraction of completed ``items`` elements from streamed JSON text."""

from __future__ import annotations

from typing import List, Optional


class IncrementalItemsParser:
    """Feed streamed JSON text and receive each complete element of the root ``items`` array.

    Only object elements of the top-level ``items`` array are emitted, as raw JSON text.
    The parser never validates; callers validate each element against the strict item
    schema. Truncated or malformed streams simply stop emitting.
    """

    def __init__(self) -> None:
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._key: List[str] = []
        self._last_key: Optional[str] = None
        self._items_open = False
        self._items_done = False
        self._capturing = False
        self._buffer: List[str] = []

    def feed(self, text: str) -> List[str]:
        completed: List[str] = []
        for char in text:
            if self._in_string:
                self._consume_string_char(char)
                continue
            if char == '"':
                self._in_string = True
                self._key = []
                if self._capturing:
                    self._buffer.append(char)
                continue
            if self._capturing:
                self._buffer.append(char)
            if char in "{[":
                self._open(char)
            elif char in "}]":
                element = self._close(char)
                if element is not None:
                    completed.append(element)
        return completed

    def _consume_string_char(self, char: str) -> None:
        if self._capturing:
            self._buffer.append(char)
        elif self._depth == 1:
            self._key.append(char)
        if self._escape:
            self._escape = False
        elif char == "\\":
            self._escape = True
        elif char == '"':
            self._in_string = False
            if not self._capturing and self._depth == 1:
                self._last_key = "".join(self._key[:-1])

    def _open(self, char: str) -> None:
        self._depth += 1
        if self._items_done:
            return
        if (
            char == "["
            and self._depth == 2
            and self._last_key == "items"
            and not self._items_open
        ):
            self._items_open = True
        elif (
            char == "{"
            and self._items_open
            and self._depth == 3
            and not self._capturing
        ):
            self._capturing = True
            self._buffer = ["{"]

    def _close(self, char: str) -> Optional[str]:
        element: Optional[str] = None
        if self._capturing and char == "}" and self._depth == 3:
            element = "".join(self._buffer)
            self._capturing = False
            self._buffer = []
        elif char == "]" and self._items_open and self._depth == 2:
            self._items_open = False
            self._items_done = True
        self._depth = max(0, self._depth - 1)
        return element
