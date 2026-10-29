"""No coroutine may open a synchronous SQLite connection or transaction directly on the event loop.

A synchronous statement that waits for the write coordinator on the loop thread deadlocks against any aiosqlite writer holding the token across an await, and even a plain read stalls every other coroutine for its duration. Synchronous database work belongs in a plain function that a coroutine reaches through `run_in_worker_thread`, `asyncio.to_thread`, or a nested synchronous closure handed to `asyncio.to_thread`.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3] / "api"

SYNC_DATABASE_ENTRY_POINTS = {"get_sync_connection", "run_write_transaction", "run_read_transaction"}


def _own_nodes(function: ast.AsyncFunctionDef):
    """Yield the nodes of a coroutine body without descending into nested functions, lambdas, or classes."""
    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _called_name(call: ast.Call) -> str | None:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_direct_sqlite_connect(call: ast.Call) -> bool:
    target = call.func
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "connect"
        and isinstance(target.value, ast.Name)
        and target.value.id == "sqlite3"
    )


def _offending_coroutines() -> list[str]:
    offenders: list[str] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for inner in _own_nodes(node):
                if isinstance(inner, ast.Call) and (
                    _called_name(inner) in SYNC_DATABASE_ENTRY_POINTS or _is_direct_sqlite_connect(inner)
                ):
                    offenders.append(f"{path.relative_to(API_ROOT)}:{inner.lineno} {node.name}")
    return offenders


def test_no_coroutine_opens_a_synchronous_sqlite_connection_on_the_event_loop() -> None:
    assert _offending_coroutines() == []


def test_the_guard_flags_a_coroutine_that_calls_the_synchronous_connection_directly() -> None:
    source = (
        "async def bad(db_path):\n"
        "    with get_sync_connection(db_path) as conn:\n"
        "        return conn.execute('SELECT 1').fetchone()\n"
        "\n"
        "async def fine(db_path):\n"
        "    def read():\n"
        "        with get_sync_connection(db_path) as conn:\n"
        "            return conn.execute('SELECT 1').fetchone()\n"
        "    return await asyncio.to_thread(read)\n"
    )
    tree = ast.parse(source)
    flagged = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            isinstance(inner, ast.Call) and _called_name(inner) in SYNC_DATABASE_ENTRY_POINTS
            for inner in _own_nodes(node)
        )
    ]
    assert flagged == ["bad"]
