"""Size-guarded read access to ZIP-based document packages (Office Open XML and iWork)."""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from typing import List, Optional

from .models import DocumentReadLimits, DocumentReadError, STATUS_ENCRYPTED, STATUS_ERROR, STATUS_TOO_LARGE

_NATURAL_SPLIT = re.compile(r"(\d+)")
_XML_SUFFIXES = (".xml", ".rels")


def natural_key(name: str) -> List[object]:
    """Sort key that orders ``slide2.xml`` before ``slide10.xml``."""
    return [int(part) if part.isdigit() else part for part in _NATURAL_SPLIT.split(name)]


class ArchiveGuard:
    """Opens a package from bytes and refuses members that are encrypted, oversized or declare XML entities."""

    def __init__(self, data: bytes, limits: DocumentReadLimits) -> None:
        try:
            self._archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError, EOFError) as error:
            raise DocumentReadError(STATUS_ERROR, "The file is not a valid document package.") from error
        infos = self._archive.infolist()
        if len(infos) > limits.max_archive_members:
            self._archive.close()
            raise DocumentReadError(STATUS_TOO_LARGE, "The document package holds too many parts to read.")
        self._limits = limits
        self._names = [info.filename for info in infos]
        self._name_set = set(self._names)
        self._lowered = {name.lower(): name for name in self._names}
        self._total = 0

    def __enter__(self) -> "ArchiveGuard":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._archive.close()

    def names(self) -> List[str]:
        return list(self._names)

    def has(self, name: str) -> bool:
        return name in self._name_set

    def find_case_insensitive(self, name: str) -> Optional[str]:
        return self._lowered.get(name.lower())

    def read(self, name: str) -> Optional[bytes]:
        """Bytes of one member, ``None`` when it does not exist; raises ``DocumentReadError`` for unsafe members."""
        if name not in self._name_set:
            return None
        info = self._archive.getinfo(name)
        if info.flag_bits & 0x1:
            raise DocumentReadError(STATUS_ENCRYPTED, "The document package is encrypted.")
        if (
            info.file_size > self._limits.max_member_bytes
            or self._total + info.file_size > self._limits.max_total_uncompressed_bytes
        ):
            raise DocumentReadError(STATUS_TOO_LARGE, "The document expands past the size limit.")
        try:
            with self._archive.open(info) as handle:
                data = handle.read(info.file_size + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as error:
            raise DocumentReadError(STATUS_ERROR, "A part of the document package could not be decompressed.") from error
        self._total += len(data)
        if name.lower().endswith(_XML_SUFFIXES) and b"<!entity" in data[:8192].lower():
            raise DocumentReadError(STATUS_ERROR, "The document declares XML entities and was not read.")
        return data
