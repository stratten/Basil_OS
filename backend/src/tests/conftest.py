import os
import shutil
import asyncio
import pytest
import httpx
import sys
from pathlib import Path
from typing import Optional

# Ensure deterministic tokenizer behavior during tests without requiring CLI env
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# ---------- Test utilities for background task management ----------
def run_in_portal(client, coro):
    """Schedule an async coroutine on FastAPI TestClient's event loop and return the task handle.

    Usage:
        task = run_in_portal(client, some_async_fn())
    """
    try:
        return client.portal.call(asyncio.create_task, coro)
    except Exception:
        return None


def cleanup_task(client, task, timeout: float = 10.0) -> None:
    """Await or cancel a portal task to avoid loop-close errors during teardown."""
    if task is None:
        return
    try:
        client.portal.call(asyncio.wait_for, task, timeout)
    except Exception:
        try:
            client.portal.call(task.cancel)
        except Exception:
            pass


def cleanup_thread(thread, timeout: float = 2.0) -> None:
    """Join a background thread with a short timeout (best-effort)."""
    if thread is None:
        return
    try:
        thread.join(timeout=timeout)
    except Exception:
        pass


def _ws_from_http(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


def _patch_loaded_preference_paths(temp_home):
    """Point already-imported preference modules at a temp preferences file."""
    temp_basil_config = Path(temp_home) / ".basil" / "config"
    temp_basil_preferences = temp_basil_config / "preferences.json"
    temp_legacy_config = Path(temp_home) / ".config" / "basil"
    temp_legacy_preferences = temp_legacy_config / "preferences.json"
    patches = []

    for module_name in (
        "api.core.models.preferences",
        "api.core.models.preferences",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "SETTINGS_DIR"):
            patches.append((module, "SETTINGS_DIR", module.SETTINGS_DIR))
            module.SETTINGS_DIR = temp_basil_config
        if hasattr(module, "SETTINGS_FILE"):
            patches.append((module, "SETTINGS_FILE", module.SETTINGS_FILE))
            module.SETTINGS_FILE = temp_basil_preferences

    for module_name in (
        "api.core.preferences.preferences_io",
        "api.core.preferences.preferences_io",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "SETTINGS_DIR"):
            patches.append((module, "SETTINGS_DIR", module.SETTINGS_DIR))
            module.SETTINGS_DIR = temp_legacy_config
        if hasattr(module, "SETTINGS_FILE"):
            patches.append((module, "SETTINGS_FILE", module.SETTINGS_FILE))
            module.SETTINGS_FILE = temp_legacy_preferences

    return patches


def _restore_patches(patches) -> None:
    for module, attribute, previous_value in reversed(patches):
        setattr(module, attribute, previous_value)


@pytest.fixture(scope="session")
def live_base_url() -> str | None:
    """Return an explicit isolated live target for a manually selected E2E run."""
    if os.getenv("BASIL_RUN_LIVE_TESTS") != "1":
        return None
    return os.getenv("BASIL_LIVE_BASE_URL")


def pytest_addoption(parser):
    parser.addoption(
        "--verbose-logs",
        action="store_true",
        default=False,
        help="Enable verbose logging (-vv -s) and live log output during tests.",
    )
    parser.addoption(
        "--live-summary",
        action="store_true",
        default=False,
        help="Show live per-test PASSED/FAILED lines (-v) without full live logging.",
    )
    parser.addoption(
        "--isolate-home",
        action="store_true",
        default=False,
        help="Force all tests to run with a temporary HOME (read/writes isolated).",
    )
    parser.addoption(
        "--no-isolate-home",
        action="store_true",
        default=False,
        help="Disable HOME isolation (use real HOME). By default tests run with a temporary HOME.",
    )


def pytest_configure(config):
    if config.getoption("--verbose-logs"):
        # Increase verbosity and show live logs
        # Note: We can't change -q, but we can set level and enable live logging.
        config.option.quiet = 0  # override -q from ini
        config.option.log_cli = True
        # Ensure INFO level logs are shown live
        config.option.log_cli_level = "INFO"
        # Also mirror pytest -vv behavior
        config.option.verbose = max(config.option.verbose, 2)
        # And mirror -s behavior (no stdout capture)
        config.option.capture = "no"
    elif config.getoption("--live-summary"):
        # Show live test progress lines without enabling full live logging
        config.option.quiet = 0  # override -q from ini
        config.option.verbose = max(config.option.verbose, 1)  # like -v
        # Keep capture and log_cli defaults for concise output
    # Register custom markers
    try:
        config.addinivalue_line("markers", "use_temp_home: run this test with a temporary HOME (isolated)")
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _session_home_setup(request):
    """Default to real HOME. Optionally force isolation for entire session via --isolate-home.

    Always expose BASIL_TEST_ORIGINAL_HOME for per-test overrides.
    """
    original_home = os.environ.get("HOME")
    if original_home is not None:
        os.environ["BASIL_TEST_ORIGINAL_HOME"] = original_home
    forced = request.config.getoption("--isolate-home") or os.getenv("BASIL_TEST_ISOLATE_HOME") == "1"
    if not forced:
        # Real HOME default
        yield
        os.environ.pop("BASIL_TEST_ORIGINAL_HOME", None)
        return

    # Force isolation for all tests in session
    temp_home = request.config._tmp_path_factory.mktemp("home")  # type: ignore[attr-defined]
    os.environ["HOME"] = str(temp_home)
    preference_path_patches = _patch_loaded_preference_paths(temp_home)
    try:
        # Mirror read-only artifacts (keys, models structure)
        try:
            if original_home:
                orig_keys = os.path.join(original_home, ".basil", "config", "api_keys.json")
                if os.path.isfile(orig_keys):
                    temp_keys_dir = os.path.join(str(temp_home), ".basil", "config")
                    os.makedirs(temp_keys_dir, exist_ok=True)
                    shutil.copy2(orig_keys, os.path.join(temp_keys_dir, "api_keys.json"))
        except Exception:
            pass
        try:
            if original_home:
                orig_models_root = os.path.join(original_home, ".basil", "models")
                if os.path.isdir(orig_models_root):
                    temp_models_root = os.path.join(str(temp_home), ".basil", "models")
                    for dirpath, dirnames, _filenames in os.walk(orig_models_root):
                        rel = os.path.relpath(dirpath, orig_models_root)
                        dest_dir = os.path.join(temp_models_root, rel) if rel != "." else temp_models_root
                        os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            pass
        yield
    finally:
        _restore_patches(preference_path_patches)
        if original_home is not None:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)
        os.environ.pop("BASIL_TEST_ORIGINAL_HOME", None)


