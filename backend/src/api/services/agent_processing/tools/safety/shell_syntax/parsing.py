"""Parsing shell text into a syntax tree with tree-sitter-bash.

The grammar is the one editors use for bash, so a command is read the way a shell reads it: quoting, escapes, substitutions, redirections, loops and operators all arrive as typed nodes instead of being guessed from word boundaries. The language and parser come from two pinned wheels, `tree-sitter` and `tree-sitter-bash`; if either is missing the import below fails and the backend does not start, which is deliberate because no command check may run on a weaker fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import tree_sitter_bash
from tree_sitter import Language, Node, Parser, Tree

_LANGUAGE = Language(tree_sitter_bash.language())


@dataclass(frozen=True)
class ParsedShell:
    """A parsed command. `source` is the UTF-8 text the node byte offsets point into, and `has_error` is True when the grammar had to recover from, or insert, anything."""

    source: bytes
    tree: Tree
    root: Node
    has_error: bool

    def text(self, node: Node) -> str:
        """The exact source text of a node. Offsets are bytes, so the slice is taken before decoding."""
        return self.source[node.start_byte:node.end_byte].decode('utf-8', 'replace')


def parse_shell(command: str) -> ParsedShell:
    """Parse a command. A parser is created per call because tree-sitter parsers are not safe to share between threads; creating one costs microseconds."""
    source = command.encode('utf-8')
    tree = Parser(_LANGUAGE).parse(source)
    return ParsedShell(source=source, tree=tree, root=tree.root_node, has_error=bool(tree.root_node.has_error))


def iter_nodes(root: Node) -> Iterator[Node]:
    """Every node under `root`, itself included, parents before children. Iterative, so a deeply nested command cannot exhaust the Python stack."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))
