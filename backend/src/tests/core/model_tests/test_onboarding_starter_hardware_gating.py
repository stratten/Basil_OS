"""The first-run reasoning model must fit the Mac it is offered to."""

from types import SimpleNamespace

import pytest

from api.core.models.models_registry import get_local_reasoning_models
from api.core.models.preference_models import defaults
from api.core.models.preference_models.defaults import _get_default_local_reasoning_model_id
from api.core.runtime import mlx_support
from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile
from api.routes.onboarding import get_starter_models
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService

MLX_9B = "Qwen-qwen35-9b-mlx-4bit"
MLX_4B = "Qwen-qwen35-4b-mlx-4bit"
MLX_35B = "Qwen-qwen36-35b-a3b-mlx-4bit"
GGUF_9B = "Qwen-qwen35-9b-q4km"
GGUF_4B = "Qwen-qwen35-4b-q4km"
GGUF_35B = "Qwen-qwen36-35b-a3b-ud-q4km"


@pytest.fixture(autouse=True)
def mlx_supported(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)


@pytest.fixture(autouse=True)
def roomy_disk(monkeypatch):
    """Every test here starts with plenty of free disk space, so the larger model is never held back by the machine running the suite. The disk cases set their own value."""
    monkeypatch.setattr(defaults, "_detected_free_disk_gb", lambda: 500.0)


def _with_free_disk(monkeypatch, free_disk_gb):
    monkeypatch.setattr(defaults, "_detected_free_disk_gb", lambda: free_disk_gb)


def _starter_service(installed):
    return SimpleNamespace(is_model_downloaded=lambda model_type, variant: f"{model_type}-{variant}" in installed)


def _starter_variant(models):
    return next(entry["variant"] for entry in models if entry["model_type"] == "Qwen")


def _on_machine_with(monkeypatch, total_ram_gb):
    monkeypatch.setattr(defaults, "_detected_total_ram_gb", lambda: total_ram_gb)


@pytest.mark.parametrize("total_ram_gb", [8, 16, 18, 23])
def test_a_mac_below_the_nine_b_minimum_is_offered_the_four_b_model(monkeypatch, total_ram_gb):
    _on_machine_with(monkeypatch, total_ram_gb)

    assert _get_default_local_reasoning_model_id() == MLX_4B
    assert _starter_variant(get_starter_models(_starter_service(set()))) == "qwen35-4b-mlx-4bit"


@pytest.mark.parametrize("total_ram_gb", [24, 32, 36, 47])
def test_a_mac_between_the_nine_b_minimum_and_the_upgrade_minimum_keeps_the_nine_b_model(monkeypatch, total_ram_gb):
    _on_machine_with(monkeypatch, total_ram_gb)

    assert _get_default_local_reasoning_model_id() == MLX_9B
    assert _starter_variant(get_starter_models(_starter_service(set()))) == "qwen35-9b-mlx-4bit"


@pytest.mark.parametrize("total_ram_gb", [48, 64, 128])
def test_a_mac_at_or_above_the_upgrade_minimum_is_offered_the_thirty_five_b_model(monkeypatch, total_ram_gb):
    _on_machine_with(monkeypatch, total_ram_gb)

    assert _get_default_local_reasoning_model_id() == MLX_35B
    assert _starter_variant(get_starter_models(_starter_service(set()))) == "qwen36-35b-a3b-mlx-4bit"