@pytest.fixture(autouse=True)
def _per_test_temp_home(request, tmp_path_factory):
    """Per-test opt-in to use a temporary HOME via @pytest.mark.use_temp_home.

    Mirrors read-only artifacts (keys, models structure) for reads; writes stay in temp.
    """
    marker = request.node.get_closest_marker("use_temp_home")
    session_forced = request.config.getoption("--isolate-home") or os.getenv("BASIL_TEST_ISOLATE_HOME") == "1"
    if not marker or session_forced:
        yield
        return

    original_home = os.environ.get("BASIL_TEST_ORIGINAL_HOME") or os.environ.get("HOME")
    prev_home = os.environ.get("HOME")
    temp_home = tmp_path_factory.mktemp("home_case")
    os.environ["HOME"] = str(temp_home)
    preference_path_patches = _patch_loaded_preference_paths(temp_home)
    try:
        # Mirror keys
        try:
            if original_home:
                orig_keys = os.path.join(original_home, ".basil", "config", "api_keys.json")
                if os.path.isfile(orig_keys):
                    temp_keys_dir = os.path.join(str(temp_home), ".basil", "config")
                    os.makedirs(temp_keys_dir, exist_ok=True)
                    shutil.copy2(orig_keys, os.path.join(temp_keys_dir, "api_keys.json"))
        except Exception:
            pass
        # Mirror models structure
        try:
            if original_home:
                orig_models_root = os.path.join(original_home, ".basil", "models")
                if os.path.isdir(orig_models_root):
                    temp_models_root = os.path.join(str(temp_home), ".basil", "models")
                    for dirpath, dirnames, _filenames in os.walk(orig_models_root):
                        rel = os.path.relpath(dirpath, orig_models_root)
                        dest_dir = os.path.join(temp_models_root, rel) if rel != "." else temp_models_root
                        os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            pass
        yield
    finally:
        _restore_patches(preference_path_patches)
        if prev_home is not None:
            os.environ["HOME"] = prev_home
        else:
            os.environ.pop("HOME", None)


@pytest.fixture(scope="session")
def api_base_url(live_base_url: str | None) -> str:
    return live_base_url or "http://testserver"


@pytest.fixture(scope="session")
def ws_base_url(live_base_url: str | None) -> str:
    if live_base_url:
        return _ws_from_http(live_base_url)
    # Placeholder for in-process; tests that require real WS should set BASIL_LIVE_BASE_URL
    return "ws://testserver"


@pytest.fixture(scope="session")
async def api_client(live_base_url: str | None) -> httpx.AsyncClient:
    if live_base_url:
        client = httpx.AsyncClient(base_url=live_base_url, timeout=60.0)
        try:
            yield client
        finally:
            await client.aclose()
    else:
        # In-process ASGI client against our FastAPI app
        from api.main import app

        transport = httpx.ASGITransport(app=app, lifespan="on")
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0)
        try:
            yield client
        finally:
            await client.aclose()


@pytest.fixture(scope="session", autouse=True)
def _release_cached_llama_cpp_models():
    """Release native llama.cpp contexts before pytest exits."""
    yield
    import sys

    for module_name in (
        "api.core.models.reasoning.llama_cpp_model",
        "api.core.models.reasoning.llama_cpp_model",
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            module.shutdown_cached_llama_cpp_models()


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import os
import sys
from pathlib import Path

# Add the project root and src directory to Python path like other agent tests
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from api.main import app

@pytest.fixture
def test_app() -> FastAPI:
    """Create a test instance of the FastAPI application."""
    return app

@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(test_app) 