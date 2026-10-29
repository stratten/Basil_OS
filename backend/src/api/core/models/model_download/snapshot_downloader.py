"""Hugging Face repository snapshot download implementation."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from huggingface_hub import snapshot_download

from ...logging.api_logger import api_logger
from .callbacks import CustomHFCallback


def build_snapshot_patterns(
    model_id: str,
    model_cfg: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """Build handler-aware allow/ignore patterns for snapshot downloads."""
    handler = model_cfg.get("handler", "")
    if handler == "parakeet":
        shared_parakeet_files = [
            "nemo128.onnx",
            "vocab.txt",
            "config.json",
            "*.yaml",
            "*.yml",
            "*.model",
            "README.md",
        ]
        precision = (model_cfg.get("precision") or "").lower()
        if precision == "int8":
            snapshot_allow_patterns = [
                "encoder-model.int8.onnx",
                "decoder_joint-model.int8.onnx",
                *shared_parakeet_files,
            ]
        elif precision == "fp32":
            snapshot_allow_patterns = [
                "encoder-model.onnx",
                "encoder-model.onnx.data",
                "decoder_joint-model.onnx",
                *shared_parakeet_files,
            ]
        else:
            raise ValueError(
                f"Parakeet model entry '{model_id}' is missing the "
                f"required `precision` field (expected 'int8' or "
                f"'fp32'). Update its registry entry in "
                f"transcription_registry.py."
            )
        snapshot_ignore_patterns = [
            "*.bin",
            "*.safetensors",
            "*.h5",
            "*.msgpack",
            "*.ot",
            "*.pt",
            "*.pth",
        ]
    else:
        snapshot_allow_patterns = [
            "*.safetensors", "*.json", "*.txt", "tokenizer.model"
        ]
        snapshot_ignore_patterns = [
            "*.h5", "*.bin", "*.msgpack", "*.ot", "*fp32*"
        ]

    return snapshot_allow_patterns, snapshot_ignore_patterns


class SnapshotDownloader:
    """Download and copy Hugging Face repository snapshots."""

    def __init__(self, progress_tracker, progress_owner) -> None:
        self.progress_tracker = progress_tracker
        self.progress_owner = progress_owner

    async def update_progress(
        self,
        model_type: str,
        variant: str,
        progress: float,
        status: str = "downloading",
        metadata: Optional[dict] = None,
    ) -> None:
        await self.progress_owner._update_progress(
            model_type, variant, progress, status=status, metadata=metadata
        )

    async def download_snapshot_model(
        self,
        model_type: str,
        variant: str,
        model_id: str,
        model_info: Dict[str, Any],
        model_path: Path,
        snapshot_allow_patterns: List[str],
        snapshot_ignore_patterns: List[str],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Path:
        repo_url = model_info["repo"]["url"]
        repo_id = repo_url.replace("https://huggingface.co/", "")
        revision = model_info["repo"].get("revision", "main")
        self.progress_tracker._current_operations[model_id] = "preparing"
        await self.update_progress(
            model_type,
            variant,
            0.0,
            status="preparing",
            metadata={"message": "Preparing download..."},
        )
        api_logger.debug(f"Processing model from {repo_url} (revision: {revision})")

        if model_path.exists() and any(model_path.iterdir()):
            api_logger.debug("Model already exists in models directory")
            await self.update_progress(model_type, variant, 1.0, status="completed")
            return model_path

        try:
            api_logger.debug("Checking for model in Hugging Face cache...")
            await self.update_progress(
                model_type,
                variant,
                0.0,
                status="preparing",
                metadata={"message": "Checking cache..."},
            )
            main_event_loop = asyncio.get_event_loop()
            print(f"🔍 [TQDM_DEBUG] Creating CustomHFCallback for {model_id}", flush=True)
            print(f"🔍 [TQDM_DEBUG] Event loop id: {id(main_event_loop)}, running: {main_event_loop.is_running()}", flush=True)
            api_logger.warning(f"🔍 [TQDM_DEBUG] Creating CustomHFCallback for {model_id}")
            api_logger.warning(f"🔍 [TQDM_DEBUG] Event loop id: {id(main_event_loop)}, running: {main_event_loop.is_running()}")
            hf_callback = CustomHFCallback(model_type, variant, self.progress_owner, main_event_loop)
            print(f"🔍 [TQDM_DEBUG] CustomHFCallback created: {hf_callback}, id: {id(hf_callback)}", flush=True)
            api_logger.warning(f"🔍 [TQDM_DEBUG] CustomHFCallback created: {hf_callback}, id: {id(hf_callback)}")
            self.progress_tracker._current_operations[model_id] = "downloading"

            try:
                import huggingface_hub.utils.tqdm as hf_tqdm_module
                from huggingface_hub.utils import are_progress_bars_disabled, enable_progress_bars

                api_logger.info(f"📊 HF progress bars disabled state BEFORE: {are_progress_bars_disabled()}")
                print(f"📊 [PROGRESS_FIX] HF progress bars disabled BEFORE: {are_progress_bars_disabled()}", flush=True)

                enable_progress_bars()

                api_logger.info(f"📊 HF progress bars disabled state AFTER enable: {are_progress_bars_disabled()}")
                print(f"📊 [PROGRESS_FIX] HF progress bars disabled AFTER enable: {are_progress_bars_disabled()}", flush=True)

                tqdm = hf_tqdm_module.tqdm
                api_logger.info("✅ Using huggingface_hub.utils.tqdm for patching")
            except (ImportError, AttributeError) as e:
                api_logger.warning(f"Could not import huggingface_hub.utils.tqdm, falling back to tqdm.auto: {e}")
                from tqdm.auto import tqdm as tqdm_auto
                tqdm = tqdm_auto

            import threading
            if not hasattr(tqdm, '_lock'):
                tqdm._lock = threading.Lock()
                api_logger.info("🔧 [TQDM_FIX] Added missing _lock to tqdm class")

            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

            original_tqdm_init = tqdm.__init__

            def patched_tqdm_init(self, *args, **kwargs):
                kwargs["disable"] = False
                original_tqdm_init(self, *args, **kwargs)
                original_update = self.update

                def new_update(n=1):
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError(
                            "cancel_event set; aborting download via tqdm hook"
                        )
                    result = original_update(n)
                    try:
                        hf_callback(self.n, self.total, getattr(self, "desc", model_id))
                    except Exception as cb_exc:
                        api_logger.error(f"[PROGRESS_PATCH] Error in patched update: {cb_exc}")
                    return result

                self.update = new_update

            tqdm.__init__ = patched_tqdm_init

            try:
                try:
                    def _run_snapshot():
                        return snapshot_download(
                            repo_id=repo_id,
                            revision=revision,
                            allow_patterns=snapshot_allow_patterns,
                            ignore_patterns=snapshot_ignore_patterns,
                            local_files_only=False,
                            resume_download=True,
                            force_download=False,
                            token=None,
                            tqdm_class=tqdm,
                        )

                    snapshot_dir = await asyncio.to_thread(_run_snapshot)
                    api_logger.debug(f"Download completed to: {snapshot_dir}")
                    self.progress_tracker._current_operations[model_id] = "copying"
                    await self.update_progress(
                        model_type,
                        variant,
                        0.95,
                        status="copying",
                        metadata={"message": "Copying files..."},
                    )

                    if not model_path.exists():
                        model_path.mkdir(parents=True, exist_ok=True)

                    if model_path.exists() and any(model_path.iterdir()):
                        api_logger.debug("Removing existing files from model directory")
                        shutil.rmtree(model_path)
                        model_path.mkdir(parents=True, exist_ok=True)

                    usage_before = shutil.disk_usage(str(model_path.parent))
                    api_logger.info(f"[DISK_USAGE][BEFORE_COPY] Total: {usage_before.total}, Used: {usage_before.used}, Free: {usage_before.free} bytes on {model_path.parent}")
                    api_logger.debug(f"Copying files from {snapshot_dir} to {model_path}")
                    total_size = sum(f.stat().st_size for f in Path(snapshot_dir).rglob("*") if f.is_file())
                    copied_size = 0
                    for src in Path(snapshot_dir).rglob("*"):
                        if src.is_file():
                            dst = model_path / src.relative_to(snapshot_dir)
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            file_size = src.stat().st_size
                            api_logger.debug(f"Copying {src.name} ({file_size} bytes)")
                            shutil.copy2(src, dst)
                            copied_size += file_size
                            copy_progress = 0.95 + (copied_size / total_size * 0.05 if total_size > 0 else 0)
                            await self.update_progress(
                                model_type,
                                variant,
                                copy_progress,
                                status="copying",
                                metadata={"message": f"Copying {src.name}..."},
                            )
                    usage_after = shutil.disk_usage(str(model_path.parent))
                    api_logger.info(f"[DISK_USAGE][AFTER_COPY] Total: {usage_after.total}, Used: {usage_after.used}, Free: {usage_after.free} bytes on {model_path.parent}")

                    marker_file = model_path / ".downloaded"
                    with open(marker_file, "w") as f:
                        f.write(f"Downloaded from {repo_url} at revision {revision}")

                    self.progress_tracker._current_operations[model_id] = "completed"
                    await self.update_progress(
                        model_type,
                        variant,
                        1.0,
                        status="completed",
                        metadata={"message": "Download complete"},
                    )

                except asyncio.CancelledError:
                    api_logger.info(f"[CANCEL_DEBUG] Download of {model_id} explicitly caught asyncio.CancelledError in snapshot_download/copying try block.")
                    self.progress_tracker._current_operations[model_id] = "user_canceled"
                    await self.update_progress(
                        model_type,
                        variant,
                        self.progress_tracker._progress.get(model_id, 0.0),
                        status="user_canceled",
                        metadata={"message": "Download canceled by user (in CancelledError block)."},
                    )
                    raise
            finally:
                tqdm.__init__ = original_tqdm_init

            return model_path

        except Exception as e:
            if "local_files_only" in str(e):
                api_logger.debug("Model not in cache, starting download...")
            else:
                raise

        return model_path
