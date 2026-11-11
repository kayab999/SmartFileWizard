"""Public, versioned API surface for FileWizard (P4-1).

Stable entry points for embedding FileWizard in other applications.
Prefer these over reaching into ``executor``/``journal`` directly.
"""

from __future__ import annotations

import warnings

from pathlib import Path
from typing import Any

from .executor import Executor, PlannedOperation, undo_operations
from .facts import collect_facts
from .journal import Journal
from .models import RuleSet
from .pipeline import plan_operations
from .scanner import iter_files


def plan(
    source: Path | str,
    ruleset: RuleSet,
    *,
    state_dir: Path | str | None = None,
    limit: int | None = None,
    extractors: Any = (),
) -> tuple[list[PlannedOperation], int]:
    """Plan operations for *source* without mutating anything."""
    src = Path(source).expanduser().resolve()
    state = Path(state_dir).expanduser().resolve() if state_dir else None
    journal_path = (state / "journal.db") if state else Path(":memory:")
    with Journal(journal_path) as journal:
        executor = Executor(journal=journal, dry_run=True)
        scan_errors: list[str] = []
        operations, scanned = plan_operations(
            source=src,
            rules=ruleset,
            executor=executor,
            extractors=extractors,
            limit=limit,
            scan_errors=scan_errors,
        )
    return operations, scanned


def execute_operations(
    operations: list[PlannedOperation],
    *,
    state_dir: Path | str,
    batch_id: str | None = None,
    dry_run: bool = False,
) -> list[PlannedOperation]:
    """Execute a previously planned list of operations."""
    state = Path(state_dir).expanduser().resolve()
    with Journal(state / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=dry_run)
        return executor.execute(operations, batch_id=batch_id)


def undo(
    state_dir: Path | str,
    *,
    limit: int = 100,
    execute: bool = False,
) -> list[dict[str, Any]]:
    """Undo the most recent moves (dry-run unless execute=True)."""
    state = Path(state_dir).expanduser().resolve()
    with Journal(state / "journal.db") as journal:
        rows = journal.last_successful_moves(limit=limit)
        return undo_operations(journal, rows, dry_run=not execute)


def deprecated(message: str):
    """Mark a public API as deprecated (emits DeprecationWarning)."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


__all__ = ["plan", "execute_operations", "undo", "collect_facts", "iter_files", "deprecated"]
