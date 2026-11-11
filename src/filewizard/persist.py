"""Atomic text writes for JSON/YAML state files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` atomically (WP-D2, F-11).

    Sequence: unique same-directory temp file (``mkstemp``) → write +
    ``fsync`` → ``replace`` → best-effort directory ``fsync``.

    Guarantees:
      - The previous file stays intact until the rename succeeds; a crash
        mid-write never yields a truncated destination.
      - The temp name is unique per write, so two concurrent writers of
        the same file cannot clobber each other's staging file (the old
        fixed ``<name>.tmp`` allowed exactly that).
      - On any failure the temp file is removed and the exception
        propagates — no silent stale content.
      - ``fsync`` of the file (and best-effort of the directory) makes
        the content and the rename durable across a power loss, not just
        a process crash.
      - The destination is always owner-only (``0o600``): state files
        hold user paths and review content. A preexisting file with a
        laxer mode (e.g. ``0666`` created by an old version or by hand)
        is tightened instead of preserved.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # Owner-only: state files hold user paths and review content. A
        # preexisting file with an excessive mode is tightened, not
        # preserved (R5 perms round: 0666 rewrite must not stay 0666).
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def ensure_private_dir(path: Path) -> None:
    """Tighten a state directory to owner-only (best-effort, E2/F-05b).

    Used for directories holding private material: the journal, the
    perception cache, displaced backups, logs. An OSError is swallowed —
    on filesystems without POSIX modes the files keep their creation
    modes rather than failing the whole pipeline.
    """
    try:
        current = path.stat().st_mode & 0o777
        if current != 0o700:
            os.chmod(path, 0o700)
    except OSError:
        pass


def ensure_private_file(path: Path) -> None:
    """Tighten a state file to owner-only (best-effort, E2)."""
    try:
        current = path.stat().st_mode & 0o777
        if current != 0o600:
            os.chmod(path, 0o600)
    except OSError:
        pass


_RUNTIME_RESET_NAMES = (
    "perception_cache",
    "review_queue.json",
    "review_queue.json.bak",
    "filewizard.log",
    "filewizard.log.1",
    "filewizard.log.2",
    "filewizard.log.3",
    "watch_state.json",
    "watch.lock",
)


def reset_runtime_paths(
    state_dir: Path, *, wipe_all: bool = False
) -> list[Path]:
    """Paths ``filewizard reset`` will delete (existing only).

    Default: cache, queue, logs, watch debounce/lock.
    ``wipe_all``: the whole state directory (journal, presets, config).
    """
    root = Path(state_dir).expanduser()
    if wipe_all:
        return [root] if root.exists() else []
    out: list[Path] = []
    for name in _RUNTIME_RESET_NAMES:
        path = root / name
        if path.exists():
            out.append(path)
    return out
