"""No-overwrite move primitives (ADR-0005 invariants 8/9).

Every publication is atomic: ``renameat2(RENAME_NOREPLACE)`` or, where it
is unavailable, ``link(2)`` (atomic EEXIST) followed by unlinking the
staging/source link. Cross-filesystem copies are staged under a unique
temporary name in the destination directory and are published *without*
a placeholder. No path in this module uses ``stat(dst)`` followed by a
plain ``rename()`` as a no-overwrite guarantee.

Fail-closed: if no atomic no-replace primitive is available, the move
raises and the source is retained. Cross-filesystem copying preserves
mode, executable bit, timestamps and platform-supported extended
attributes via ``copy2`` (ownership cannot normally be preserved by an
unprivileged process; ACLs beyond POSIX xattr support are not claimed).
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import tempfile
from pathlib import Path

RENAME_NOREPLACE = 1 << 0
_AT_FDCWD = -100

_libc = None


class DestinationExistsError(OSError):
    """The destination exists (or appeared concurrently); nothing moved."""


def _libc_renameat2():
    global _libc
    if os.name != "posix":
        raise NotImplementedError
    if _libc is None:
        try:
            _libc = ctypes.CDLL(None, use_errno=True)
        except OSError as exc:  # pragma: no cover - no libc at all
            raise NotImplementedError from exc
    fn = getattr(_libc, "renameat2", None)
    if fn is None:
        raise NotImplementedError
    return fn


def _try_renameat2_noreplace(src: Path, dst: Path) -> None:
    """Atomic no-replace rename; raises as documented or NotImplementedError."""
    fn = _libc_renameat2()
    res = fn(
        _AT_FDCWD,
        os.fsencode(str(src)),
        _AT_FDCWD,
        os.fsencode(str(dst)),
        RENAME_NOREPLACE,
    )
    if res != 0:
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise NotImplementedError
        if code == errno.ENOENT:
            raise FileNotFoundError(code, os.strerror(code), str(src))
        if code == errno.EEXIST:
            raise DestinationExistsError(
                errno.EEXIST, "destination exists", str(dst)
            )
        raise OSError(code, os.strerror(code), str(src), None, str(dst))


def _publish_noreplace(staging: Path, dst: Path) -> None:
    """Atomically publish a same-filesystem staging file without replacement."""
    try:
        _try_renameat2_noreplace(staging, dst)
        return
    except NotImplementedError:
        pass
    except OSError as exc:
        if isinstance(exc, DestinationExistsError):
            raise
        if exc.errno == errno.ENOENT:
            raise
        # Other kernel errors are handled by the portable link path.
    try:
        os.link(staging, dst, follow_symlinks=False)
    except FileExistsError as exc:
        raise DestinationExistsError(
            errno.EEXIST, "destination exists", str(dst)
        ) from exc
    except OSError:
        # No safe no-replace publication on this filesystem: fail closed.
        raise
    os.unlink(staging)


def _same_fs(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def fsync_path(path: Path) -> None:
    """Best-effort fsync of a file (durability aid, not a guarantee)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory entry (POSIX only)."""
    if os.name != "posix":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _move_cross_fs(src: Path, dst: Path) -> None:
    """Verified EXDEV move with no placeholder and atomic publication.

    Source identity is captured before the copy and compared both to the
    staging copy and to a fresh capture immediately before unlinking the
    source. A changing source aborts the move and keeps the original.
    """
    from .identity import capture_identity
    from .perception.cache import MAX_CACHE_FILE_BYTES

    dst.parent.mkdir(parents=True, exist_ok=True)
    before = capture_identity(src)
    if before is None:
        raise FileNotFoundError(errno.ENOENT, "source not found", str(src))
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{dst.name}.fwtmp-", dir=str(dst.parent)
        )
        os.close(fd)
        tmp = Path(tmp_name)
        # copy2 preserves mode/timestamps and supported extended metadata.
        shutil.copy2(src, tmp_name)
        fsync_path(tmp)
        copied = capture_identity(tmp)
        if copied is None or copied.size != before.size:
            raise OSError(errno.EIO, "cross-fs copy size mismatch", str(src))
        if before.sha256 is not None and copied.sha256 != before.sha256:
            raise OSError(errno.EIO, "cross-fs copy content mismatch", str(src))
        after = capture_identity(src)
        if (
            after is None
            or after.size != before.size
            or after.device != before.device
            or after.inode != before.inode
            or after.mtime_ns != before.mtime_ns
            or (before.sha256 is not None and after.sha256 != before.sha256)
        ):
            raise OSError(
                errno.EIO,
                "source changed during cross-fs copy; original retained",
                str(src),
            )
        # The destination was never reserved. Publication can only create
        # a new name or fail with DestinationExistsError; foreign files,
        # symlinks and substituted placeholders are never overwritten.
        _publish_noreplace(tmp, dst)
        tmp_name = None
        fsync_dir(dst.parent)
        if before.size > MAX_CACHE_FILE_BYTES and before.sha256 is None:
            # Metadata-only source-continuity evidence for large files.
            # This is deliberately not upgraded to a content guarantee.
            pass
    except BaseException:
        _cleanup(tmp_name)
        raise
    os.unlink(src)
    fsync_dir(src.parent)


def _cleanup(tmp_name: str | None) -> None:
    if tmp_name:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def move_noreplace(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst``; raise instead of overwriting ``dst``.

    Raises:
        DestinationExistsError: ``dst`` exists now or appeared concurrently.
        FileNotFoundError: ``src`` vanished.
        OSError: the move failed for another reason (source untouched).
        NotImplementedError: no no-replace strategy on this platform and
            filesystem combination.
    """
    try:
        _try_renameat2_noreplace(src, dst)
        fsync_dir(dst.parent)
        return
    except NotImplementedError:
        pass
    except OSError as exc:
        if isinstance(exc, DestinationExistsError):
            raise
        if exc.errno == errno.ENOENT:
            raise
        # Other renameat2 errors: try the portable fallback below.
    if _same_fs(src, dst.parent):
        try:
            os.link(src, dst, follow_symlinks=False)
        except FileExistsError as exc:
            raise DestinationExistsError(
                errno.EEXIST, "destination exists", str(dst)
            ) from exc
        except OSError:
            # link denied (fs/permission): fail closed, keep both files.
            raise
        os.unlink(src)
        fsync_dir(dst.parent)
        return
    _move_cross_fs(src, dst)


def move_noreplace_unique(src: Path, dst: Path) -> Path:
    """Atomically move to ``dst`` or the first available ``stem_N`` name.

    Unlike ``append_unique()`` + ``shutil.move()``, this never creates a
    zero-byte placeholder and never overwrites a reservation. Each name
    is attempted with the same no-replace primitive.
    """
    candidates = [dst]
    candidates.extend(
        dst.with_name(f"{dst.stem}_{i}{dst.suffix}") for i in range(1, 10_000)
    )
    for candidate in candidates:
        try:
            move_noreplace(src, candidate)
        except DestinationExistsError:
            continue
        return candidate
    raise FileExistsError(f"Could not find a unique destination for {dst}")
