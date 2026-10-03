"""Read-only comparison of one journal batch with the files it recorded.

Every path comes from the journal or the review queue. Nothing here creates
a directory, a journal, or a queue file, and nothing here names a folder
the user did not already record.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


_SOURCE_REMAINS = frozenset({"skipped", "failed", "error", "interrupted"})


@dataclass(frozen=True)
class Divergence:
    operation_id: int
    op: str
    status: str
    detail: str


@dataclass
class VerifyReport:
    batch_id: str
    journal_path: Path
    found: bool
    problem: str | None = None
    done: int = 0
    holds: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    awaiting_review: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.found
            and self.problem is None
            and not self.divergences
            and not self.awaiting_review
        )


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    started_at: str
    done: int
    total: int


@dataclass
class BatchList:
    journal_path: Path
    problem: str | None = None
    batches: list[BatchSummary] = field(default_factory=list)


def format_report(report: VerifyReport) -> str:
    lines = [f"batch: {report.batch_id}"]
    if report.problem:
        lines.append(report.problem)
    for item in report.divergences:
        lines.append(
            f"diverged #{item.operation_id} {item.op} {item.status}: {item.detail}"
        )
    for path in report.awaiting_review:
        lines.append(f"awaiting review: {path}")
    lines.append(
        f"done: {report.done}    holds: {report.holds}    "
        f"diverged: {len(report.divergences)}"
    )
    lines.append(f"awaiting review: {len(report.awaiting_review)}")
    lines.append("RESULT: " + ("FREEZE PASS" if report.passed else "FREEZE FAIL"))
    return "\n".join(lines)


def format_batch_list(listing: BatchList) -> str:
    if listing.problem:
        return listing.problem
    if not listing.batches:
        return f"Journal at {listing.journal_path} has no batches yet."
    lines = [f"Recorded batches in {listing.journal_path}:"]
    for batch in listing.batches:
        lines.append(
            f"  {batch.batch_id}  {batch.started_at}  "
            f"done={batch.done}  total={batch.total}"
        )
    lines.append("Check one with: filewizard verify --batch <id>")
    return "\n".join(lines)


def list_batches(journal_path: Path, *, limit: int = 20) -> BatchList:
    """Recent batches. Missing journal is an empty history, not an error file."""
    journal_path = Path(journal_path)
    listing = BatchList(journal_path=journal_path)
    rows, problem = _load_rows(journal_path)
    if problem:
        listing.problem = problem
        return listing
    if rows is None:
        return listing
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        batch_id = str(row["batch_id"])
        slot = grouped.get(batch_id)
        if slot is None:
            slot = {
                "started_at": str(row.get("created_at") or ""),
                "done": 0,
                "total": 0,
                "last_id": int(row["id"]),
            }
            grouped[batch_id] = slot
            order.append(batch_id)
        slot["total"] += 1
        if str(row["status"]) == "done":
            slot["done"] += 1
        slot["last_id"] = max(int(slot["last_id"]), int(row["id"]))
        created = str(row.get("created_at") or "")
        if created and (not slot["started_at"] or created < slot["started_at"]):
            slot["started_at"] = created
    order.sort(key=lambda batch_id: int(grouped[batch_id]["last_id"]), reverse=True)
    listing.batches = [
        BatchSummary(
            batch_id=batch_id,
            started_at=str(grouped[batch_id]["started_at"]),
            done=int(grouped[batch_id]["done"]),
            total=int(grouped[batch_id]["total"]),
        )
        for batch_id in order[:limit]
    ]
    return listing


def verify_batch(
    journal_path: Path,
    batch_id: str,
    review_queue_path: Path | None = None,
) -> VerifyReport:
    """Check one batch. Does not create or modify any file."""
    journal_path = Path(journal_path)
    report = VerifyReport(batch_id=batch_id, journal_path=journal_path, found=False)
    if not str(batch_id).strip():
        report.problem = "Batch id is empty."
        return report

    rows, problem = _load_rows(journal_path)
    if problem:
        report.problem = problem
        return report
    assert rows is not None

    batch = [row for row in rows if str(row["batch_id"]) == batch_id]
    if not batch:
        report.problem = f"No operations recorded for batch {batch_id}."
        return report
    report.found = True

    undo_done = [
        row
        for row in rows
        if str(row["op"]) == "undo" and str(row["status"]) == "done"
    ]
    for row in batch:
        detail = _check_row(row, undo_done)
        if detail is None:
            report.holds += 1
        else:
            report.divergences.append(
                Divergence(
                    operation_id=int(row["id"]),
                    op=str(row["op"]),
                    status=str(row["status"]),
                    detail=detail,
                )
            )
        if str(row["status"]) == "done":
            report.done += 1

    if review_queue_path is not None:
        pending, review_problem = _unresolved_review_paths(Path(review_queue_path))
        if review_problem:
            report.problem = review_problem
        else:
            batch_keys = _batch_path_keys(batch)
            seen: set[str] = set()
            for path in pending:
                key = _key(path)
                if key and key in batch_keys and key not in seen:
                    seen.add(key)
                    report.awaiting_review.append(path)
    return report


def _check_row(row: dict, undo_done: list[dict]) -> str | None:
    status = str(row["status"])
    if status == "done":
        return _check_relocated(row)
    if status == "undone":
        return _check_undone(row, undo_done)
    if status == "pending":
        return "operation still pending"
    if status in _SOURCE_REMAINS:
        return _check_source_remains(row)
    return f"status {status!r} has no check"


def _check_relocated(row: dict) -> str | None:
    source = _path(row.get("source"))
    destination = _path(row.get("destination"))
    if source is None or destination is None:
        return "journal row has no source or destination"
    problem = _require_regular(destination, "destination")
    if problem:
        return problem
    problem = _require_size(destination, row.get("byte_size"), "destination")
    if problem:
        return problem
    problem = _require_hash(destination, row.get("content_sha256"), "destination")
    if problem:
        return problem
    try:
        if source.exists():
            return f"source still present: {source}"
    except OSError as exc:
        return f"cannot inspect source {source} ({exc})"
    return None


def _check_undone(row: dict, undo_done: list[dict]) -> str | None:
    destination = _path(row.get("destination"))
    restored = _restored_path(row, undo_done)
    if restored is None:
        return "no restored path recorded"
    problem = _require_regular(restored, "restored file")
    if problem:
        return problem
    problem = _require_size(restored, row.get("byte_size"), "restored file")
    if problem:
        return problem
    problem = _require_hash(restored, row.get("content_sha256"), "restored file")
    if problem:
        return problem
    if destination is not None and _key(destination) != _key(restored):
        try:
            if destination.exists():
                return f"move destination still present after undo: {destination}"
        except OSError as exc:
            return f"cannot inspect destination {destination} ({exc})"
    return None


def _restored_path(row: dict, undo_done: list[dict]) -> Path | None:
    destination_key = _key(row.get("destination"))
    matches = [
        undo
        for undo in undo_done
        if destination_key and _key(undo.get("source")) == destination_key
    ]
    if matches:
        latest = max(matches, key=lambda undo: int(undo["id"]))
        recorded = _path(latest.get("destination"))
        if recorded is not None:
            return recorded
    return _path(row.get("source"))


def _check_source_remains(row: dict) -> str | None:
    source = _path(row.get("source"))
    if source is None:
        return "journal row has no source"
    return _require_regular(source, "source")


def _require_regular(path: Path, role: str) -> str | None:
    try:
        if path.is_symlink():
            return f"{role} {path}: not a regular file"
        if not path.exists():
            return f"{role} {path}: missing"
        if not path.is_file():
            return f"{role} {path}: not a regular file"
    except OSError as exc:
        return f"cannot inspect {role} {path} ({exc})"
    return None


def _require_hash(path: Path, recorded: object, role: str) -> str | None:
    if not isinstance(recorded, str) or not recorded:
        return None
    from .perception.cache import file_content_hash

    try:
        actual = file_content_hash(path)
    except OSError as exc:
        return f"cannot hash {role} {path} ({exc})"
    if actual != recorded:
        return f"{role} {path}: content hash does not match journal"
    return None


def _require_size(path: Path, recorded: object, role: str) -> str | None:
    if recorded is None:
        return f"{role} {path}: journal has no recorded size"
    try:
        actual = path.stat().st_size
    except OSError as exc:
        return f"cannot read size of {role} {path} ({exc})"
    expected = int(recorded)
    if actual != expected:
        return f"{role} {path}: size {actual} does not match journal {expected}"
    return None


def _batch_path_keys(rows: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        for field_name in ("source", "destination"):
            key = _key(row.get(field_name))
            if key:
                keys.add(key)
    return keys


def _unresolved_review_paths(path: Path) -> tuple[list[str], str | None]:
    if not path.is_file():
        return [], None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], (
            f"Review queue could not be read ({exc}). The file was left unchanged."
        )
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], (
            "Review queue could not be read (no item list). The file was left unchanged."
        )
    pending: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("resolved") is True:
            continue
        item_path = item.get("path")
        if isinstance(item_path, str) and item_path:
            pending.append(item_path)
    return pending, None


def _path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _key(value: object) -> str | None:
    path = value if isinstance(value, Path) else _path(value)
    if path is None:
        return None
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _load_rows(journal_path: Path) -> tuple[list[dict] | None, str | None]:
    if not journal_path.is_file():
        return None, (
            f"No journal at {journal_path}. "
            "Apply a plan with filewizard run --source <directory> --execute "
            "and the batch is recorded there."
        )
    try:
        connection = _connect_readonly(journal_path)
    except sqlite3.Error as exc:
        return None, f"Journal could not be read ({exc})."
    try:
        return _select_rows(connection), None
    except sqlite3.Error as exc:
        return None, f"Journal could not be read ({exc})."
    finally:
        connection.close()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    quoted = quote(path.resolve().as_posix(), safe="/")
    connection = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _select_rows(connection: sqlite3.Connection) -> list[dict]:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(operations)").fetchall()
    }
    required = {"id", "batch_id", "op", "source", "destination", "status"}
    missing = sorted(required - columns)
    if not columns or missing:
        raise sqlite3.OperationalError(
            "operations table is missing columns: " + ", ".join(missing or ["operations"])
        )
    size_sql = "byte_size" if "byte_size" in columns else "NULL AS byte_size"
    created_sql = "created_at" if "created_at" in columns else "NULL AS created_at"
    hash_sql = (
        "content_sha256" if "content_sha256" in columns else "NULL AS content_sha256"
    )
    cursor = connection.execute(
        f"""
        SELECT id, batch_id, op, source, destination, status,
               {size_sql}, {created_sql}, {hash_sql}
        FROM operations
        ORDER BY id
        """
    )
    return [dict(row) for row in cursor.fetchall()]
