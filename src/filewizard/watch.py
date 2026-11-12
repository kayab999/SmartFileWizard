from __future__ import annotations

import fcntl
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

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

logger = logging.getLogger(__name__)


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
    allow_model_only: bool = False

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


def destinations_inside_source(ruleset: RuleSet, source: Path) -> list[str]:
    """Static move destinations that resolve inside the watched tree.

    WP-C3 (F-15): this is repeated-work risk, not a guaranteed infinite
    loop — whether a re-observed file matches again depends on the rules
    (and the debounce). Dynamic template destinations are reported as
    "may resolve inside"; static ones are resolved and checked.
    """
    source = source.expanduser().resolve()
    warnings: list[str] = []
    for rule in ruleset.rules:
        dest = rule.then.move_to
        if not dest:
            continue
        if "{" in dest:
            warnings.append(
                f"rule {rule.id}: dynamic destination '{dest}' may "
                f"resolve inside the watched tree {source}"
            )
            continue
        try:
            resolved = Path(dest).expanduser().resolve()
        except OSError:
            continue  # unresolvable: execution will fail on its own
        if resolved == source or source in resolved.parents:
            warnings.append(
                f"rule {rule.id}: destination '{dest}' is inside the "
                f"watched tree {source}"
            )
    return warnings


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

    # WP-C3 (F-15): explicit, non-fatal warning when destinations sit
    # inside the watched tree (repeated work risk, documented).
    for line in destinations_inside_source(ruleset, cfg.source):
        logger.warning("watch: %s", line)

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
            allow_model_only=cfg.allow_model_only,
        )
        held = [op for op in operations if op.status == "needs-review"]
        if held:
            from .review_queue import (
                ReviewQueue,
                ReviewQueueLockError,
            )

            queue = ReviewQueue(state_dir=state_dir)
            for op in held:
                queue.add_model_hold(op.source, op.error or "", save=False)
            try:
                # WP-D2 (F-11): enqueue commits under the lock with a
                # merge, so it can never clobber a concurrent writer.
                queue.merge_new_items()
            except (ReviewQueueLockError, OSError) as exc:
                logger.warning("review queue save failed: %s", exc)
                for op in held:
                    _record_giveup(
                        state_dir,
                        source=cfg.source,
                        path=op.source,
                        attempts=0,
                        last_status="needs-review",
                        reason=f"enqueue_failed: {exc}",
                    )

        if not cfg.dry_run:
            operations = executor.execute(operations)

    return operations, scanned


# --- debounce state ------------------------------------------------------

# Watch-state signature layout (watch_state.json per-source entries).
# Legacy 2-entry lists [mtime_ns, size] remain readable: missing fields
# are treated as "unknown" (attempt count 0; dev/ino/ctime unknown makes
# the signature weaker, never stronger).
SIG_MTIME = 0
SIG_SIZE = 1
SIG_DEV = 2
SIG_INO = 3
SIG_CTIME = 4
SIG_ATTEMPTS = 5
SIG_FIELDS = 6

# WP-C1 (F-04): statuses that mean "the event was processed" (consumed).
# Anything else (error / stale / failed) is NOT consumed: the file is
# re-observed next tick with an attempt counter; after
# MAX_WATCH_ATTEMPTS consecutive failures the signature is consumed
# with a warning (no infinite retry cycles).
CONSUMED_STATUSES = frozenset(
    {"done", "skipped", "noop", "needs-review", "dry-run", "missing",
     "state_mismatch", "already_restored", "undo_partial"}
)
RETRY_STATUSES = frozenset({"error", "stale", "failed"})
MAX_WATCH_ATTEMPTS = 3


def _attempts_of(entry: list[int] | None) -> int:
    if entry is None or len(entry) <= SIG_ATTEMPTS:
        return 0
    return max(0, int(entry[SIG_ATTEMPTS]))


