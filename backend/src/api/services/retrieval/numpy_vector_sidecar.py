"""Atomic, memory-mapped NumPy persistence for retrieval-vector generations."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np


class NumpyVectorSidecar:
    """Persist one exact float32 vector matrix per retrieval generation."""

    FORMAT = "numpy-float32-v1"

    def __init__(self, db_path: str, model: str) -> None:
        self.root = Path(db_path).parent / "retrieval" / self._key(model)
        self.model = model

    @staticmethod
    def _key(model: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "_" for char in model)

    @property
    def manifest_path(self) -> Path:
        return self.root / "current.json"

    def publish(
        self,
        generation_id: str,
        vectors: np.ndarray,
        dimension: int,
        count: int,
    ) -> None:
        """Atomically publish a validated vector generation and manifest."""
        if vectors.dtype != np.float32:
            raise ValueError("retrieval vectors must be float32")
        if vectors.shape != (count, dimension):
            raise ValueError("retrieval vector shape does not match generation metadata")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as temp_dir:
            temp = Path(temp_dir)
            vector_name = f"{generation_id}.npy"
            staged_vectors = temp / vector_name
            np.save(staged_vectors, vectors, allow_pickle=False)
            os.replace(staged_vectors, self.root / vector_name)
            manifest = {
                "format": self.FORMAT,
                "generation_id": generation_id,
                "model": self.model,
                "dimension": dimension,
                "document_count": count,
                "vector_file": vector_name,
            }
            staged_manifest = temp / "current.json"
            staged_manifest.write_text(json.dumps(manifest, sort_keys=True))
            os.replace(staged_manifest, self.manifest_path)

    def snapshot_current_manifest(self) -> Optional[bytes]:
        """Return the manifest bytes needed to restore the live generation."""
        try:
            return self.manifest_path.read_bytes()
        except FileNotFoundError:
            return None

    def restore_current_manifest(self, manifest: Optional[bytes]) -> None:
        """Restore the generation visible before a failed metadata commit."""
        if manifest is None:
            self.manifest_path.unlink(missing_ok=True)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as staged:
            staged.write(manifest)
            staged_path = Path(staged.name)
        os.replace(staged_path, self.manifest_path)

    def load(self, generation_id: str, dimension: int, count: int) -> Optional[np.ndarray]:
        """Load the current matrix as a read-only memory map when valid."""
        if count <= 0 or dimension <= 0 or not self.manifest_path.exists():
            return None
        try:
            manifest = json.loads(self.manifest_path.read_text())
            if (
                manifest["format"] != self.FORMAT
                or manifest["generation_id"] != generation_id
                or manifest["model"] != self.model
                or manifest["dimension"] != dimension
                or manifest["document_count"] != count
            ):
                return None
            vectors = np.load(
                self.root / manifest["vector_file"],
                mmap_mode="r",
                allow_pickle=False,
            )
            if vectors.dtype != np.float32 or vectors.shape != (count, dimension):
                return None
            return vectors
        except (OSError, ValueError, KeyError):
            return None

    def remove_current_generation(self) -> None:
        """Remove the current NumPy generation after an empty metadata commit."""
        if not self.manifest_path.exists():
            return
        try:
            manifest = json.loads(self.manifest_path.read_text())
            vector_file = manifest.get("vector_file")
            if vector_file:
                (self.root / vector_file).unlink(missing_ok=True)
            self.manifest_path.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            return

    def remove_legacy_faiss_generations(self) -> None:
        """Best-effort cleanup after a NumPy generation becomes current."""
        if not self.root.exists():
            return
        for path in self.root.glob("*.faiss"):
            try:
                path.unlink()
            except OSError:
                continue
