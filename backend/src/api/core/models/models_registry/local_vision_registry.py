"""
Local vision-capable models.

These entries are merged into the unified registry for capability discovery and
Settings > Models download management. Agent runtime availability checks remain
filesystem-only and never initiate downloads.

The local vision fallback uses Qwen's official Qwen3-VL Instruct GGUF repositories, loaded through
llama-cpp-python's generic multimodal handler (``chat_handler: "mtmd"``). The Qwen2.5-VL entries it
replaces were removed because Qwen2.5-VL is two model generations old; saved preferences that name
them are migrated in ``preference_models/migrations.py``.
"""

from pathlib import Path
from typing import Any, Dict


def _qwen3_vl_instruct_entry(
    *,
    size_label: str,
    main_sha256: str,
    parameters: str,
    total_size: str,
    recommended_ram: str,
    display_order: int,
    description: str,
) -> Dict[str, Any]:
    """Build a registry entry for one Qwen3-VL Instruct size from Qwen's official GGUF repository."""
    repo_url = f"https://huggingface.co/Qwen/Qwen3-VL-{size_label}-Instruct-GGUF/resolve/main/"
    main_stem = f"Qwen3VL-{size_label}-Instruct-Q4_K_M"
    mmproj_file = f"mmproj-Qwen3VL-{size_label}-Instruct-F16.gguf"
    return {
        "handler": "llama_cpp_vision",
        "location": "local",
        "provider": "qwen",
        "display_name": f"Qwen3-VL {parameters} Instruct (local vision fallback)",
        "capabilities": ["reasoning", "vision"],
        "features": ["gpu_acceleration", "quantization"],
        "context_window": 262144,
        "max_output_tokens": 4096,
        "download_url": f"{repo_url}{main_stem}.gguf",
        "sha256": main_sha256,
        "companion_downloads": [
            {
                "file": mmproj_file,
                "download_url": f"{repo_url}{mmproj_file}",
            },
        ],
        "main_model_file": f"{main_stem}.gguf",
        "mmproj_file": mmproj_file,
        "chat_handler": "mtmd",
        "manual_install_required": False,
        "on_disk_name": main_stem,
        "size": total_size,
        "recommended_ram": recommended_ram,
        "visible": True,
        "display_order": display_order,
        "description": description,
    }


LOCAL_VISION_MODELS: Dict[str, Any] = {
    "Qwen-qwen3vl-2b-instruct-q4km": _qwen3_vl_instruct_entry(
        size_label="2B",
        main_sha256="089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae",
        parameters="2B",
        total_size="1.9GB",
        recommended_ram="8GB",
        display_order=48,
        description=(
            "Smallest local multimodal fallback for analyze_with_vision, for Macs with limited memory. "
            "Downloads Qwen's official Qwen3-VL 2B GGUF and its required mmproj companion file through "
            "Basil's model manager."
        ),
    ),
    "Qwen-qwen3vl-4b-instruct-q4km": _qwen3_vl_instruct_entry(
        size_label="4B",
        main_sha256="66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a",
        parameters="4B",
        total_size="3.3GB",
        recommended_ram="8GB",
        display_order=49,
        description=(
            "Lightweight local multimodal fallback for analyze_with_vision. "
            "Downloads Qwen's official Qwen3-VL 4B GGUF and its required mmproj companion file through "
            "Basil's model manager."
        ),
    ),
    "Qwen-qwen3vl-8b-instruct-q4km": _qwen3_vl_instruct_entry(
        size_label="8B",
        main_sha256="67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2",
        parameters="8B",
        total_size="6.2GB",
        recommended_ram="16GB",
        display_order=50,
        description=(
            "Default local multimodal fallback for analyze_with_vision when the agent model has no native "
            "vision. Downloads Qwen's official Qwen3-VL 8B GGUF and its required mmproj companion file "
            "through Basil's model manager."
        ),
    ),
    "Qwen-qwen3vl-32b-instruct-q4km": _qwen3_vl_instruct_entry(
        size_label="32B",
        main_sha256="5cf0136e721d6294718ec71fd8c93b17ab5dd4e2714d6079e83fa46571ad94c8",
        parameters="32B",
        total_size="21.0GB",
        recommended_ram="48GB",
        display_order=51,
        description=(
            "Higher-capacity local multimodal fallback for analyze_with_vision. "
            "Uses the same Qwen3-VL GGUF + mmproj loader path as the smaller sizes."
        ),
    ),
}


def local_vision_files_present(models_dir: Path, cfg: Dict[str, Any]) -> bool:
    """Return True if both main GGUF and mmproj exist under ``models_dir``."""
    main_name = cfg.get("main_model_file")
    mmproj_name = cfg.get("mmproj_file")
    if not main_name or not mmproj_name:
        return False
    main_path = models_dir / main_name
    mmproj_path = models_dir / mmproj_name
    return main_path.is_file() and mmproj_path.is_file()
