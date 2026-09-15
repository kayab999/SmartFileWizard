from __future__ import annotations

import os
import time
import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from .cancel import CancelToken
from .executor import Executor, PlannedOperation
from .journal import Journal
from .models import RuleSet
from .pipeline import (
    RulesLoadError,
    default_extractors,
    load_ruleset,
    plan_operations,
)
from .persist import atomic_write_text
from .presets import PresetError, ensure_builtin_presets, load_preset
from .scanner import iter_files


def interruptible_sleep(
    seconds: float,
    cancel: CancelToken | None = None,
    step: float = 0.25,
) -> None:
    """Sleep up to `seconds`, returning early if cancel is set (H5)."""
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        if cancel is not None and cancel.is_cancelled():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(step, remaining))


class WatchError(Exception):
    """Raised for invalid watch configuration or rule resolution."""


class WatcherLockError(WatchError):
    """Raised when another watcher already holds the pid lock."""


def default_state_dir() -> Path:
    return Path("~/.local/share/filewizard").expanduser()


@dataclass(frozen=True)
class WatchConfig:
    """Configuration for one watch tick or polling loop (0.6.x)."""

    source: Path
    preset: str | None = None
    rules: Path | None = None
    dry_run: bool = True
    state_dir: Path = field(default_factory=default_state_dir)
    limit: int | None = None
    profile: str | None = None
    ocr: bool = False
    vision: bool = False
    agent_features: Path | None = None

    def __post_init__(self) -> None:
        if bool(self.preset) == bool(self.rules):
            raise WatchError(
                "Specify exactly one of preset=<name> or rules=<path>."
            )


def _load_ruleset(cfg: WatchConfig, state_dir: Path) -> RuleSet:
    if cfg.preset:
        try:
            return load_preset(cfg.preset, state_dir)
        except (PresetError, RulesLoadError) as exc:
            raise WatchError(str(exc)) from exc
    try:
        return load_ruleset(cfg.rules)  # type: ignore[arg-type]
    except RulesLoadError as exc:
        raise WatchError(str(exc)) from exc


def watch_once(
    cfg: WatchConfig,
    *,
    cancel: CancelToken | None = None,
    only_paths: set[Path] | None = None,
    acquire_lock: bool = True,
) -> tuple[list[PlannedOperation], int]:
    """
    Run a single watch tick: scan `source`, plan rules (and apply if not
    dry-run), using the same journal + dry-run contract as `run` (I1).

    only_paths: restrict planning to this subset of files (used by the
    polling loop debounce to skip untouched files).

    acquire_lock: take ``watch.lock`` (GUI tick / CLI once). The polling
    loop already holds the lock and must pass False.

    Returns (operations, scanned). Never mutates the filesystem unless
    cfg.dry_run is False.
    """
    state_dir = cfg.state_dir.expanduser().resolve()
    if acquire_lock:
        with watcher_lock(state_dir):
            return _watch_once_body(
                cfg, state_dir, cancel=cancel, only_paths=only_paths
            )
    return _watch_once_body(cfg, state_dir, cancel=cancel, only_paths=only_paths)


def _watch_once_body(
    cfg: WatchConfig,
    state_dir: Path,
    *,
    cancel: CancelToken | None = None,
    only_paths: set[Path] | None = None,
) -> tuple[list[PlannedOperation], int]:
    ensure_builtin_presets(state_dir)

    ruleset = _load_ruleset(cfg, state_dir)

    try:
        extractors = default_extractors(
            ocr=cfg.ocr,
            vision=cfg.vision,
            profile=cfg.profile,
            state_dir=state_dir,
            agent_features=cfg.agent_features,
        )
    except Exception as exc:
        from .perception.inject import AgentFeaturesError

        if isinstance(exc, AgentFeaturesError):
            raise WatchError(str(exc)) from exc
        raise

    with Journal(state_dir / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=cfg.dry_run)
        operations, scanned = plan_operations(
            source=cfg.source,
            rules=ruleset,
            executor=executor,
            extractors=extractors,
            limit=cfg.limit,
            only_paths=only_paths,
            cancel=cancel,
        )

        if not cfg.dry_run:
            operations = executor.execute(operations)

    return operations, scanned


# --- debounce state ------------------------------------------------------


def file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) used to detect changes since the last tick."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def snapshot(source: Path) -> dict[Path, tuple[int, int]]:
    """Map of regular files under `source` to their change signature."""
    source = source.expanduser().resolve()
    result: dict[Path, tuple[int, int]] = {}
    for path in iter_files(source):
        sig = file_signature(path)
        if sig is not None:
            result[path.resolve()] = sig
    return result


def _state_path(state_dir: Path) -> Path:
    return state_dir / "watch_state.json"


def _load_state(state_path: Path) -> dict[str, dict[str, list[int]]]:
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    sources = raw.get("sources", {})
    return sources if isinstance(sources, dict) else {}


