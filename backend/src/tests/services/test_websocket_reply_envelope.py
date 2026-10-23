"""Guard: every live /ws reply dict that reports status and message also names its event_type."""

import ast
from pathlib import Path

import pytest

_BACKEND_SRC = Path(__file__).resolve().parents[2]
_ROUTE_FILES = (
    _BACKEND_SRC / "api" / "routes" / "websocket.py",
    _BACKEND_SRC / "api" / "routes" / "websocket_routes" / "conversation.py",
    _BACKEND_SRC / "api" / "routes" / "websocket_routes" / "transcription.py",
)


class _EnvelopeVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.function_stack: list[str] = []
        self.findings: list[str] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        if {"status", "message"} <= keys and "event_type" not in keys:
            owner = self.function_stack[-1] if self.function_stack else "<module>"
            self.findings.append(f"{self.path}:{node.lineno} in {owner}")
        self.generic_visit(node)


def _reply_dicts_missing_event_type(path: Path) -> list[str]:
    visitor = _EnvelopeVisitor(path)
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return visitor.findings


@pytest.mark.parametrize("route_file", _ROUTE_FILES, ids=lambda path: path.name)
def test_ws_reply_dicts_declare_event_type(route_file: Path) -> None:
    assert route_file.is_file(), f"route file moved: {route_file}"
    assert _reply_dicts_missing_event_type(route_file) == []


def test_guard_flags_status_reply_without_event_type(tmp_path: Path) -> None:
    sample = tmp_path / "sample_route.py"
    sample.write_text(
        "async def handler(websocket):\n"
        "    await websocket.send_json({\"status\": \"error\", \"message\": \"bad\"})\n"
        "    await websocket.send_json({\"event_type\": \"ok\", \"status\": \"success\", \"message\": \"fine\"})\n",
        encoding="utf-8",
    )
    assert _reply_dicts_missing_event_type(sample) == [f"{sample}:2 in handler"]
