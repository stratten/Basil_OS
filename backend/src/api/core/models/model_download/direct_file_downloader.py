"""Direct-file download implementation behind ``ModelDownloader``.

Handles registry entries with a direct ``download_url`` such as GGUF files,
including Hugging Face single-file downloads, generic HTTP downloads,
checksum verification, and companion files.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

from ...logging.api_logger import api_logger
from .artifacts import ModelArtifactStore
from .callbacks import CustomHFCallback


class DirectFileDownloader:
    """Download direct-file model artifacts into the models directory."""

    def __init__(
        self,
        models_dir: Path,
        artifacts: ModelArtifactStore,
        progress_tracker,
        progress_owner,
    ) -> None:
        self.models_dir = models_dir
        self.artifacts = artifacts
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

    async def download_companion_files(
        self,
        model_type: str,
        variant: str,
        model_cfg: Dict[str, Any],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Download any required companion files into the models directory."""
        companions = self.artifacts.get_companion_downloads(model_cfg)
        if not companions:
            return

        from huggingface_hub import hf_hub_download

        self.models_dir.mkdir(parents=True, exist_ok=True)
        total_companions = len(companions)
        for index, companion in enumerate(companions, start=1):
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError("cancel_event set; aborting companion download")

            filename = companion["file"]
            url = companion["download_url"]
            destination = self.models_dir / filename
            if destination.exists():
                api_logger.info(f"Companion file already exists: {destination}")
                continue

            await self.update_progress(
                model_type,
                variant,
                0.95,
                status="downloading",
                metadata={
                    "message": f"Downloading companion file {index}/{total_companions}: {filename}",
                    "current_file": filename,
                    "files_completed": index - 1,
                    "total_files": total_companions + 1,
                },
            )

            if "huggingface.co" in url and "/resolve/" in url:
                url_parts = url.replace("https://huggingface.co/", "").split("/resolve/")
                repo_id = url_parts[0]
                revision_and_file = url_parts[1].split("/", 1)
                revision = revision_and_file[0] if len(revision_and_file) > 1 else "main"
                hf_filename = revision_and_file[1] if len(revision_and_file) > 1 else revision_and_file[0]

                def download_file():
                    return hf_hub_download(
                        repo_id=repo_id,
                        filename=hf_filename,
                        revision=revision,
                        local_files_only=False,
                        force_download=False,
                        resume_download=True,
                    )

                downloaded_path = await asyncio.to_thread(download_file)
                shutil.copy2(downloaded_path, destination)
            else:
                timeout = aiohttp.ClientTimeout(total=3600)
                chunk_size = 1024 * 1024
                temp_file = destination.with_suffix(destination.suffix + ".tmp")
                try:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(url) as response:
                            if response.status != 200:
                                raise Exception(f"HTTP {response.status}: {response.reason}")
                            with open(temp_file, "wb") as f:
                                async for chunk in response.content.iter_chunked(chunk_size):
                                    if cancel_event is not None and cancel_event.is_set():
                                        raise asyncio.CancelledError(
                                            "cancel_event set; aborting companion download"
                                        )
                                    if chunk:
                                        f.write(chunk)
                    temp_file.rename(destination)
                except Exception:
                    if temp_file.exists():
                        temp_file.unlink()
                    raise

            api_logger.info(f"Downloaded companion file to {destination}")

    @staticmethod
    def _parse_huggingface_url(url: str) -> tuple[str, str, str]:
        prefix = "https://huggingface.co/"
        if not url.startswith(prefix) or "/resolve/" not in url:
            raise ValueError(f"Artifact manifest requires a Hugging Face resolve URL: {url}")
        repo_id, revision_and_file = url[len(prefix) :].split("/resolve/", 1)
        revision, filename = revision_and_file.split("/", 1)
        return repo_id, revision, filename

    async def _download_manifest_item(
        self,
        item: Dict[str, Any],
        destination: Path,
        cancel_event: Optional[asyncio.Event],
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError("cancel_event set before artifact download")
        repo_id, revision, filename = self._parse_huggingface_url(str(item["download_url"]))
        from huggingface_hub import hf_hub_download

        def download_file() -> str:
            return hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                revision=revision,
                local_files_only=False,
                force_download=False,
                resume_download=True,
            )

        downloaded_path = Path(await asyncio.to_thread(download_file))
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError("cancel_event set after artifact download")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(downloaded_path, destination)
        expected_size = item.get("size_bytes")
        if isinstance(expected_size, int) and destination.stat().st_size != expected_size:
            raise ValueError(
                f"Artifact size mismatch for {item['file']}: "
                f"expected {expected_size}, got {destination.stat().st_size}"
            )
        expected_sha256 = item.get("sha256")
        if isinstance(expected_sha256, str) and expected_sha256:
            if not await self.verify_checksum(destination, expected_sha256):
                raise ValueError(f"SHA256 checksum verification failed for {item['file']}")

    async def download_artifact_manifest(
        self,
        model_type: str,
        variant: str,
        model_cfg: Dict[str, Any],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Path:
        artifacts = model_cfg.get("artifact_files")
        root_name = model_cfg.get("artifact_root")
        primary_name = model_cfg.get("primary_artifact")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("Artifact manifest is missing artifact_files")
        if not isinstance(root_name, str) or not isinstance(primary_name, str):
            raise ValueError("Artifact manifest requires artifact_root and primary_artifact")
        try:
            safe_root_name = self.artifacts._safe_relative_artifact_path(root_name)
            safe_primary_name = self.artifacts._safe_relative_artifact_path(primary_name)
        except ValueError as exc:
            raise ValueError(
                f"Invalid artifact manifest root or primary artifact: "
                f"{root_name!r}, {primary_name!r}"
            ) from exc

        final_root = self.models_dir / safe_root_name
        primary_path = final_root / safe_primary_name
        if self.artifacts.artifact_manifest_is_complete(model_cfg, self.models_dir):
            await self.update_progress(
                model_type,
                variant,
                1.0,
                status="completed",
                metadata={
                    "message": "Model artifact manifest is already installed",
                    "current_file": primary_name,
                    "files_completed": len(artifacts),
                    "total_files": len(artifacts),
                },
            )
            return primary_path

        staging_root = self.models_dir / f".{root_name}.downloading-{uuid.uuid4().hex}"
        total_bytes = sum(
            item.get("size_bytes", 0) for item in artifacts if isinstance(item, dict)
        )
        completed_bytes = 0
        try:
            for index, item in enumerate(artifacts, start=1):
                if not isinstance(item, dict):
                    raise ValueError("Artifact manifest contains a non-object item")
                filename = str(item.get("file") or "")
                try:
                    safe_filename = self.artifacts._safe_relative_artifact_path(filename)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid artifact manifest filename: {filename!r}"
                    ) from exc
                await self.update_progress(
                    model_type,
                    variant,
                    completed_bytes / total_bytes if total_bytes else 0.0,
                    status="downloading",
                    metadata={
                        "message": f"Downloading artifact {index} of {len(artifacts)}: {filename}",
                        "current_file": filename,
                        "files_completed": index - 1,
                        "total_files": len(artifacts),
                    },
                )
                await self._download_manifest_item(
                    item,
                    staging_root / safe_filename,
                    cancel_event,
                )
                completed_bytes += int(item.get("size_bytes") or 0)
                await self.update_progress(
                    model_type,
                    variant,
                    completed_bytes / total_bytes if total_bytes else index / len(artifacts),
                    status="downloading",
                    metadata={
                        "message": f"Verified artifact {index} of {len(artifacts)}: {filename}",
                        "current_file": filename,
                        "files_completed": index,
                        "total_files": len(artifacts),
                    },
                )

            missing_staged_files = [
                str(item.get("file"))
                for item in artifacts
                if not (staging_root / str(item.get("file") or "")).is_file()
            ]
            if missing_staged_files:
                raise ValueError("Staged artifact manifest is incomplete after download")
            if final_root.exists():
                shutil.rmtree(final_root)
            staging_root.rename(final_root)
            await self.update_progress(
                model_type,
                variant,
                1.0,
                status="completed",
                metadata={
                    "message": "All model artifacts downloaded and verified",
                    "current_file": primary_name,
                    "files_completed": len(artifacts),
                    "total_files": len(artifacts),
                },
            )
            return primary_path
        except BaseException:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

    async def download_direct_file(
        self,
        model_type: str,
        variant: str,
        model_id: str,
        model_cfg: Dict[str, Any],
        model_info: Dict[str, Any],
        model_path: Path,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Path:
        """Download a direct file entry and any required companion files."""
        api_logger.info(f"Handling direct file download for {model_type}-{variant}")
        if model_cfg.get("artifact_files"):
            return await self.download_artifact_manifest(
                model_type,
                variant,
                model_cfg,
                cancel_event=cancel_event,
            )

        if model_path.exists():
            api_logger.debug(f"Model file already exists: {model_path}")
            await self.download_companion_files(
                model_type,
                variant,
                model_cfg,
                cancel_event=cancel_event,
            )
            await self.update_progress(model_type, variant, 1.0, status="completed")
            return model_path

        url = model_info["url"]
        api_logger.info(f"Starting direct download from: {url}")
        await self.update_progress(
            model_type,
            variant,
            0.05,
            status="downloading",
            metadata={"message": "Starting file download..."},
        )

        if "huggingface.co" in url and "/resolve/" in url:
            return await self._download_huggingface_file(
                model_type,
                variant,
                model_id,
                model_cfg,
                model_path,
                url,
                cancel_event=cancel_event,
            )

        return await self._download_http_file(
            model_type,
            variant,
            model_cfg,
            model_info,
            model_path,
            url,
            cancel_event=cancel_event,
        )

    async def _download_huggingface_file(
        self,
        model_type: str,
        variant: str,
        model_id: str,
        model_cfg: Dict[str, Any],
        model_path: Path,
        url: str,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Path:
        url_parts = url.replace("https://huggingface.co/", "").split("/resolve/")
        repo_id = url_parts[0]
        revision_and_file = url_parts[1].split("/", 1)
        revision = revision_and_file[0] if len(revision_and_file) > 1 else "main"
        filename = revision_and_file[1] if len(revision_and_file) > 1 else revision_and_file[0]

        api_logger.info(f"Parsed HuggingFace URL: repo_id={repo_id}, filename={filename}, revision={revision}")

        try:
            from huggingface_hub import hf_hub_download
            from tqdm import tqdm as _tqdm_base

            await self.update_progress(
                model_type,
                variant,
                0.02,
                status="downloading",
                metadata={"message": f"Downloading {filename}..."},
            )

            main_event_loop = asyncio.get_event_loop()
            hf_callback = CustomHFCallback(model_type, variant, self.progress_owner, main_event_loop)
            self.progress_tracker._current_operations[model_id] = "downloading"

            original_tqdm_init = _tqdm_base.__init__

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
                        hf_callback(self.n, self.total, getattr(self, "desc", filename))
                    except Exception as cb_exc:
                        api_logger.error(f"[PROGRESS_PATCH] Error in patched update: {cb_exc}")
                    return result

                self.update = new_update

            _tqdm_base.__init__ = patched_tqdm_init

            try:
                def download_file():
                    return hf_hub_download(
                        repo_id=repo_id,
                        filename=filename,
                        revision=revision,
                        local_files_only=False,
                        force_download=False,
                        resume_download=True,
                    )

                api_logger.info(f"Downloading {filename} from {repo_id}...")
                downloaded_path = await asyncio.to_thread(download_file)
                api_logger.info(f"Downloaded to cache: {downloaded_path}")

                await self.update_progress(
                    model_type,
                    variant,
                    0.95,
                    status="copying",
                    metadata={"message": "Copying to models directory..."},
                )

                model_path.parent.mkdir(parents=True, exist_ok=True)
                api_logger.info(f"Copying from {downloaded_path} to {model_path}")
                shutil.copy2(downloaded_path, model_path)

                api_logger.info(f"Successfully downloaded {model_type}-{variant} to {model_path}")
                await self.download_companion_files(
                    model_type,
                    variant,
                    model_cfg,
                    cancel_event=cancel_event,
                )
                await self.update_progress(
                    model_type,
                    variant,
                    1.0,
                    status="completed",
                    metadata={"message": "Download complete"},
                )

                return model_path
            finally:
                _tqdm_base.__init__ = original_tqdm_init

        except Exception as e:
            api_logger.error(f"Error downloading with HuggingFace Hub: {e}")
            raise

    async def _download_http_file(
        self,
        model_type: str,
        variant: str,
        model_cfg: Dict[str, Any],
        model_info: Dict[str, Any],
        model_path: Path,
        url: str,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Path:
        api_logger.info("Using fallback download method for non-HuggingFace URL")
        expected_sha256 = model_info.get("sha256")

        timeout = aiohttp.ClientTimeout(total=3600)
        chunk_size = 1024 * 1024

        import ssl

        ssl_context = ssl.create_default_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)

        temp_file = model_path.with_suffix(model_path.suffix + ".tmp")
        temp_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                api_logger.info(f"Making HTTP request to {url}")
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")

                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    api_logger.info(f"Total file size: {total_size / (1024*1024):.2f} MB")

                    with open(temp_file, "wb") as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)

                                if total_size > 0:
                                    progress = min(0.95 * downloaded / total_size, 0.95)
                                    await self.update_progress(
                                        model_type,
                                        variant,
                                        progress,
                                        status="downloading",
                                        metadata={
                                            "message": f"Downloaded {downloaded / (1024*1024):.1f} / {total_size / (1024*1024):.1f} MB",
                                            "total_downloaded": downloaded,
                                            "total_size": total_size,
                                        },
                                    )

            api_logger.info("Download completed, verifying file integrity...")
            await self.update_progress(
                model_type,
                variant,
                0.95,
                status="verifying",
                metadata={"message": "Verifying file integrity..."},
            )

            actual_size = temp_file.stat().st_size
            if total_size > 0 and actual_size != total_size:
                raise Exception(f"File size mismatch: expected {total_size}, got {actual_size}")

            if expected_sha256:
                api_logger.info("Verifying SHA256 checksum...")
                if not await self.verify_checksum(temp_file, expected_sha256):
                    raise Exception("SHA256 checksum verification failed")

            api_logger.info(f"Moving file from {temp_file} to {model_path}")
            temp_file.rename(model_path)

            api_logger.info(f"Successfully downloaded {model_type}-{variant} to {model_path}")
            await self.download_companion_files(
                model_type,
                variant,
                model_cfg,
                cancel_event=cancel_event,
            )
            await self.update_progress(
                model_type,
                variant,
                1.0,
                status="completed",
                metadata={"message": "Download complete"},
            )

            return model_path

        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            api_logger.error(f"Error downloading {model_type}-{variant}: {e}")
            raise

    @staticmethod
    async def verify_checksum(file_path: Path, expected_sha256: str) -> bool:
        """Verify the SHA256 checksum of a downloaded file."""
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest() == expected_sha256
