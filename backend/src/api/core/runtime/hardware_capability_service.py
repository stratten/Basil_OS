"""Shared hardware capability detection for local runtime planning.

This module centralizes the hardware probes that were previously split across
model recommendations, GPU setup, ONNX provider selection, and transcription
backend support. It deliberately reports capabilities without changing runtime
behavior; consumers decide how to use the profile.
"""

from __future__ import annotations

import importlib.util
import logging
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from api.core.models.gpu_manager import GPUManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareCapabilityProfile:
    """Machine-level capabilities relevant to local model runtimes."""

    platform: str
    machine: str
    total_ram_gb: int
    is_apple_silicon: bool
    chip_label: Optional[str]
    memory_tier: str
    local_model_memory_budget_gb: int
    cpu_count: int
    gpu_available: bool
    gpu_backend: Optional[str]
    recommended_gpu_layers: int
    memory_optimizations: Dict[str, Any] = field(default_factory=dict)
    mps_available: bool = False
    cuda_available: bool = False
    coreml_execution_provider_available: bool = False
    mlx_whisper_available: bool = False
    faster_whisper_available: bool = False
    recommended_threads: int = 4
    recommended_llama_batch: int = 512
    recommended_llama_ubatch: int = 512
    prefer_mlx_whisper: bool = False
    prefer_coreml_onnx: bool = False
    capability_notes: List[str] = field(default_factory=list)

    def as_legacy_system_info(self) -> Dict[str, Any]:
        """Return the existing /models/system-info dictionary shape."""

        return {
            "total_ram_gb": self.total_ram_gb,
            "is_apple_silicon": self.is_apple_silicon,
            "gpu_available": self.gpu_available,
            "gpu_backend": self.gpu_backend,
            "platform": self.platform,
            "machine": self.machine,
        }


