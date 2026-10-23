from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_hardware_capability_service
from api.core.runtime.hardware_capability_service import HardwareCapabilityProfile
from api.main import app
from api.services.transcription.recommendations.model_recommendation_service import (
    ModelRecommendationService,
    UserPreference,
)
from api.services.transcription.backends.parakeet_components.parakeet_model_manager import (
    _detect_execution_providers,
)


pytestmark = pytest.mark.use_temp_home


def _hardware_profile(**overrides):
    defaults = {
        "platform": "Darwin",
        "machine": "arm64",
        "total_ram_gb": 128,
        "is_apple_silicon": True,
        "chip_label": "Apple M5 Max",
        "memory_tier": "very_high",
        "local_model_memory_budget_gb": 96,
        "cpu_count": 16,
        "gpu_available": True,
        "gpu_backend": "metal",
        "recommended_gpu_layers": -1,
        "memory_optimizations": {"f16_kv": True},
    }
    defaults.update(overrides)
    return HardwareCapabilityProfile(**defaults)


class StubHardwareService:
    def __init__(self, profile):
        self.profile = profile

    def get_profile(self, refresh=False):
        return self.profile

    def get_legacy_system_info(self):
        return self.profile.as_legacy_system_info()


def test_models_system_info_route_preserves_legacy_response_shape():
    app.dependency_overrides[get_hardware_capability_service] = lambda: StubHardwareService(
        _hardware_profile()
    )
    try:
        response = TestClient(app).get("/models/system-info")
    finally:
        app.dependency_overrides.pop(get_hardware_capability_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "totalRamGB": 128,
        "isAppleSilicon": True,
        "gpuAvailable": True,
        "gpuBackend": "metal",
        "platform": "Darwin",
        "machine": "arm64",
    }


def test_system_info_reports_darwin_arm64_memory_and_gpu():
    service = ModelRecommendationService(
        hardware_service=StubHardwareService(_hardware_profile())
    )

    assert service.system_capabilities == {
        "total_ram_gb": 128,
        "is_apple_silicon": True,
        "gpu_available": True,
        "gpu_backend": "metal",
    }

    assert service.get_system_info() == {
        "total_ram_gb": 128,
        "is_apple_silicon": True,
        "gpu_available": True,
        "gpu_backend": "metal",
        "platform": "Darwin",
        "machine": "arm64",
    }


def test_model_compatibility_uses_ninety_percent_ram_budget():
    service = ModelRecommendationService.__new__(ModelRecommendationService)
    service.system_capabilities = {"total_ram_gb": 16}

    assert service._is_model_system_compatible({"recommended_ram": "14GB"})
    assert not service._is_model_system_compatible({"recommended_ram": "15GB"})


def test_gpu_models_receive_current_recommendation_bonus():
    service = ModelRecommendationService.__new__(ModelRecommendationService)
    service.system_capabilities = {"gpu_available": True, "gpu_backend": "metal"}

    score, reasoning = service._calculate_model_score(
        {
            "speed_rating": 8,
            "accuracy_rating": 6,
            "supports_gpu": True,
        },
        UserPreference.BALANCED,
        system_compatible=True,
    )

    assert score == pytest.approx(7.7)
    assert any("Compatible with your system" in item for item in reasoning)
    assert any("GPU acceleration available (metal)" in item for item in reasoning)


def test_parakeet_provider_order_uses_shared_hardware_profile():
    apple_coreml = _hardware_profile(
        coreml_execution_provider_available=True,
        prefer_coreml_onnx=True,
    )
    cuda_linux = _hardware_profile(
        platform="Linux",
        machine="x86_64",
        is_apple_silicon=False,
        chip_label=None,
        gpu_backend="cuda",
        cuda_available=True,
    )

    assert _detect_execution_providers(apple_coreml) == [
        "CoreMLExecutionProvider",
        "CPUExecutionProvider",
    ]
    assert _detect_execution_providers(cuda_linux) == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