def test_the_upgrade_is_never_offered_where_mlx_cannot_run_so_a_gguf_machine_keeps_the_gguf_nine_b(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    _on_machine_with(monkeypatch, 128)

    assert _get_default_local_reasoning_model_id() == GGUF_9B


def test_the_upgrade_is_not_offered_when_the_memory_size_cannot_be_read(monkeypatch):
    _on_machine_with(monkeypatch, None)

    assert _get_default_local_reasoning_model_id() == MLX_9B


def test_an_upgrade_machine_that_already_has_the_gguf_build_is_not_asked_for_a_second_copy(monkeypatch):
    _on_machine_with(monkeypatch, 64)

    models = get_starter_models(_starter_service({GGUF_35B}))

    assert _starter_variant(models) == "qwen36-35b-a3b-ud-q4km"


def test_the_upgrade_pack_description_names_the_download_size(monkeypatch):
    _on_machine_with(monkeypatch, 64)

    models = get_starter_models(_starter_service(set()))

    assert "20GB" in models[2]["description"]


def test_the_fallback_follows_the_runtime_so_a_gguf_machine_gets_the_gguf_four_b(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: False)
    _on_machine_with(monkeypatch, 16)

    assert _get_default_local_reasoning_model_id() == GGUF_4B
    assert _starter_variant(get_starter_models(_starter_service(set()))) == "qwen35-4b-q4km"


def test_an_unreadable_memory_size_leaves_the_flagged_model_in_place(monkeypatch):
    _on_machine_with(monkeypatch, None)

    assert _get_default_local_reasoning_model_id() == MLX_9B


def test_an_explicit_memory_size_overrides_the_detected_one(monkeypatch):
    _on_machine_with(monkeypatch, 128)

    assert _get_default_local_reasoning_model_id(total_ram_gb=16) == MLX_4B
    assert _get_default_local_reasoning_model_id(total_ram_gb=32) == MLX_9B
    assert _get_default_local_reasoning_model_id(total_ram_gb=48) == MLX_35B


def test_a_low_memory_install_that_already_has_the_other_four_b_build_is_not_asked_for_a_second_copy(monkeypatch):
    _on_machine_with(monkeypatch, 16)

    models = get_starter_models(_starter_service({GGUF_4B}))

    assert _starter_variant(models) == "qwen35-4b-q4km"


def test_the_starter_pack_keeps_one_reasoning_model_and_its_description_names_the_size(monkeypatch):
    _on_machine_with(monkeypatch, 16)

    models = get_starter_models(_starter_service(set()))

    assert len(models) == 3 and models[2]["priority"] == 3
    assert "2.9GB" in models[2]["description"]


def test_every_declared_fallback_exists_and_is_smaller_than_the_model_it_replaces():
    raw = get_local_reasoning_models()

    for model_id in (MLX_9B, GGUF_9B):
        cfg = raw[model_id]
        fallback = raw[cfg["onboarding_low_memory_fallback"]]
        assert float(fallback["size"].rstrip("GB")) < float(cfg["size"].rstrip("GB"))
        assert cfg["onboarding_min_ram_gb"] > int(fallback["recommended_ram"].rstrip("GB"))
        assert fallback["handler"] == cfg["handler"]


def test_the_declared_upgrade_exists_is_larger_and_only_applies_where_it_fits():
    raw = get_local_reasoning_models()
    cfg = raw[MLX_9B]
    upgrade = raw[cfg["onboarding_high_memory_upgrade"]]

    assert upgrade["handler"] == cfg["handler"]
    assert float(upgrade["size"].rstrip("GB")) > float(cfg["size"].rstrip("GB"))
    assert cfg["onboarding_upgrade_min_ram_gb"] >= int(upgrade["recommended_ram"].rstrip("GB"))
    assert cfg["onboarding_upgrade_min_ram_gb"] > cfg["onboarding_min_ram_gb"]
    assert upgrade["onboarding_low_memory_fallback"] == MLX_9B
    assert upgrade.get("recommended_for_onboarding") is False


def _profile(total_ram_gb):
    return HardwareCapabilityProfile(
        platform="Darwin",
        machine="arm64",
        total_ram_gb=total_ram_gb,
        is_apple_silicon=True,
        chip_label="Apple M2",
        memory_tier="standard",
        local_model_memory_budget_gb=7,
        cpu_count=8,
        gpu_available=True,
        gpu_backend="metal",
        recommended_gpu_layers=33,
    )


def test_setup_discovery_judges_fit_by_whole_machine_memory_not_by_the_smaller_local_budget():
    service = SetupAssistantDiscoveryService.__new__(SetupAssistantDiscoveryService)
    config = {"handler": "mlx", "features": [], "recommended_ram": "16GB"}

    on_sixteen = service._build_model_hardware_metadata(config, _profile(16))
    on_eight = service._build_model_hardware_metadata(config, _profile(8))

    assert on_sixteen["hardware_fits_memory_budget"] == "true"
    assert on_eight["hardware_fits_memory_budget"] == "false"


def test_the_four_b_model_is_offered_as_fitting_an_eight_gb_mac():
    service = SetupAssistantDiscoveryService.__new__(SetupAssistantDiscoveryService)
    raw = get_local_reasoning_models()

    metadata = service._build_model_hardware_metadata(raw[MLX_4B], _profile(8))

    assert metadata["hardware_fits_memory_budget"] == "true"


class _FakeDownloadManager:
    def __init__(self, fail=False):
        self.started = []
        self.fail = fail

    async def start(self, model_type, variant):
        if self.fail:
            raise RuntimeError("network down")
        self.started.append((model_type, variant))
        return SimpleNamespace(status="queued")


def _request(manager):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(download_manager=manager)))


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_starts_the_download_when_it_is_not_installed(monkeypatch):
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 32)
    manager = _FakeDownloadManager()

    result = await use_smaller_reasoning_model(_request(manager), _starter_service(set()))

    assert result.status == "downloading"
    assert result.model_id == MLX_4B
    assert manager.started == [("Qwen", "qwen35-4b-mlx-4bit")]
    assert "2.9GB" in result.message


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_switches_the_preference_once_the_model_is_installed(monkeypatch):
    from api.core.preferences.preferences_io import load_preferences
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 32)
    manager = _FakeDownloadManager()

    result = await use_smaller_reasoning_model(_request(manager), _starter_service({MLX_4B}))

    assert result.status == "switched"
    assert manager.started == []
    assert load_preferences().models.reasoning_model == MLX_4B


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_reports_unavailable_when_the_current_model_is_already_the_smallest(monkeypatch):
    from api.core.preferences.preferences_io import load_preferences, save_preferences
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 8)
    preferences = load_preferences()
    preferences.models.reasoning_model = MLX_4B
    save_preferences(preferences)
    manager = _FakeDownloadManager()

    result = await use_smaller_reasoning_model(_request(manager), _starter_service(set()))

    assert result.status == "unavailable"
    assert "Basil Cloud" in result.message
    assert manager.started == []


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_reports_a_failed_download_start_without_raising(monkeypatch):
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 32)

    result = await use_smaller_reasoning_model(_request(_FakeDownloadManager(fail=True)), _starter_service(set()))

    assert result.status == "unavailable"
    assert result.model_id == MLX_4B


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_steps_the_thirty_five_b_down_to_the_nine_b_and_starts_nothing_until_asked(monkeypatch):
    from api.core.preferences.preferences_io import load_preferences
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 64)
    assert load_preferences().models.reasoning_model == MLX_35B
    manager = _FakeDownloadManager()

    result = await use_smaller_reasoning_model(_request(manager), _starter_service(set()))

    assert result.status == "downloading"
    assert result.model_id == MLX_9B
    assert manager.started == [("Qwen", "qwen35-9b-mlx-4bit")]
    assert "5.6GB" in result.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("total_ram_gb", "expected_id"),
    [(16, MLX_4B), (32, MLX_9B), (64, MLX_35B)],
)
async def test_setup_discovery_marks_exactly_the_model_chosen_for_this_machine(monkeypatch, total_ram_gb, expected_id):
    monkeypatch.setattr(
        "api.services.setup_assistant.discovery_service.HardwareCapabilityService.get_profile",
        lambda self: _profile(total_ram_gb),
    )
    service = SetupAssistantDiscoveryService(model_service=None)

    response = await service.collect_model_catalog_facts()

    marked = [
        fact.value
        for fact in response.facts
        if fact.metadata.get("recommended_for_this_machine") == "true"
    ]
    assert marked == [expected_id]


