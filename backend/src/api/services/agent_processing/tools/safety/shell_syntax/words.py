"""The text a shell would hand to a program, read from syntax-tree nodes.

A node is "literal" when every piece of it is fixed text: a bare word, a single-quoted string, a double-quoted string with no expansion inside, or a concatenation of those. Its value is exactly what the program receives, with the quoting and backslashes removed, so `-"delete"`, `\\-delete`, and `-delete` all read as `-delete`. Anything the shell computes (a variable, a substitution, arithmetic) is not literal and reads as None.
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from tree_sitter import Node

from .parsing import ParsedShell

# What stands in for an expansion when a quoted shell script is rebuilt for checking.
SCRIPT_VALUE_PLACEHOLDER = 'value'

_UNQUOTED_ESCAPE = re.compile(r'\\(.)', re.DOTALL)
_DOUBLE_QUOTED_ESCAPE = re.compile(r'\\([$`"\\\n])')
_VARIABLE_REFERENCE = re.compile(r'^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$')


def _unescape_unquoted(text: str) -> str:
    """A backslash outside quotes makes the next character literal, and a backslash before a line break joins the lines."""
    return _UNQUOTED_ESCAPE.sub(lambda match: '' if match.group(1) == '\n' else match.group(1), text)


def _unescape_double_quoted(text: str) -> str:
    """Inside double quotes a backslash only escapes `$`, a backtick, `"`, another backslash, and a line break."""
    return _DOUBLE_QUOTED_ESCAPE.sub(lambda match: '' if match.group(1) == '\n' else match.group(1), text)


def literal_text(parsed: ParsedShell, node: Node) -> Optional[str]:
    """The value of a literal node, or None when the shell computes any part of it."""
    kind = node.type
    if kind in ('word', 'number'):
        if node.named_children:
            return None
        return _unescape_unquoted(parsed.text(node))
    if kind == 'raw_string':
        text = parsed.text(node)
        if len(text) < 2 or not text.startswith("'") or not text.endswith("'"):
            return None
        return text[1:-1]
    if kind == 'string':
        if any(child.type != 'string_content' for child in node.named_children):
            return None
        text = parsed.text(node)
        if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
            return None
        return _unescape_double_quoted(text[1:-1])
    if kind == 'concatenation':
        children = node.named_children
        # Every byte of the concatenation has to belong to a child, or a piece would be dropped from the value.
        if sum(child.end_byte - child.start_byte for child in children) != node.end_byte - node.start_byte:
            return None
        pieces: List[str] = []
        for child in children:
            piece = literal_text(parsed, child)
            if piece is None:
                return None
            pieces.append(piece)
        return ''.join(pieces)
    return None


def has_unsafe_unquoted_text(parsed: ParsedShell, node: Node, literal: str) -> bool:
    """Whether bare (unquoted) text in an argument could still expand into something else: a brace list such as `{-delete,x}`, or a glob in a word that starts with `-` and could match a file named like an option."""
    if node.type == 'word':
        bare_words = [node]
    elif node.type == 'concatenation':
        bare_words = [child for child in node.named_children if child.type == 'word']
    else:
        bare_words = []
    raw = ''.join(parsed.text(word) for word in bare_words)
    if '{' in raw:
        return True
    return literal.startswith('-') and any(character in raw for character in '*?[')


def variable_name_of(text: str) -> Optional[str]:
    """The name in `$NAME` or `${NAME}`, or None for any other expansion form (`${x:-y}`, `${x@P}`, `${x[0]}`, `$((1))`)."""
    match = _VARIABLE_REFERENCE.match(text)
    if match is None:
        return None
    return match.group(1) or match.group(2)


def script_text(parsed: ParsedShell, node: Node, replaceable: Callable[[Node], bool]) -> Optional[str]:
    """The shell script a wrapper such as `bash -c` is given.

    A literal argument is its own value. A double-quoted string that holds expansions is rebuilt with each expansion replaced by a plain word, but only when `replaceable` accepts every one of them; any other argument shape, and any expansion `replaceable` refuses, reads as None.
    """
    literal = literal_text(parsed, node)
    if literal is not None:
        return literal
    if node.type != 'string':
        return None
    text_start = node.start_byte + 1
    inner = parsed.source[text_start:node.end_byte - 1]
    pieces: List[bytes] = []
    position = 0
    for child in node.named_children:
        if child.type == 'string_content':
            continue
        if not replaceable(child):
            return None
        pieces.append(inner[position:child.start_byte - text_start])
        pieces.append(SCRIPT_VALUE_PLACEHOLDER.encode('utf-8'))
        position = child.end_byte - text_start
    pieces.append(inner[position:])
    return _unescape_double_quoted(b''.join(pieces).decode('utf-8', 'replace'))
