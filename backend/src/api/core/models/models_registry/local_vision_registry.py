"""
Local vision-capable models.

These entries are merged into the unified registry for capability discovery and
Settings > Models download management. Agent runtime availability checks remain
filesystem-only and never initiate downloads.
"""

from pathlib import Path
from typing import Any, Dict

LOCAL_VISION_MODELS: Dict[str, Any] = {
    "Qwen-qwen25vl-3b-instruct-q4km": {
        "handler": "llama_cpp_vision",
        "location": "local",
        "provider": "qwen",
        "display_name": "Qwen2.5-VL 3B Instruct Q4_K_M (local vision fallback)",
        "capabilities": ["reasoning", "vision"],
        "features": ["gpu_acceleration", "quantization"],
        "context_window": 32768,
        "max_output_tokens": 4096,
        "download_url": (
            "https://huggingface.co/llmware/qwen2.5-vl-3b-instruct-gguf/resolve/main/"
            "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
        ),
        "companion_downloads": [
            {
                "file": "mmproj-F16.gguf",
                "download_url": (
                    "https://huggingface.co/llmware/qwen2.5-vl-3b-instruct-gguf/resolve/main/"
                    "mmproj-F16.gguf"
                ),
            },
        ],
        "main_model_file": "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        "mmproj_file": "mmproj-F16.gguf",
        "chat_handler": "qwen25vl",
        "manual_install_required": False,
        "on_disk_name": "Qwen2.5-VL-3B-Instruct-Q4_K_M",
        "size": "1.93GB",
        "recommended_ram": "8GB",
        "visible": True,
        "display_order": 49,
        "description": (
            "Lightweight local multimodal fallback for analyze_with_vision. "
            "Downloads the main Qwen2.5-VL 3B GGUF and required mmproj companion "
            "file through Basil's model manager."
        ),
    },
    # Matches filenames produced by common Qwen2.5-VL GGUF conversions.
    "Qwen-qwen25vl-7b-instruct-q4k": {
        "handler": "llama_cpp_vision",
        "location": "local",
        "provider": "qwen",
        "display_name": "Qwen2.5-VL 7B Instruct (local vision fallback)",
        "capabilities": ["reasoning", "vision"],
        "features": ["gpu_acceleration", "quantization"],
        "context_window": 32768,
        "max_output_tokens": 4096,
        "download_url": (
            "https://huggingface.co/Mungert/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/"
            "Qwen2.5-VL-7B-Instruct-bf16-q4_k.gguf"
        ),
        "companion_downloads": [
            {
                "file": "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf",
                "download_url": (
                    "https://huggingface.co/Mungert/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/"
                    "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf"
                ),
            },
        ],
        "main_model_file": "Qwen2.5-VL-7B-Instruct-bf16-q4_k.gguf",
        "mmproj_file": "Qwen2.5-VL-7B-Instruct-mmproj-f16.gguf",
        "chat_handler": "qwen25vl",
        "manual_install_required": False,
        "on_disk_name": "Qwen2.5-VL-7B-Instruct-bf16-q4_k",
        "size": "4.3GB",
        "recommended_ram": "16GB",
        "visible": True,
        "display_order": 50,
        "description": (
            "Local multimodal fallback for analyze_with_vision when the agent "
            "model has no native vision. Downloads the main GGUF and required "
            "mmproj companion file through Basil's model manager."
        ),
    },
    "Qwen-qwen25vl-32b-instruct-q4km": {
        "handler": "llama_cpp_vision",
        "location": "local",
        "provider": "qwen",
        "display_name": "Qwen2.5-VL 32B Instruct Q4_K_M (local vision fallback)",
        "capabilities": ["reasoning", "vision"],
        "features": ["gpu_acceleration", "quantization"],
        "context_window": 128000,
        "max_output_tokens": 4096,
        "download_url": (
            "https://huggingface.co/ggml-org/Qwen2.5-VL-32B-Instruct-GGUF/resolve/main/"
            "Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf"
        ),
        "companion_downloads": [
            {
                "file": "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf",
                "download_url": (
                    "https://huggingface.co/ggml-org/Qwen2.5-VL-32B-Instruct-GGUF/resolve/main/"
                    "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf"
                ),
            },
        ],
        "main_model_file": "Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf",
        "mmproj_file": "mmproj-Qwen2.5-VL-32B-Instruct-f16.gguf",
        "chat_handler": "qwen25vl",
        "manual_install_required": False,
        "on_disk_name": "Qwen2.5-VL-32B-Instruct-Q4_K_M",
        "size": "19.9GB",
        "recommended_ram": "48GB",
        "visible": True,
        "display_order": 51,
        "description": (
            "Higher-capacity local multimodal fallback for analyze_with_vision. "
            "Uses the same Qwen2.5-VL GGUF + mmproj loader path as the 7B model."
        ),
    },
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
