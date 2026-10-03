"""Identity of a file at plan time, checked again before a move is trusted.

Files at most 64MiB also get a SHA-256. Larger files keep size, mtime,
device, and inode. A sampled hash is not used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .perception.cache import MAX_CACHE_FILE_BYTES, file_content_hash


@dataclass(frozen=True)
class FileIdentity:
    size: int
    mtime_ns: int
    device: int
    inode: int
    sha256: str | None


def capture_identity(path: Path) -> FileIdentity | None:
    """Stat the file and hash it when it is within the cache size cap."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        st = path.stat()
    except OSError:
        return None
    digest: str | None = None
    if 0 <= st.st_size <= MAX_CACHE_FILE_BYTES:
        try:
            digest = file_content_hash(path)
        except OSError:
            digest = None
    return FileIdentity(
        size=int(st.st_size),
        mtime_ns=int(st.st_mtime_ns),
        device=int(st.st_dev),
        inode=int(st.st_ino),
        sha256=digest,
    )


def identity_matches(path: Path, ident: FileIdentity) -> bool:
    """True when `path` is still the file described by `ident`."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        st = path.stat()
    except OSError:
        return False
    if int(st.st_size) != ident.size:
        return False
    if int(st.st_mtime_ns) != ident.mtime_ns:
        return False
    if int(st.st_dev) != ident.device or int(st.st_ino) != ident.inode:
        return False
    if ident.sha256 is None:
        return True
    try:
        return file_content_hash(path) == ident.sha256
    except OSError:
        return False


def content_matches(path: Path, *, size: int | None, sha256: str | None) -> bool:
    """True when destination bytes match a recorded hash, or size if no hash.

    A missing hash does not match: size alone is not identity.
    """
    if sha256 is None or size is None:
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        if path.stat().st_size != int(size):
            return False
        return file_content_hash(path) == sha256
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
