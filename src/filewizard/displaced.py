"""Inventory and safe purge of ``<state_dir>/displaced/`` (WP-D4, F-16).

Replace operations keep the overwritten file aside as
``displaced/<op_id><suffix>`` while the journal row still references it
(``displaced_path``). Those files are the only copy of the displaced
content until an undo restores them, so a purge must never delete a
referenced one:

  protected  — a journal row references the file (``displaced_path``) or
               the row that created it (id == file stem op-id) is still in
               a state that may need it (pending/done/needs_verify/
               undo_partial).
  purgeable  — nothing references it (intent cleared: the undo finished,
               the operation failed and dropped the intent, or the row is
               terminal).

Nothing here is destructive by default: purge runs only with an explicit
confirmation flag, reports every deletion, and appends one line per file
to the rotating log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Rows in these states may still need their displaced backup.
PROTECTING_STATUSES = frozenset(
    {"pending", "done", "needs_verify", "undo_partial"}
)


class DisplacedError(RuntimeError):
    """The displaced directory or journal could not be inspected."""


@dataclass
class DisplacedEntry:
    path: Path
    size: int
    age_days: float
    op_id: int | None
    referenced_by: list[int] = field(default_factory=list)
    status: str | None = None

    @property
    def protected(self) -> bool:
        """True while some journal row may still need this file."""
        if self.referenced_by:
            return True
        if self.status in PROTECTING_STATUSES:
            return True
        return False


@dataclass
class DisplacedReport:
    root: Path
    entries: list[DisplacedEntry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    purged: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries)

    @property
    def purgeable_bytes(self) -> int:
        return sum(e.size for e in self.entries if not e.protected)


def displaced_root(state_dir: Path) -> Path:
    return Path(state_dir).expanduser() / "displaced"


def _journal_rows(journal_path: Path) -> list[dict[str, Any]]:
    import sqlite3

    # R8.5: an existing displaced/ directory with a missing journal is
    # uninspectable, not empty. Never expose its files as purgeable.
    if not journal_path.is_file():
        raise DisplacedError(
            f"journal missing or not a regular file: {journal_path}"
        )
    try:
        connection = sqlite3.connect(str(journal_path), timeout=5)
    except sqlite3.Error as exc:
        raise DisplacedError(f"journal cannot be opened: {exc}") from exc
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            """
            SELECT id, status, displaced_path FROM operations
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise DisplacedError(f"journal unreadable: {exc}") from exc
    finally:
        connection.close()


def scan_displaced(
    state_dir: Path,
    journal_path: Path | None = None,
) -> DisplacedReport:
    """Classify every file under ``displaced/`` (read-only)."""
    root = displaced_root(state_dir)
    report = DisplacedReport(root=root)
    if not root.is_dir():
        return report

    journal_path = journal_path or (Path(state_dir) / "journal.db")
    rows = _journal_rows(journal_path)
    by_ref: dict[str, list[int]] = {}
    by_op: dict[int, dict[str, Any]] = {}
    for row in rows:
        ref = row.get("displaced_path")
        if ref:
            by_ref.setdefault(str(Path(str(ref)).resolve()), []).append(
                int(row["id"])
            )
        try:
            by_op[int(row["id"])] = row
        except (TypeError, ValueError):
            continue

    now = time.time()
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            report.problems.append(f"cannot stat {path}: {exc}")
            continue
        referenced = by_ref.get(str(path.resolve()), [])
        op_id: int | None = None
        status: str | None = None
        stem = path.stem
        if stem.isdigit():
            candidate = int(stem)
            matched: dict[str, Any] | None = by_op.get(candidate)
            if matched is not None:
                op_id = candidate
                status = str(matched.get("status") or "")
        report.entries.append(
            DisplacedEntry(
                path=path,
                size=int(stat.st_size),
                age_days=max(0.0, (now - stat.st_mtime) / 86400),
                op_id=op_id,
                referenced_by=referenced,
                status=status,
            )
        )
    return report


def purge_displaced(
    state_dir: Path,
    *,
    older_than_days: float | None = None,
    execute: bool = False,
) -> DisplacedReport:
    """Delete unreferenced displaced backups (never referenced ones).

    Read-only preview unless ``execute`` is True. ``older_than_days``
    restricts the purge to files older than the cutoff (retention).
    Every deletion is logged via the ``filewizard`` logger.
    """
    report = scan_displaced(state_dir)
    for entry in report.entries:
        if entry.protected:
            continue
        if older_than_days is not None and entry.age_days < older_than_days:
            continue
        if not execute:
            continue
        try:
            entry.path.unlink()
        except OSError as exc:
            report.failed.append((entry.path, str(exc)))
            logger.warning(
                "displaced purge failed for %s: %s", entry.path, exc
            )
            continue
        report.purged.append(entry.path)
        logger.info(
            "displaced purge: removed %s (%d bytes, age %.1f days)",
            entry.path,
            entry.size,
            entry.age_days,
        )
    if execute and report.purged:
        logger.info(
            "displaced purge: %d file(s), %d bytes reclaimed",
            len(report.purged),
            sum(
                e.size
                for e in report.entries
                if e.path in set(report.purged)
            ),
        )
    return report
