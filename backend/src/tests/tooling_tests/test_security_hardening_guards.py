"""Repository guards that keep the local security hardening wired into every desktop and web surface."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_COMPONENTS_ROOT = REPO_ROOT / "web-components"
CLIENT_SOURCES_ROOT = REPO_ROOT / "client" / "Sources"
MAIN_MODULE = REPO_ROOT / "backend" / "src" / "api" / "main.py"
WEB_VIEW_CONFIGURATION_FACTORY = CLIENT_SOURCES_ROOT / "Services" / "Security" / "BasilWebViewConfigurationFactory.swift"
AGENT_CONTENT_BRIDGE_FILES = (
    CLIENT_SOURCES_ROOT / "App" / "AgentTaskCapture" / "AgentTaskResultWebView" / "AgentTaskResultWebView+IncomingBridge.swift",
    CLIENT_SOURCES_ROOT / "App" / "BasilBoard" / "BasilBoardWebView+FilePreview.swift",
    CLIENT_SOURCES_ROOT / "App" / "AgentTaskCapture" / "AgentTaskFilePreviewWindow.swift",
    CLIENT_SOURCES_ROOT / "App" / "AgentTaskCapture" / "LocalWebPreview" / "AgentTaskLocalWebPreviewWindow.swift",
)
EXPECTED_VITE_PACKAGE_COUNT = 16
EXPECTED_WEB_SOCKET_TASK_CALLS = 5
WEB_SOCKET_TASK_CALL = re.compile(r"webSocketTask\(with:\s*([^\n]*)")


def _vite_configs() -> list[Path]:
    return sorted(WEB_COMPONENTS_ROOT.glob("*/vite.config.mts"))


def _swift_sources() -> list[Path]:
    return sorted(CLIENT_SOURCES_ROOT.rglob("*.swift"))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_every_vite_package_is_discovered() -> None:
    assert len(_vite_configs()) == EXPECTED_VITE_PACKAGE_COUNT


@pytest.mark.parametrize("config_path", _vite_configs(), ids=lambda path: path.parent.name)
def test_vite_config_registers_content_security_policy(config_path: Path) -> None:
    source = config_path.read_text(encoding="utf-8")

    assert "from '../shared/vite/basilContentSecurityPolicy'" in source
    assert re.search(r"plugins:\s*\[[^\]]*basilContentSecurityPolicy\(\)", source)


def test_only_the_factory_constructs_web_view_configurations() -> None:
    offenders = [
        _relative(path)
        for path in _swift_sources()
        if path != WEB_VIEW_CONFIGURATION_FACTORY and "WKWebViewConfiguration()" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
    assert "WKWebViewConfiguration()" in WEB_VIEW_CONFIGURATION_FACTORY.read_text(encoding="utf-8")


def test_every_web_socket_task_uses_an_authorized_request() -> None:
    calls = [
        (_relative(path), match.group(1).strip())
        for path in _swift_sources()
        for match in WEB_SOCKET_TASK_CALL.finditer(path.read_text(encoding="utf-8"))
    ]
    unauthorized = [
        (path, argument)
        for path, argument in calls
        if not argument.startswith("BackendAuthorization.authorizedRequest(")
    ]

    assert len(calls) == EXPECTED_WEB_SOCKET_TASK_CALLS
    assert unauthorized == []


@pytest.mark.parametrize("bridge_path", AGENT_CONTENT_BRIDGE_FILES, ids=lambda path: path.name)
def test_agent_content_bridges_open_through_the_policy(bridge_path: Path) -> None:
    source = bridge_path.read_text(encoding="utf-8")

    assert "NSWorkspace.shared.open(" not in source
    assert "BridgeOpenPolicy." in source


def test_main_module_installs_guard_inside_explicit_cors() -> None:
    source = MAIN_MODULE.read_text(encoding="utf-8")
    guard_index = source.index("app.add_middleware(BackendRequestGuardMiddleware)")
    cors_index = source.index('    CORSMiddleware,\n    allow_origins=["null"],')

    assert guard_index < cors_index
    assert 'allow_origins=["*"]' not in source
    assert '"0.0.0.0"' not in source
    assert "resolve_loopback_bind_host(" in source