def file_signature(path: Path) -> tuple[int, ...] | None:
    """Change signature for the debounce (WP-C2, F-10).

    (mtime_ns, size, dev, ino, ctime_ns). ``st_dev``/``st_ino`` catch
    same-name substitutions on the same filesystem; ``ctime_ns`` catches
    in-place rewrites that preserve size and mtime (ctime cannot be set
    from userspace on Linux). Their semantics are platform-specific —
    they are change *detection* signals, never content identity.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (
        st.st_mtime_ns,
        st.st_size,
        getattr(st, "st_dev", 0),
        getattr(st, "st_ino", 0),
        getattr(st, "st_ctime_ns", 0),
    )


def snapshot(source: Path) -> dict[Path, tuple[int, ...]]:
    """Map of regular files under `source` to their change signature."""
    source = source.expanduser().resolve()
    result: dict[Path, tuple[int, ...]] = {}
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


def _giveups_path(state_dir: Path) -> Path:
    return state_dir / "watch_giveups.jsonl"


def _giveups_error_path(state_dir: Path) -> Path:
    return state_dir / "watch_giveups.error.json"


def read_giveup_error(state_dir: Path) -> dict[str, Any] | None:
    """Observable persistent error when the JSONL surface itself fails."""
    try:
        value = json.loads(_giveups_error_path(state_dir).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _record_giveup(
    state_dir: Path,
    *,
    source: Path,
    path: Path,
    attempts: int,
    last_status: str | None,
    reason: str,
) -> bool:
    """Append one give-up / enqueue-failure event as a JSONL line.

    R4: a queryable operator surface independent of the rotating log.
    Append (fsynced) so a crash between events cannot lose prior records;
    each line is a self-contained JSON object.
    """
    import json as _json
    import os as _os

    from datetime import datetime, timezone

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "path": str(path),
        "attempts": int(attempts),
        "last_status": last_status,
        "reason": reason,
    }
    path_out = _giveups_path(state_dir)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with path_out.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            try:
                _os.fsync(fh.fileno())
            except OSError:
                pass
    except OSError as exc:
        # R8.8: recording failure is itself an observable persistent state,
        # not merely a debug trace. The next giveup CLI read surfaces it.
        logger.error("watch giveup persistence failed for %s: %s", path, exc)
        try:
            atomic_write_text(
                _giveups_error_path(state_dir),
                _json.dumps({"record": record, "error": str(exc)}, ensure_ascii=False),
            )
        except OSError:
            logger.error("watch giveup error state could not be persisted")
        return False
    from .persist import ensure_private_file

    ensure_private_file(path_out)
    return True


def read_giveups(state_dir: Path) -> list[dict[str, Any]]:
    """Read all give-up events (oldest first)."""
    import json as _json

    path = _giveups_path(state_dir)
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            item = _json.loads(raw)
        except (ValueError, _json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def clear_giveups(state_dir: Path) -> None:
    for path in (_giveups_path(state_dir), _giveups_error_path(state_dir)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def retry_watch_paths(state_dir: Path, paths: list[str]) -> dict[str, int]:
    """Reset attempt counters for the given paths in watch_state.json.

    Runs under ``watcher_lock`` so it cannot race a live watcher tick.
    Returns a dict with ``reset`` (entries whose counter was reset) and
    ``not_found`` (requested paths absent from every source's state). The
    give-up log is filtered to drop entries for retried paths so the
    operator's view matches the new state.
    """
    state_dir = state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)

    targets = {str(Path(p).expanduser().resolve()) for p in paths}

    with watcher_lock(state_dir):
        state_path = _state_path(state_dir)
        state = _load_state(state_path)

        reset = 0
        found: set[str] = set()
        for source, entries in state.items():
            if not isinstance(entries, dict):
                continue
            for key in list(entries.keys()):
                try:
                    resolved = str(Path(key).resolve())
                except (OSError, RuntimeError):
                    resolved = key
                if resolved not in targets:
                    continue
                sig = entries.get(key)
                if isinstance(sig, list) and sig:
                    # 1 (not 0): changed_paths re-enqueues a path only when
                    # 0 < attempts < MAX_WATCH_ATTEMPTS.
                    sig[-1] = 1
                    entries[key] = sig
                    reset += 1
                    found.add(resolved)
        _save_state(state_path, state)

        # Filter give-ups for retried paths.
        gp = _giveups_path(state_dir)
        if gp.exists():
            kept: list[str] = []
            for line in gp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                ev_path = ev.get("path")
                try:
                    ev_resolved = (
                        str(Path(str(ev_path)).resolve()) if ev_path else ""
                    )
                except (OSError, RuntimeError):
                    ev_resolved = str(ev_path)
                if ev_resolved in targets:
                    continue
                kept.append(line)
            atomic_write_text(gp, "\n".join(kept) + ("\n" if kept else ""))

    not_found = len(targets - found)
    return {"reset": reset, "not_found": not_found, "targets": len(targets)}


def changed_paths(
    prev: dict[str, list[int]],
    current: dict[Path, tuple[int, ...]],
) -> list[Path]:
    """Paths present/updated since the previous tick (new or signature changed).

    Legacy 2-entry lists compare on (mtime, size) only; newer entries
    also compare dev/ino/ctime when present.
    """
    changed: list[Path] = []
    for path, sig in current.items():
        key = str(path)
        old = prev.get(key)
        if old is None:
            changed.append(path)
            continue
        changed_sig = False
        for idx in range(min(len(sig), len(old))):
            if old[idx] != sig[idx]:
                changed_sig = True
                break
        if changed_sig:
            changed.append(path)
            continue
        # WP-C1: an unconsumed failure is re-observed next tick.
        attempts = _attempts_of(old)
        if 0 < attempts < MAX_WATCH_ATTEMPTS:
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
    Exclusive watcher lock (E1): ``flock`` on ``watch.lock`` + pid/token
    diagnostics.

    The exclusion primitive is the flock: the kernel releases it when
    the holder dies, so a crashed watcher can never wedge the lock and
    pid reuse cannot make a dead lock look alive (pid + ``kill(pid, 0)``
    alone is not a robust identity). The pid and a random token in the
    file are diagnostics only.

    Raises WatcherLockError if another live watcher holds the lock.
    """
    state_dir = state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "watch.lock"

    fd = os.open(
        lock_path, os.O_CREAT | os.O_RDWR, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            other = -1
            try:
                other = int(
                    lock_path.read_text(encoding="utf-8").strip() or -1
                )
            except (OSError, ValueError):
                pass
            raise WatcherLockError(
                f"Another watcher is already running (pid {other}, "
                f"lock {lock_path})."
            ) from exc
        # Truncate + record owner identity (diagnostics, not the lock).
        try:
            os.ftruncate(fd, 0)
            token = uuid.uuid4().hex
            os.write(
                fd,
                f"{os.getpid()} {token}".encode("ascii"),
            )
        except OSError:
            pass

        try:
            yield lock_path
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(fd)
        # Removing the file is only cosmetic; the flock, not its absence,
        # is the lock. Removing it while a waiter holds a flock on the
        # same inode is avoided by leaving the file in place.


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

            # WP-C1 (F-04): observed is not processed. Only statuses in
            # CONSUMED_STATUSES record the signature cleanly; a failed
            # attempt keeps the file observable and counts an attempt,
            # capped at MAX_WATCH_ATTEMPTS to avoid infinite retries.
            op_status: dict[str, str] = {}
            for op in ops:
                op_status[str(op.source)] = op.status

            new_prev: dict[str, list[int]] = {}
            for path, sig in current.items():
                key = str(path)
                old = prev.get(key)
                # Reset attempts only on a genuinely new signature; a
                # forced retry re-observation (same signature) keeps
                # counting (WP-C1).
                sig_changed = old is None or any(
                    old[i] != sig[i] for i in range(min(len(sig), len(old)))
                )
                attempts = 0 if sig_changed else _attempts_of(old)
                status = op_status.get(key)
                if status in RETRY_STATUSES:
                    attempts += 1
                    if attempts >= MAX_WATCH_ATTEMPTS:
                        logger.warning(
                            "watch: giving up on %s after %d failed "
                            "attempts (last status: %s)",
                            key,
                            attempts,
                            status,
                        )
                        _record_giveup(
                            state_dir,
                            source=source,
                            path=Path(key),
                            attempts=attempts,
                            last_status=status,
                            reason="max_attempts_exhausted",
                        )
                entry: list[int] = list(sig) + [attempts]
                new_prev[key] = entry
            sources[source_key] = new_prev
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