def test_a_download_needs_twice_the_model_size_plus_a_margin_of_free_disk():
    assert defaults._download_disk_required_gb("20GB") == 42.0
    assert defaults._download_disk_required_gb("5.6GB") == pytest.approx(13.2)
    assert defaults._download_disk_required_gb("151MB") is None
    assert defaults._download_disk_required_gb(None) is None


def test_a_mac_with_the_memory_for_the_upgrade_but_too_little_disk_falls_back_to_the_nine_b_and_records_why(monkeypatch):
    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 41.9)

    choice = defaults._choose_local_reasoning_model(total_ram_gb=64)

    assert choice.model_id == MLX_9B
    assert choice.preferred_model_id == MLX_35B
    assert choice.blocked_by_disk is True
    assert choice.required_disk_gb == 42.0
    assert choice.free_disk_gb == 41.9
    assert _get_default_local_reasoning_model_id() == MLX_9B
    assert _starter_variant(get_starter_models(_starter_service(set()))) == "qwen35-9b-mlx-4bit"


def test_a_mac_with_exactly_the_required_disk_gets_the_upgrade(monkeypatch):
    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 42.0)

    choice = defaults._choose_local_reasoning_model(total_ram_gb=64)

    assert choice.model_id == MLX_35B
    assert choice.blocked_by_disk is False