def _save_state(
    state_path: Path,
    sources: dict[str, dict[str, list[int]]],
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sources": sources}
    atomic_write_text(
        state_path,
        json.dumps(payload, sort_keys=True, indent=2),
    )


def changed_paths(
    prev: dict[str, list[int]],
    current: dict[Path, tuple[int, int]],
) -> list[Path]:
    """Paths present/updated since the previous tick (new or signature changed)."""
    changed: list[Path] = []
    for path, sig in current.items():
        key = str(path)
        old = prev.get(key)
        if old is None or old[0] != sig[0] or old[1] != sig[1]:
            changed.append(path)
    return changed


# --- pid lock --------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@contextmanager
def watcher_lock(state_dir: Path) -> Iterator[Path]:
    """
    Exclusive watcher pid lock: prevents two `watch` processes on the same
    state_dir. Stale locks (dead pid or unreadable) are reclaimed.

    Raises WatcherLockError if another live watcher holds the lock.
    """
    state_dir = state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "watch.lock"

    fd: int | None = None
    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                other = int(lock_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                other = -1
            if other > 0 and _pid_alive(other):
                raise WatcherLockError(
                    f"Another watcher is already running (pid {other}, "
                    f"lock {lock_path})."
                ) from None
            lock_path.unlink(missing_ok=True)
    else:  # pragma: no cover - loop can only exit via break
        raise WatcherLockError(f"Cannot acquire lock {lock_path}.")

    assert fd is not None
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    finally:
        os.close(fd)

    try:
        yield lock_path
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


# --- polling loop -----------------------------------------------------------


def watch_loop(
    cfg: WatchConfig,
    *,
    interval: float = 30.0,
    cancel: CancelToken | None = None,
    on_tick: Callable[[int, list[PlannedOperation], int], None] | None = None,
) -> None:
    """
    Poll `cfg.source` every `interval` seconds (0.6.2).

    Debounce: only files whose (mtime, size) changed since the last tick are
    planned again. State is persisted at `<state_dir>/watch_state.json` so a
    restart does not re-plan untouched files.

    on_tick(tick: int, ops: list[PlannedOperation], changed: int) is called
    after each tick (logging hook). Cancel-only exit; Ctrl-C propagates
    through the lock context manager (released cleanly).
    """
    if interval < 1:
        raise WatchError("interval must be >= 1 second.")

    source = cfg.source.expanduser().resolve()
    state_dir = cfg.state_dir.expanduser().resolve()
    ensure_builtin_presets(state_dir)
    state_path = _state_path(state_dir)
    sources = _load_state(state_path)

    source_key = str(source)
    prev = sources.get(source_key, {})
    tick = 0

    with watcher_lock(state_dir):
        while cancel is None or not cancel.is_cancelled():
            tick += 1

            current = snapshot(source)
            changed = changed_paths(prev, current)

            ops: list[PlannedOperation] = []
            if changed:
                ops, _ = watch_once(
                    cfg,
                    cancel=cancel,
                    only_paths=set(changed),
                    acquire_lock=False,
                )

            sources[source_key] = {
                str(p): [sig[0], sig[1]] for p, sig in current.items()
            }
            _save_state(state_path, sources)
            prev = sources[source_key]

            if on_tick is not None:
                on_tick(tick, ops, len(changed))

            if cancel is not None and cancel.is_cancelled():
                break
            interruptible_sleep(interval, cancel)


# --- active watch list (0.6.3) ---------------------------------------------


@dataclass(frozen=True)
class ActiveWatch:
    """One entry in the enable list at <state_dir>/active_watches.yaml."""

    name: str
    source: Path
    preset: str | None = None
    rules: Path | None = None
    dry_run: bool = True
    interval_s: float = 60.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise WatchError("watch name must not be empty.")
        if bool(self.preset) == bool(self.rules):
            raise WatchError(
                "Specify exactly one of preset=<name> or rules=<path>."
            )
        try:
            float(self.interval_s)
        except (TypeError, ValueError) as exc:
            raise WatchError(f"interval_s must be a number, got {self.interval_s!r}") from exc

    def to_watch_config(self, state_dir: Path) -> WatchConfig:
        return WatchConfig(
            source=self.source,
            preset=self.preset,
            rules=self.rules,
            dry_run=self.dry_run,
            state_dir=state_dir,
        )


def _active_watches_path(state_dir: Path) -> Path:
    return state_dir.expanduser().resolve() / "active_watches.yaml"


def load_active_watches(state_dir: Path) -> list[ActiveWatch]:
    """Read the enable list; returns [] if missing or unreadable."""
    path = _active_watches_path(state_dir)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    entries = raw.get("watches", []) if isinstance(raw, dict) else []
    out: list[ActiveWatch] = []
    for entry in entries:
        try:
            out.append(
                ActiveWatch(
                    name=str(entry["name"]),
                    source=Path(entry["source"]),
                    preset=entry.get("preset"),
                    rules=Path(entry["rules"]) if entry.get("rules") else None,
                    dry_run=bool(entry.get("dry_run", True)),
                    interval_s=float(entry.get("interval_s", 60)),
                )
            )
        except (KeyError, TypeError) as exc:
            raise WatchError(f"invalid watch entry: {exc}") from exc
    return out


def save_active_watches(state_dir: Path, watches: list[ActiveWatch]) -> Path:
    path = _active_watches_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "watches": [
            {
                "name": w.name,
                "source": str(w.source.expanduser()),
                **({"preset": w.preset} if w.preset else {}),
                **({"rules": str(w.rules)} if w.rules else {}),
                "dry_run": w.dry_run,
                "interval_s": w.interval_s,
            }
            for w in watches
        ]
    }
    atomic_write_text(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )
    return path


def add_active_watch(
    state_dir: Path,
    watch: ActiveWatch,
    *,
    overwrite: bool = False,
) -> Path:
    watches = load_active_watches(state_dir)
    if any(w.name == watch.name for w in watches) and not overwrite:
        raise WatchError(f"Watch already exists: {watch.name!r} (overwrite to replace).")
    watches = [w for w in watches if w.name != watch.name]
    watches.append(watch)
    watches.sort(key=lambda w: w.name)
    return save_active_watches(state_dir, watches)


def remove_active_watch(state_dir: Path, name: str) -> ActiveWatch:
    watches = load_active_watches(state_dir)
    target = next((w for w in watches if w.name == name), None)
    if target is None:
        raise WatchError(f"No active watch named {name!r}.")
    save_active_watches(state_dir, [w for w in watches if w.name != name])
    return target