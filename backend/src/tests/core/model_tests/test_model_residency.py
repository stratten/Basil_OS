"""Local model residency: leases, window holds, idle unload and run scopes.

Everything here uses fake models; no native model is loaded.
"""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from api.core.models import model_manager as manager_module
from api.core.models.base_model import ModelState
from api.core.models.model_manager import ModelManager
from api.core.models.model_run_scope import (
    attach_model_to_current_run,
    current_model_run_scope,
    model_run_scope,
)
from api.routes.websocket_window_presence import (
    clear_connection_window_holds,
    handle_window_presence,
)


class FakeModel:
    def __init__(self) -> None:
        self.unloaded = 0
        self.state = ModelState.READY

    @property
    def is_loaded(self) -> bool:
        return self.state == ModelState.READY

    async def unload(self) -> None:
        self.unloaded += 1
        self.state = ModelState.UNLOADED


_created_managers: list = []


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch):
    monkeypatch.setattr(manager_module, "MIN_UNLEASED_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(manager_module, "PROTECTED_RECHECK_SECONDS", 0.02)


@pytest_asyncio.fixture(autouse=True)
async def cancel_leftover_timers():
    yield
    for manager in _created_managers:
        for entry in manager._models.values():
            if entry.unload_task is not None:
                entry.unload_task.cancel()
    _created_managers.clear()
    await asyncio.sleep(0)


class Settings:
    def __init__(self, idle: float = 0, keep: bool = True) -> None:
        self.idle = idle
        self.keep = keep


def make_manager(tmp_path: Path, settings: Settings) -> ModelManager:
    manager = ModelManager(
        tmp_path,
        idle_seconds_provider=lambda: settings.idle,
        keep_for_windows_provider=lambda: settings.keep,
    )
    # The real manager truncates to whole seconds; tests need sub-second delays.
    _created_managers.append(manager)
    manager._idle_seconds = lambda: max(0.0, float(settings.idle))  # type: ignore[method-assign]
    return manager


async def settle(seconds: float = 0.15) -> None:
    await asyncio.sleep(seconds)


@pytest.mark.asyncio
async def test_lease_blocks_idle_unload_until_released(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    lease = manager.acquire_lease("local-a", owner="run-1")

    await settle(0.3)  # well past the unleased grace period
    assert model.unloaded == 0
    assert manager.is_leased("local-a")

    lease.release()
    await settle()
    assert model.unloaded == 1
    assert "local-a" not in manager._models


@pytest.mark.asyncio
async def test_lease_release_is_idempotent_and_counts_holders(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    first = manager.acquire_lease("local-a")
    second = manager.acquire_lease("local-a")

    first.release()
    first.release()
    await settle()
    assert model.unloaded == 0  # the second holder still counts

    second.release()
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_zero_delay_still_gives_unleased_loads_a_grace_period(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    await asyncio.sleep(0.01)
    assert model.unloaded == 0  # not unloaded between load and first use

    await settle(0.2)
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_idle_delay_applies_to_the_default_model_too(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0.1))
    model = FakeModel()
    manager.adopt_model("default-model", model)

    await asyncio.sleep(0.03)
    assert model.unloaded == 0
    await settle(0.3)
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_touch_resets_the_idle_clock(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0.15))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    for _ in range(4):
        await asyncio.sleep(0.07)
        manager.touch_model("local-a")
    assert model.unloaded == 0

    await settle(0.4)
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_open_window_keeps_model_loaded_and_close_starts_the_delay(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0, keep=True))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    manager.set_window_hold("ws-1", "window-1", "task-1")

    await settle(0.3)
    assert model.unloaded == 0

    manager.clear_window_hold("ws-1", "window-1")
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_window_hold_is_ignored_when_the_setting_is_off(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0, keep=False))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    manager.set_window_hold("ws-1", "window-1")

    await settle(0.3)
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_run_lease_is_honored_even_when_the_window_setting_is_off(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0, keep=False))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    lease = manager.acquire_lease("local-a")

    await settle(0.3)
    assert model.unloaded == 0
    lease.release()
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_window_holds_from_a_dropped_connection_are_cleared(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0, keep=True))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    manager.set_window_hold("ws-1", "window-1")
    manager.set_window_hold("ws-1", "window-2")
    manager.set_window_hold("ws-2", "window-9")

    manager.clear_owner_window_holds("ws-1")
    assert manager.window_hold_count() == 1
    await settle(0.2)
    assert model.unloaded == 0  # ws-2 still has a window open

    manager.clear_owner_window_holds("ws-2")
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_shortening_the_delay_applies_to_already_loaded_models(tmp_path):
    settings = Settings(idle=1000)
    manager = make_manager(tmp_path, settings)
    model = FakeModel()
    manager.adopt_model("local-a", model)
    await settle(0.05)
    assert model.unloaded == 0

    settings.idle = 0
    manager.reschedule_idle_timers()
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_turning_the_window_setting_off_releases_a_window_hold(tmp_path):
    settings = Settings(idle=0, keep=True)
    manager = make_manager(tmp_path, settings)
    model = FakeModel()
    manager.adopt_model("local-a", model)
    manager.set_window_hold("ws-1", "window-1")
    await settle(0.2)
    assert model.unloaded == 0

    settings.keep = False
    await settle(0.2)  # the protected recheck notices the new setting
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_unload_listener_is_told_about_idle_unloads(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0))
    unloaded = []
    manager.add_unload_listener(unloaded.append)
    manager.adopt_model("local-a", FakeModel())

    await settle(0.3)
    assert unloaded == ["local-a"]