def test_an_unreadable_disk_size_does_not_hold_back_the_upgrade(monkeypatch):
    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, None)

    choice = defaults._choose_local_reasoning_model(total_ram_gb=64)

    assert choice.model_id == MLX_35B
    assert choice.blocked_by_disk is False


@pytest.mark.parametrize("total_ram_gb", [16, 32])
def test_a_nearly_full_disk_changes_nothing_on_a_mac_that_was_never_offered_the_upgrade(monkeypatch, total_ram_gb):
    _on_machine_with(monkeypatch, total_ram_gb)
    _with_free_disk(monkeypatch, 1.0)

    choice = defaults._choose_local_reasoning_model(total_ram_gb=total_ram_gb)

    assert choice.blocked_by_disk is False
    assert choice.model_id == (MLX_4B if total_ram_gb == 16 else MLX_9B)


def test_an_explicit_free_disk_size_overrides_the_detected_one(monkeypatch):
    _with_free_disk(monkeypatch, 500.0)

    assert _get_default_local_reasoning_model_id(total_ram_gb=64, free_disk_gb=10.0) == MLX_9B
    assert _get_default_local_reasoning_model_id(total_ram_gb=64, free_disk_gb=100.0) == MLX_35B


@pytest.mark.asyncio
async def test_setup_discovery_tells_the_agent_the_best_model_does_not_fit_the_disk_and_offers_the_nine_b(monkeypatch):
    monkeypatch.setattr(
        "api.services.setup_assistant.discovery_service.HardwareCapabilityService.get_profile",
        lambda self: _profile(64),
    )
    _with_free_disk(monkeypatch, 30.0)
    service = SetupAssistantDiscoveryService(model_service=None)

    response = await service.collect_model_catalog_facts()
    by_id = {fact.value: fact.metadata for fact in response.facts if fact.id.startswith("model-catalog-Qwen-")}

    assert by_id[MLX_9B]["recommended_for_this_machine"] == "true"
    assert by_id[MLX_9B]["best_for_this_machine_memory"] == "false"
    assert by_id[MLX_9B]["disk_fits_download"] == "true"
    assert by_id[MLX_35B]["recommended_for_this_machine"] == "false"
    assert by_id[MLX_35B]["best_for_this_machine_memory"] == "true"
    assert by_id[MLX_35B]["disk_fits_download"] == "false"
    assert by_id[MLX_35B]["free_disk_gb"] == "30.0"
    assert by_id[MLX_35B]["download_disk_required_gb"] == "42.0"


@pytest.mark.asyncio
async def test_setup_discovery_marks_the_upgrade_as_both_best_and_recommended_when_the_disk_has_room(monkeypatch):
    monkeypatch.setattr(
        "api.services.setup_assistant.discovery_service.HardwareCapabilityService.get_profile",
        lambda self: _profile(64),
    )
    _with_free_disk(monkeypatch, 200.0)
    service = SetupAssistantDiscoveryService(model_service=None)

    response = await service.collect_model_catalog_facts()
    metadata = next(fact.metadata for fact in response.facts if fact.value == MLX_35B)

    assert metadata["recommended_for_this_machine"] == "true"
    assert metadata["best_for_this_machine_memory"] == "true"
    assert metadata["disk_fits_download"] == "true"


def test_the_setup_agent_prompt_states_the_disk_warning_and_the_strong_recommendation():
    from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt

    prompt = build_setup_agent_system_prompt()

    for fact_name in ("recommended_for_this_machine", "best_for_this_machine_memory", "free_disk_gb", "download_disk_required_gb", "disk_fits_download"):
        assert fact_name in prompt
    assert "strongly recommend that the user free up that space" in prompt
    assert "discover_local_models" in prompt
    assert "Never propose a model whose `disk_fits_download` is `false`" in prompt
    assert "nothing downloads until they approve" in prompt


class _DiskFullForReasoningManager:
    """Refuses the Qwen reasoning download for lack of disk space and accepts every other model."""

    def __init__(self):
        self.started = []

    async def start(self, model_type, variant):
        from api.core.models.model_download.disk_space import InsufficientDiskSpaceError

        if model_type == "Qwen":
            raise InsufficientDiskSpaceError(f"{model_type}-{variant}", "Qwen3.5-9B MLX 4-bit", 13.2, 4.0)
        self.started.append((model_type, variant))
        return SimpleNamespace(status="queued")


def test_there_is_no_disk_warning_when_the_disk_has_room(monkeypatch):
    from api.routes.onboarding import starter_disk_warnings

    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 500.0)

    assert starter_disk_warnings() == []


