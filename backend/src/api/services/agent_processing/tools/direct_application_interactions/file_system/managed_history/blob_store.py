"""Content-addressed local blob store for managed file-history snapshots."""

from __future__ import annotations

import os
import uuid
from hashlib import sha256
from pathlib import Path


class ManagedHistoryBlobIntegrityError(RuntimeError):
    """Raised when a stored blob's bytes no longer match its content address."""


class ManagedHistoryBlobMissingError(RuntimeError):
    """Raised when a referenced blob cannot be found on disk."""


class ManagedHistoryBlobStore:
    """Store and retrieve immutable, SHA-256-addressed snapshot blobs."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        return self._root / digest[:2] / digest

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, content: bytes) -> tuple[str, int]:
        """Persist ``content`` and return ``(sha256_hex_digest, byte_size)``.

        Idempotent: if a blob with the same digest already exists, it is
        verified rather than rewritten.
        """
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        if target.is_file():
            self._verify(target, digest)
            return digest, len(content)

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.write-{os.getpid()}-{uuid.uuid4().hex}"
        try:
            with temporary.open("xb") as destination:
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return digest, len(content)

    def get(self, digest: str) -> bytes:
        target = self.path_for(digest)
        if not target.is_file():
            raise ManagedHistoryBlobMissingError(
                f"Managed history blob {digest!r} is missing from the blob store."
            )
        content = target.read_bytes()
        self._verify(target, digest, content=content)
        return content

    def delete(self, digest: str) -> None:
        self.path_for(digest).unlink(missing_ok=True)

    @staticmethod
    def _verify(target: Path, digest: str, *, content: bytes | None = None) -> None:
        actual = content if content is not None else target.read_bytes()
        if sha256(actual).hexdigest() != digest:
            raise ManagedHistoryBlobIntegrityError(
                f"Managed history blob at {target} does not match its content address "
                f"{digest!r}; the file is corrupt."
            )