@pytest.mark.asyncio
async def test_unload_if_unprotected_reports_what_happened(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=1000, keep=True))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    assert await manager.unload_if_unprotected("absent") == "not_loaded"

    lease = manager.acquire_lease("local-a")
    assert await manager.unload_if_unprotected("local-a") == "in_use"
    assert model.unloaded == 0

    lease.release()
    manager.set_window_hold("ws-1", "w")
    assert await manager.unload_if_unprotected("local-a") == "in_use"

    manager.clear_window_hold("ws-1", "w")
    assert await manager.unload_if_unprotected("local-a") == "unloaded"
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_idle_timer_really_awaits_the_unload(tmp_path):
    """The timer must not cancel itself while unloading (a real unload awaits)."""
    manager = make_manager(tmp_path, Settings(idle=0))

    class SlowModel(FakeModel):
        async def unload(self) -> None:
            await asyncio.sleep(0.05)
            await super().unload()

    model = SlowModel()
    manager.adopt_model("local-a", model)
    await settle(0.4)
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_retired_wrapper_that_is_reloaded_is_adopted_again(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=1000))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    await manager.unload_model("local-a")
    assert manager.acquire_lease_for_model(model) is None  # not loaded: nothing to hold

    model.state = ModelState.READY  # the holder reloaded it behind the manager's back
    lease = manager.acquire_lease_for_model(model, owner="resumed-run")
    assert lease is not None
    assert manager.model_name_for(model) == "local-a"
    lease.release()


def test_unmanaged_models_get_no_lease(tmp_path):
    manager = make_manager(tmp_path, Settings())
    assert manager.acquire_lease_for_model(FakeModel()) is None


@pytest.mark.asyncio
async def test_run_scope_leases_the_model_and_releases_on_exit(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=0))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    with model_run_scope(owner="test") as scope:
        assert current_model_run_scope() is scope
        assert attach_model_to_current_run(model, manager=manager) is True
        assert attach_model_to_current_run(model, manager=manager) is True  # idempotent
        assert scope.lease_count == 1
        await settle(0.3)
        assert model.unloaded == 0

    assert current_model_run_scope() is None
    await settle()
    assert model.unloaded == 1