def test_there_is_no_disk_warning_on_a_mac_that_was_never_offered_the_upgrade(monkeypatch):
    from api.routes.onboarding import starter_disk_warnings

    _on_machine_with(monkeypatch, 32)
    _with_free_disk(monkeypatch, 1.0)

    assert starter_disk_warnings() == []


def test_a_blocked_upgrade_produces_one_warning_that_names_both_models_and_strongly_recommends_freeing_space(monkeypatch):
    from api.routes.onboarding import starter_disk_warnings

    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 30.0)

    warnings = starter_disk_warnings()

    assert len(warnings) == 1
    assert "Qwen3.6-35B-A3B MLX 4-bit" in warnings[0]
    assert "Qwen3.5-9B MLX 4-bit" in warnings[0]
    assert "needs about 42 GB free" in warnings[0] and "has 30 GB free" in warnings[0]
    assert "strongly recommends freeing up about 12 GB" in warnings[0]


@pytest.mark.asyncio
async def test_the_starter_status_endpoint_carries_the_warning_and_clears_it_once_space_is_freed(monkeypatch):
    from api.routes.onboarding import get_starter_models_status

    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 30.0)

    blocked = await get_starter_models_status(_starter_service(set()))

    assert len(blocked.warnings) == 1
    assert _starter_variant([model.model_dump() for model in blocked.models]) == "qwen35-9b-mlx-4bit"

    _with_free_disk(monkeypatch, 60.0)
    freed = await get_starter_models_status(_starter_service(set()))

    assert freed.warnings == []
    assert _starter_variant([model.model_dump() for model in freed.models]) == "qwen36-35b-a3b-mlx-4bit"


@pytest.mark.asyncio
async def test_starting_the_starter_pack_reports_a_refused_model_as_a_warning_and_still_starts_the_rest(monkeypatch):
    from api.routes.onboarding import start_starter_model_downloads

    _on_machine_with(monkeypatch, 32)
    manager = _DiskFullForReasoningManager()

    response = await start_starter_model_downloads(_request(manager), _starter_service(set()))

    assert response.downloads_started == 2
    assert [started[0] for started in manager.started] == ["OpenAI", "NVIDIA"]
    assert any("Not enough free disk space to download Qwen3.5-9B MLX 4-bit" in warning for warning in response.warnings)


@pytest.mark.use_temp_home
@pytest.mark.asyncio
async def test_use_smaller_model_explains_a_full_disk_instead_of_blaming_the_connection(monkeypatch):
    from api.core.models.model_download.disk_space import InsufficientDiskSpaceError
    from api.routes.onboarding import use_smaller_reasoning_model

    _on_machine_with(monkeypatch, 32)
    error = InsufficientDiskSpaceError(MLX_4B, "Qwen3.5-4B MLX 4-bit", 7.8, 3.0)

    async def refuse(model_type, variant):
        raise error

    manager = SimpleNamespace(start=refuse)

    result = await use_smaller_reasoning_model(_request(manager), _starter_service(set()))

    assert result.status == "unavailable"
    assert result.model_id == MLX_4B
    assert result.message == str(error)
    assert "connection" not in result.message


@pytest.mark.asyncio
async def test_the_live_model_status_reports_free_disk_and_whether_the_larger_model_is_blocked(monkeypatch):
    from api.services.setup_assistant.agent_graph.setup_agent_tooling.discovery_tools import check_setup_model_status

    _on_machine_with(monkeypatch, 64)
    _with_free_disk(monkeypatch, 30.0)
    downloader = SimpleNamespace(
        get_installed_models=lambda: {},
        progress_tracker=SimpleNamespace(get_operation_status=lambda model_id: "unknown", get_progress=lambda model_id: 0.0),
    )
    factory = SimpleNamespace(discovery_service=SimpleNamespace(model_service=SimpleNamespace(model_downloader=downloader)))

    status = await check_setup_model_status(factory)

    assert status["free_disk_gb"] == 30.0
    assert status["local_reasoning_recommendation"] == {
        "recommended_model_id": MLX_9B,
        "best_for_this_machine_memory_model_id": MLX_35B,
        "blocked_by_disk": True,
        "download_disk_required_gb": 42.0,
    }

    _with_free_disk(monkeypatch, 80.0)
    freed = await check_setup_model_status(factory)

    assert freed["local_reasoning_recommendation"]["blocked_by_disk"] is False
    assert freed["local_reasoning_recommendation"]["recommended_model_id"] == MLX_35B