class HardwareCapabilityService:
    """Detect and cache local hardware/runtime capabilities."""

    def __init__(
        self,
        gpu_manager_factory: Callable[[], GPUManager] = GPUManager,
        module_available: Optional[Callable[[str], bool]] = None,
        subprocess_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._gpu_manager_factory = gpu_manager_factory
        self._module_available = module_available or self._default_module_available
        self._subprocess_run = subprocess_run
        self._profile: Optional[HardwareCapabilityProfile] = None

    def get_profile(self, refresh: bool = False) -> HardwareCapabilityProfile:
        """Return the cached hardware profile, optionally forcing refresh."""

        if self._profile is None or refresh:
            self._profile = self._detect_profile()
        return self._profile

    def get_legacy_system_info(self, refresh: bool = False) -> Dict[str, Any]:
        """Compatibility wrapper for existing system-info consumers."""

        return self.get_profile(refresh=refresh).as_legacy_system_info()

    def _detect_profile(self) -> HardwareCapabilityProfile:
        system = platform.system()
        machine = platform.machine()
        total_ram_gb = self._detect_total_ram_gb(system)
        is_apple_silicon = system == "Darwin" and machine.lower() in {"arm64", "aarch64"}
        chip_label = self._detect_chip_label(system)
        cpu_count = self._detect_cpu_count()

        gpu_caps = self._detect_gpu_capabilities()
        mps_available = self._torch_backend_available("mps")
        cuda_available = self._torch_backend_available("cuda")
        onnx_providers = self._detect_onnx_providers()

        profile = HardwareCapabilityProfile(
            platform=system,
            machine=machine,
            total_ram_gb=total_ram_gb,
            is_apple_silicon=is_apple_silicon,
            chip_label=chip_label,
            memory_tier=self._memory_tier(total_ram_gb),
            local_model_memory_budget_gb=self._local_model_memory_budget(total_ram_gb),
            cpu_count=cpu_count,
            gpu_available=bool(gpu_caps.get("available", False)),
            gpu_backend=gpu_caps.get("backend"),
            recommended_gpu_layers=int(gpu_caps.get("n_gpu_layers") or 0),
            memory_optimizations=dict(gpu_caps.get("memory_optimizations") or {}),
            mps_available=mps_available,
            cuda_available=cuda_available,
            coreml_execution_provider_available="CoreMLExecutionProvider" in onnx_providers,
            mlx_whisper_available=self._module_available("mlx_whisper"),
            faster_whisper_available=self._module_available("faster_whisper"),
            recommended_threads=self._recommended_threads(cpu_count),
            recommended_llama_batch=self._recommended_llama_batch(total_ram_gb),
            recommended_llama_ubatch=self._recommended_llama_ubatch(total_ram_gb),
            prefer_mlx_whisper=False,
            prefer_coreml_onnx=False,
            capability_notes=[],
        )

        profile = self._with_preferences_and_notes(profile)
        logger.info("Detected hardware capability profile: %s", profile)
        return profile

    def _with_preferences_and_notes(
        self,
        profile: HardwareCapabilityProfile,
    ) -> HardwareCapabilityProfile:
        notes: List[str] = []
        prefer_mlx_whisper = profile.is_apple_silicon and profile.mlx_whisper_available
        prefer_coreml_onnx = (
            profile.is_apple_silicon and profile.coreml_execution_provider_available
        )

        if profile.is_apple_silicon and not profile.mlx_whisper_available:
            notes.append(
                "MLX Whisper is not installed; local Whisper live transcription may fall back to CPU-bound Faster-Whisper."
            )
        if profile.is_apple_silicon and profile.faster_whisper_available:
            notes.append(
                "Faster-Whisper is available, but CTranslate2 does not use MPS on Apple Silicon."
            )
        if prefer_coreml_onnx:
            notes.append("ONNX Runtime CoreML execution provider is available for compatible local ASR models.")

        return HardwareCapabilityProfile(
            **{
                **profile.__dict__,
                "prefer_mlx_whisper": prefer_mlx_whisper,
                "prefer_coreml_onnx": prefer_coreml_onnx,
                "capability_notes": notes,
            }
        )

    def _detect_total_ram_gb(self, system: str) -> int:
        try:
            if system == "Darwin":
                result = self._subprocess_run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return round(int(str(result.stdout).strip()) / (1024**3))
            if system == "Linux":
                with open("/proc/meminfo", "r", encoding="utf-8") as meminfo:
                    for line in meminfo:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            return round(kb / (1024**2))
        except Exception as exc:
            logger.warning("Error detecting total RAM: %s", exc)
        return 16

    def _detect_chip_label(self, system: str) -> Optional[str]:
        if system != "Darwin":
            return None
        try:
            result = self._subprocess_run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=False,
            )
            label = str(result.stdout).strip()
            return label or None
        except Exception:
            return None

    def _detect_cpu_count(self) -> int:
        try:
            import os

            return os.cpu_count() or 1
        except Exception:
            return 1

    def _detect_gpu_capabilities(self) -> Dict[str, Any]:
        try:
            return dict(self._gpu_manager_factory().capabilities)
        except Exception as exc:
            logger.warning("Error detecting GPU capabilities: %s", exc)
            return {
                "available": False,
                "backend": None,
                "n_gpu_layers": 0,
                "memory_optimizations": {},
            }

    def _torch_backend_available(self, backend: str) -> bool:
        try:
            import torch

            if backend == "mps":
                return bool(
                    hasattr(torch, "backends")
                    and hasattr(torch.backends, "mps")
                    and torch.backends.mps.is_available()
                )
            if backend == "cuda":
                return bool(torch.cuda.is_available())
        except Exception:
            return False
        return False

    def _detect_onnx_providers(self) -> List[str]:
        try:
            import onnxruntime as ort

            return list(ort.get_available_providers())
        except Exception:
            return []

    @staticmethod
    def _default_module_available(module_name: str) -> bool:
        return importlib.util.find_spec(module_name) is not None

    @staticmethod
    def _memory_tier(total_ram_gb: int) -> str:
        if total_ram_gb >= 96:
            return "very_high"
        if total_ram_gb >= 48:
            return "high"
        if total_ram_gb >= 24:
            return "medium"
        if total_ram_gb >= 12:
            return "standard"
        return "low"

    @staticmethod
    def _local_model_memory_budget(total_ram_gb: int) -> int:
        if total_ram_gb >= 96:
            return int(total_ram_gb * 0.75)
        if total_ram_gb >= 48:
            return int(total_ram_gb * 0.65)
        if total_ram_gb >= 24:
            return int(total_ram_gb * 0.55)
        return max(4, int(total_ram_gb * 0.45))

    @staticmethod
    def _recommended_threads(cpu_count: int) -> int:
        return max(4, min(max(cpu_count - 2, 1), 12))

    @staticmethod
    def _recommended_llama_batch(total_ram_gb: int) -> int:
        if total_ram_gb >= 96:
            return 2048
        if total_ram_gb >= 48:
            return 1024
        return 512

    @staticmethod
    def _recommended_llama_ubatch(total_ram_gb: int) -> int:
        if total_ram_gb >= 96:
            return 1024
        return 512
