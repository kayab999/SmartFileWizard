"""Atomic text writes for JSON/YAML state files."""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` via a same-directory temp file, then ``Path.replace``.

    A crash mid-write leaves ``<name>.tmp`` and the previous file intact
    (POSIX replace is atomic on the same filesystem).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


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