@pytest.mark.asyncio
async def test_run_scope_releases_when_the_run_fails(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=1000))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    with pytest.raises(RuntimeError):
        with model_run_scope():
            attach_model_to_current_run(model, manager=manager)
            raise RuntimeError("run failed")
    assert not manager.is_leased("local-a")


@pytest.mark.asyncio
async def test_lease_taken_in_a_child_task_is_released_with_the_run(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=1000))
    model = FakeModel()
    manager.adopt_model("local-a", model)

    with model_run_scope():
        await asyncio.create_task(asyncio.sleep(0, result=attach_model_to_current_run(model, manager=manager)))
        assert manager.is_leased("local-a")
    assert not manager.is_leased("local-a")


def test_attach_without_a_scope_is_a_noop():
    assert attach_model_to_current_run(FakeModel()) is False


def test_run_scope_survives_deepcopy():
    import copy

    with model_run_scope() as scope:
        assert copy.deepcopy({"scope": scope})["scope"] is scope


@pytest.mark.asyncio
async def test_window_presence_messages_add_and_remove_holds(tmp_path):
    manager = make_manager(tmp_path, Settings(idle=1000))

    assert handle_window_presence("ws-1", {"window_id": "w1", "present": True, "agent_task_id": "t"}, manager)
    assert manager.window_hold_count() == 1
    assert handle_window_presence("ws-1", {"window_id": "w1", "present": False}, manager)
    assert manager.window_hold_count() == 0
    assert not handle_window_presence("ws-1", {"present": True}, manager)  # no window id

    handle_window_presence("ws-1", {"window_id": "w2", "present": True}, manager)
    clear_connection_window_holds("ws-1", manager)
    assert manager.window_hold_count() == 0


@pytest.mark.asyncio
async def test_coordinator_leases_its_model_for_the_duration_of_the_run(tmp_path, monkeypatch):
    import logging
    from types import SimpleNamespace

    from api.core.services import model_service as model_service_module
    from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator

    manager = make_manager(tmp_path, Settings(idle=1000))
    model = FakeModel()
    manager.adopt_model("local-a", model)
    monkeypatch.setattr(
        model_service_module, "get_model_service", lambda: SimpleNamespace(model_manager=manager)
    )

    coordinator = WorkflowCoordinator.__new__(WorkflowCoordinator)
    coordinator._llm_model = None
    coordinator._provided_llm_model = model
    coordinator.logger = logging.getLogger("test")
    coordinator.request_analyzer = SimpleNamespace()

    with model_run_scope():
        await coordinator._ensure_llm_components_initialized(context={})
        assert manager.is_leased("local-a")
    assert not manager.is_leased("local-a")

    # Outside a run (a one-off call) nothing is leased and nothing breaks.
    coordinator._llm_model = None
    await coordinator._ensure_llm_components_initialized(context={})
    assert not manager.is_leased("local-a")


@pytest.mark.asyncio
async def test_every_graph_run_opens_and_closes_a_model_run_scope(tmp_path):
    from api.services.agent_processing.lifecycle.execution_graph.agent_graph_runtime import (
        _open_tool_enhanced_graph,
    )

    assert current_model_run_scope() is None
    async with _open_tool_enhanced_graph(checkpoint_path=str(tmp_path / "checkpoints.db")):
        assert current_model_run_scope() is not None
    assert current_model_run_scope() is None


@pytest.mark.asyncio
async def test_graph_run_scope_is_released_when_the_run_raises(tmp_path):
    from api.services.agent_processing.lifecycle.execution_graph.agent_graph_runtime import (
        _open_tool_enhanced_graph,
    )

    with pytest.raises(RuntimeError):
        async with _open_tool_enhanced_graph(checkpoint_path=str(tmp_path / "checkpoints.db")):
            raise RuntimeError("run failed")
    assert current_model_run_scope() is None
