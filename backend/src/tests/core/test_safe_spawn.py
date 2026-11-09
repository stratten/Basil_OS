"""safe_spawn must route eligible spawns through posix_spawn and leave fork-only spawns alone."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from api.core.runtime import safe_spawn

pytestmark = pytest.mark.skipif(not getattr(subprocess, "_USE_POSIX_SPAWN", False), reason="posix_spawn unavailable")


@pytest.fixture
def posix_spawn_calls(monkeypatch):
    calls = []
    original = subprocess.Popen._posix_spawn

    def spy(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "_posix_spawn", spy)
    return calls


def test_eligibility_rules():
    assert safe_spawn.posix_spawn_eligible({}) is True
    assert safe_spawn.posix_spawn_eligible({"capture_output": True, "env": {"A": "1"}}) is True
    for blocked in (
        {"cwd": "/tmp"},
        {"start_new_session": True},
        {"preexec_fn": lambda: None},
        {"pass_fds": (5,)},
        {"user": "root"},
        {"group": "wheel"},
        {"process_group": 0},
        {"umask": 0o22},
        {"shell": True},
    ):
        assert safe_spawn.posix_spawn_eligible(blocked) is False, blocked
    assert safe_spawn.posix_spawn_eligible({"umask": -1}) is True


def test_resolve_executable_returns_an_absolute_path_for_known_programs_and_passes_unknown_through():
    assert safe_spawn.resolve_executable("sh").startswith("/")
    assert safe_spawn.resolve_executable("/bin/sh") == "/bin/sh"
    assert safe_spawn.resolve_executable("definitely-not-a-real-program-xyz") == "definitely-not-a-real-program-xyz"


def test_sync_run_uses_posix_spawn_when_eligible(posix_spawn_calls):
    result = safe_spawn.run(["echo", "hello"], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "hello"
    assert len(posix_spawn_calls) == 1


def test_sync_run_keeps_the_fork_path_when_cwd_is_set(posix_spawn_calls, tmp_path):
    result = safe_spawn.run(["pwd"], capture_output=True, text=True, check=True, cwd=str(tmp_path))

    assert result.stdout.strip().endswith(tmp_path.name)
    assert posix_spawn_calls == []


def test_explicit_close_fds_from_the_caller_is_respected(posix_spawn_calls):
    safe_spawn.run(["echo", "x"], capture_output=True, close_fds=True)

    assert posix_spawn_calls == []


def test_missing_program_still_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        safe_spawn.run(["definitely-not-a-real-program-xyz"], capture_output=True)


@pytest.mark.asyncio
async def test_async_spawn_uses_posix_spawn_and_returns_output(posix_spawn_calls):
    process = await safe_spawn.create_subprocess_exec(
        "echo", "async-hello", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _stderr = await process.communicate()

    assert stdout.decode().strip() == "async-hello"
    assert process.returncode == 0
    assert len(posix_spawn_calls) == 1


@pytest.mark.asyncio
async def test_async_spawn_with_start_new_session_keeps_the_fork_path(posix_spawn_calls):
    process = await safe_spawn.create_subprocess_exec(
        "echo", "x", stdout=asyncio.subprocess.PIPE, start_new_session=True
    )
    await process.communicate()

    assert posix_spawn_calls == []


@pytest.mark.asyncio
async def test_slow_spawn_is_reported(monkeypatch):
    async def slow_exec(program, *args, **kwargs):
        return object()

    ticks = iter([100.0, 103.5])
    monkeypatch.setattr(safe_spawn.asyncio, "create_subprocess_exec", slow_exec)
    monkeypatch.setattr(safe_spawn, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    warnings = []
    monkeypatch.setattr(safe_spawn, "logger", SimpleNamespace(warning=lambda message, *args: warnings.append(message % args), debug=lambda *a: None))

    await safe_spawn.create_subprocess_exec("echo", "x")

    assert any("took 3.5s" in warning for warning in warnings)


def _tesseract_binary():
    import os
    import shutil

    found = shutil.which("tesseract")
    if found:
        return found
    return "/opt/homebrew/bin/tesseract" if os.path.exists("/opt/homebrew/bin/tesseract") else None


def test_pytesseract_wrapper_adds_close_fds_false_and_installing_twice_is_a_no_op():
    import pytesseract.pytesseract as module

    safe_spawn.install_pytesseract_posix_spawn()
    installed = module.subprocess_args
    safe_spawn.install_pytesseract_posix_spawn()

    assert module.subprocess_args is installed
    assert installed._basil_posix_spawn is True
    assert installed.__wrapped__ is not installed
    assert installed()["close_fds"] is False


def test_pytesseract_wrapper_keeps_an_explicit_close_fds_and_leaves_fork_only_options_alone(monkeypatch):
    import pytesseract.pytesseract as module

    monkeypatch.setattr(module, "subprocess_args", lambda *a, **k: {"close_fds": True, "stdin": subprocess.PIPE})
    safe_spawn.install_pytesseract_posix_spawn()
    assert module.subprocess_args()["close_fds"] is True

    monkeypatch.setattr(module, "subprocess_args", lambda *a, **k: {"cwd": "/tmp"})
    safe_spawn.install_pytesseract_posix_spawn()
    assert "close_fds" not in module.subprocess_args()


def test_pytesseract_image_to_string_takes_the_posix_spawn_path_and_never_forks(posix_spawn_calls, monkeypatch):
    import pytesseract
    from PIL import Image

    tesseract = _tesseract_binary()
    if tesseract is None:
        pytest.skip("tesseract is not installed")
    safe_spawn.install_pytesseract_posix_spawn()
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", tesseract)
    fork_calls = []
    original_fork_exec = subprocess._fork_exec
    monkeypatch.setattr(subprocess, "_fork_exec", lambda *a, **k: fork_calls.append(a) or original_fork_exec(*a, **k))

    text = pytesseract.image_to_string(Image.new("RGB", (200, 60), "white"))

    assert isinstance(text, str)
    assert len(posix_spawn_calls) == 1
    assert fork_calls == []


@pytest.mark.parametrize(
    "module_name",
    ["api.services.ocr.ocr_service", "api.services.image_processing.image_processing_service"],
)
def test_both_ocr_services_install_the_posix_spawn_route_on_import(module_name):
    import os
    import sys

    code = (
        f"import {module_name}\n"
        "import pytesseract.pytesseract as m\n"
        "print('INSTALLED' if getattr(m.subprocess_args, '_basil_posix_spawn', False) else 'MISSING')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)},
    )

    assert "INSTALLED" in result.stdout, result.stdout + result.stderr
