from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .persist import ensure_private_file


class Journal:
    """
    Transactional journal for audit and undo.

    Essential for a production tool that moves files.
    Status lifecycle for moves:
      pending → done | failed | skipped
      done → undone  (only after a successful reverse move)

    Batches (batch_id) group operations from one execute/undo run.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # R12: timeout for concurrent access; one connection per Journal instance/thread.
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        # E2 (F-05b): the journal records user paths — owner-only.
        ensure_private_file(self.path)
        # R5 perms round: the WAL/SHM side files carry the same user-path
        # data and SQLite keeps a preexisting file's mode when reconnecting.
        # Tighten them if they already exist (fresh creation follows the
        # database's 0600). Best-effort, like the rest of E2.
        for side in ("-wal", "-shm"):
            side_path = Path(str(self.path) + side)
            if side_path.exists():
                ensure_private_file(side_path)
        # 0.9.4: WAL so readers (preview/history) block writers less.
        # Separate try so busy_timeout still applies if WAL is unavailable.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            self.conn.execute("PRAGMA busy_timeout=10000")
        except Exception:
            pass

        self._create_schema()
        self._migrate_schema()

    def _create_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_name TEXT,
                op TEXT NOT NULL,
                source TEXT NOT NULL,
                destination TEXT,
                status TEXT NOT NULL,
                error TEXT,
                byte_size INTEGER,
                perception TEXT,
                content_sha256 TEXT,
                source_mtime_ns INTEGER,
                source_dev INTEGER,
                source_ino INTEGER,
                displaced_path TEXT,
                owner_pid INTEGER,
                original_operation_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_operations_status
            ON operations(status)
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_operations_op_status
            ON operations(op, status)
            """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_operations_batch
            ON operations(batch_id)
            """
        )

        self.conn.commit()

    def _migrate_schema(self) -> None:
        """Add columns introduced after the first schema version."""
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(operations)").fetchall()
        }
        if "byte_size" not in columns:
            self.conn.execute(
                "ALTER TABLE operations ADD COLUMN byte_size INTEGER"
            )
        if "rule_name" not in columns:
            self.conn.execute(
                "ALTER TABLE operations ADD COLUMN rule_name TEXT"
            )
        if "perception" not in columns:
            # Compact JSON snapshot of cascade/ocr/vision evidence (0.4.4+).
            self.conn.execute(
                "ALTER TABLE operations ADD COLUMN perception TEXT"
            )
        for name, ddl in (
            ("content_sha256", "TEXT"),
            ("source_mtime_ns", "INTEGER"),
            ("source_dev", "INTEGER"),
            ("source_ino", "INTEGER"),
            ("displaced_path", "TEXT"),
            ("displaced_size", "INTEGER"),
            ("displaced_sha256", "TEXT"),
            ("displaced_mtime_ns", "INTEGER"),
            ("displaced_dev", "INTEGER"),
            ("displaced_ino", "INTEGER"),
            ("owner_pid", "INTEGER"),
            ("original_operation_id", "INTEGER"),
        ):
            if name not in columns:
                try:
                    self.conn.execute(
                        f"ALTER TABLE operations ADD COLUMN {name} {ddl}"
                    )
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc):
                        raise
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start_operation(
        self,
        batch_id: str,
        rule_id: str,
        op: str,
        source: Path,
        destination: Path | None,
        byte_size: int | None = None,
        rule_name: str | None = None,
        perception: dict[str, Any] | str | None = None,
        content_sha256: str | None = None,
        source_mtime_ns: int | None = None,
        source_dev: int | None = None,
        source_ino: int | None = None,
        owner_pid: int | None = None,
        original_operation_id: int | None = None,
    ) -> int:
        now = self._now()
        perception_json: str | None
        if perception is None:
            perception_json = None
        elif isinstance(perception, str):
            perception_json = perception
        else:
            perception_json = json.dumps(
                perception, ensure_ascii=False, default=str
            )

        cur = self.conn.execute(
            """
            INSERT INTO operations (
                batch_id,
                rule_id,
                rule_name,
                op,
                source,
                destination,
                status,
                error,
                byte_size,
                perception,
                content_sha256,
                source_mtime_ns,
                source_dev,
                source_ino,
                owner_pid,
                original_operation_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                rule_id,
                rule_name,
                op,
                str(source),
                str(destination) if destination else None,
                "pending",
                None,
                byte_size,
                perception_json,
                content_sha256,
                source_mtime_ns,
                source_dev,
                source_ino,
                owner_pid if owner_pid is not None else os.getpid(),
                original_operation_id,
                now,
                now,
            ),
        )

        self.conn.commit()

        row_id = cur.lastrowid
        assert row_id is not None
        return int(row_id)

    @staticmethod
    def parse_perception(row: Any) -> dict[str, Any] | None:
        """Decode operations.perception JSON from a sqlite Row / mapping."""
        try:
            raw = row["perception"]
        except (KeyError, IndexError, TypeError):
            return None
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def finish_operation(
        self,
        op_id: int,
        status: str,
        destination: Path | str | None = None,
        error: str | None = None,
        byte_size: int | None = None,
    ) -> None:
        now = self._now()

        destination_value = (
            str(destination)
            if destination is not None
            else None
        )

        self.conn.execute(
            """
            UPDATE operations
            SET
                status = ?,
                destination = COALESCE(?, destination),
                error = ?,
                byte_size = COALESCE(?, byte_size),
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                destination_value,
                error,
                byte_size,
                now,
                op_id,
            ),
        )

        self.conn.commit()

    def set_displaced(
        self,
        op_id: int,
        path: Path | str,
        *,
        size: int | None = None,
        sha256: str | None = None,
        mtime_ns: int | None = None,
        device: int | None = None,
        inode: int | None = None,
    ) -> None:
        """Persist displacement intent and evidence of the displaced bytes.

        R8.4: absence of a backup is not evidence of restoration. The
        recorded identity lets undo distinguish a restored occupant from
        a foreign file before closing the saga.
        """
        self.conn.execute(
            """
            UPDATE operations
            SET displaced_path = ?, displaced_size = ?, displaced_sha256 = ?,
                displaced_mtime_ns = ?, displaced_dev = ?, displaced_ino = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(path), size, sha256, mtime_ns, device, inode,
                self._now(), op_id,
            ),
        )
        self.conn.commit()

    def clear_displaced(self, op_id: int) -> None:
        self.conn.execute(
            """
            UPDATE operations
            SET displaced_path = NULL, updated_at = ?
            WHERE id = ?
            """,
            (self._now(), op_id),
        )
        self.conn.commit()

    def mark_undone(self, op_id: int) -> None:
        now = self._now()

        self.conn.execute(
            """
            UPDATE operations
            SET
                status = 'undone',
                updated_at = ?
            WHERE id = ?
              AND status IN ('done', 'needs_verify', 'undo_partial')
            """,
            (
                now,
                op_id,
            ),
        )

        self.conn.commit()

    def mark_undo_partial(self, op_id: int) -> bool:
        """Mark an operation as partially undone (ADR-0005 state).

        The reverse move (A) succeeded but the displaced backup restore
        (B) did not. The row keeps its identity/undo evidence and stays
        non-purgeable until the restore is retried and completes.
        Returns True when the row was transitioned.
        """
        now = self._now()
        cur = self.conn.execute(
            """
            UPDATE operations
            SET
                status = 'undo_partial',
                updated_at = ?
            WHERE id = ?
              AND status IN ('done', 'needs_verify')
            """,
            (
                now,
                op_id,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def last_successful_moves(self, limit: int = 100) -> list[Any]:
        """Moves still eligible for undo or undo-restore retry.

        ``undo_partial`` rows are included so a partial undo (reverse
        move done, backup restore pending) can be resumed; undo_operations
        handles them without repeating the reverse move.
        """
        cur = self.conn.execute(
            """
            SELECT *
            FROM operations
            WHERE op = 'move'
              AND status IN ('done', 'needs_verify', 'undo_partial')
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return cur.fetchall()

    def recent_operations(self, limit: int = 50) -> list[Any]:
        cur = self.conn.execute(
            "SELECT * FROM operations ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def recent_batches(self, limit: int = 20) -> list[Any]:
        """Aggregate operations into sessions (one row per batch_id)."""
        cur = self.conn.execute(
            """
            SELECT
                batch_id,
                MIN(created_at) AS started_at,
                MAX(updated_at) AS finished_at,
                GROUP_CONCAT(DISTINCT COALESCE(rule_name, rule_id)) AS rule_names,
                GROUP_CONCAT(DISTINCT op) AS ops,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN status = 'undone' THEN 1 ELSE 0 END) AS undone,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                COUNT(*) AS total,
                MAX(id) AS last_id
            FROM operations
            GROUP BY batch_id
            ORDER BY last_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()

    def operations_for_batch(self, batch_id: str) -> list[Any]:
        cur = self.conn.execute(
            "SELECT * FROM operations WHERE batch_id = ? ORDER BY id",
            (batch_id,),
        )
        return cur.fetchall()

    def done_moves_for_batch(self, batch_id: str) -> list[Any]:
        """Moves of a batch eligible for undo or undo-restore retry."""
        cur = self.conn.execute(
            """
            SELECT * FROM operations
            WHERE batch_id = ? AND op = 'move'
              AND status IN ('done', 'needs_verify', 'undo_partial')
            ORDER BY id DESC
            """,
            (batch_id,),
        )
        return cur.fetchall()

    def pending_operations(self) -> list[Any]:
        cur = self.conn.execute(
            "SELECT * FROM operations WHERE status = 'pending' ORDER BY id"
        )
        return cur.fetchall()

    def reconcile_pending(self) -> tuple[int, int]:
        """Promote pending rows whose moved bytes match the recorded hash.

        Evidence ladder (ADR-0005):
          E1 content hash match          → done
          E2 fs-identity (dev/ino/size)  → needs_verify (metadata evidence
                                           only; never presented as done)
          E3 presence alone              → insufficient, row stays pending

        Size alone is not enough. A pending replace whose backup is still
        aside and whose source is still present is put back first.
        Returns ``(promoted, still_pending)``. Idempotent: re-running with
        unchanged filesystem state promotes nothing twice.
        """
        promoted = 0
        for row in self.pending_operations():
            if str(row["op"]) not in {"move", "undo"}:
                continue
            source_raw = row["source"]
            dest_raw = row["destination"]
            recorded = row["byte_size"] if "byte_size" in row.keys() else None
            digest = row["content_sha256"] if "content_sha256" in row.keys() else None
            if not source_raw or not dest_raw or recorded is None:
                continue
            source = Path(str(source_raw))
            destination = Path(str(dest_raw))
            displaced_raw = (
                row["displaced_path"] if "displaced_path" in row.keys() else None
            )
            # R8.3: size alone cannot identify our reservation. Only a
            # genuinely missing destination is free; an empty file or a
            # symlink is foreign and is never overwritten.
            if displaced_raw and source.exists() and not destination.exists():
                backup = Path(str(displaced_raw))
                if backup.is_file():
                    try:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        from .fsmove import move_noreplace

                        move_noreplace(backup, destination)
                        self.clear_displaced(int(row["id"]))
                    except OSError:
                        pass
                continue
            if displaced_raw and source.exists() and destination.exists():
                backup = Path(str(displaced_raw))
                if backup.is_file():
                    # R8.3: a foreign file (including an empty regular file
                    # or a symlink) is never our placeholder. Preserve the
                    # backup and keep the row pending with an explicit
                    # conflict note — never claim needs_verify without E2
                    # evidence (ADR-0005). The operator resolves it manually.
                    self.finish_operation(
                        int(row["id"]),
                        status="pending",
                        destination=destination,
                        error=(
                            "destination occupied during crash recovery; "
                            "displaced backup preserved for review"
                        ),
                    )
                    continue
            try:
                from .identity import fs_identity_matches, content_matches

                source_gone = not source.exists()
                if source_gone and content_matches(
                    destination, size=int(recorded), sha256=digest
                ):
                    # E1: content verified.
                    self.finish_operation(
                        int(row["id"]),
                        status="done",
                        destination=destination,
                        byte_size=int(recorded),
                    )
                    promoted += 1
                    continue
                if (
                    source_gone
                    and digest is None
                    and fs_identity_matches(
                        destination,
                        size=int(recorded),
                        source_dev=row["source_dev"]
                        if "source_dev" in row.keys()
                        else None,
                        source_ino=row["source_ino"]
                        if "source_ino" in row.keys()
                        else None,
                    )
                ):
                    # E2: same-file-object evidence only → needs_verify.
                    self.finish_operation(
                        int(row["id"]),
                        status="needs_verify",
                        destination=destination,
                        byte_size=int(recorded),
                    )
                    promoted += 1
                    continue
            except OSError:
                continue
        return promoted, len(self.pending_operations())

    def resolve_pending(self, status: str = "interrupted") -> int:
        """Mark pending rows whose owner process is gone.

        A null ``owner_pid`` is treated as stale. A live pid is left pending
        so another FileWizard process can finish its own batch.
        """
        from .identity import pid_alive

        stale: list[int] = []
        for row in self.pending_operations():
            pid = row["owner_pid"] if "owner_pid" in row.keys() else None
            if pid is None or not pid_alive(int(pid)):
                stale.append(int(row["id"]))
        if not stale:
            return 0
        now = self._now()
        placeholders = ",".join("?" for _ in stale)
        cur = self.conn.execute(
            f"""
            UPDATE operations
            SET status = ?, updated_at = ?
            WHERE status = 'pending' AND id IN ({placeholders})
            """,
            (status, now, *stale),
        )
        self.conn.commit()
        return int(cur.rowcount)

    def get_operation(self, op_id: int) -> Any | None:
        cur = self.conn.execute(
            "SELECT * FROM operations WHERE id = ?",
            (op_id,),
        )
        return cur.fetchone()

    # Statuses that can never back an undo (done/pending excluded on purpose).
    PURGEABLE_STATUSES = (
        "failed",
        "skipped",
        "error",
        "interrupted",
        "undone",
    )

    def _purge_cutoff(self, older_than_days: int) -> str:
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        # updated_at is always UTC ISO from _now(): lexicographic compare works.
        return (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).isoformat()

    def count_purgeable(self, *, older_than_days: int = 90) -> int:
        """Rows purge() would delete (dry-run preview)."""
        cutoff = self._purge_cutoff(older_than_days)
        placeholders = ",".join("?" for _ in self.PURGEABLE_STATUSES)
        cur = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM operations
            WHERE status IN ({placeholders})
              AND updated_at < ?
            """,
            (*self.PURGEABLE_STATUSES, cutoff),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def purge(self, *, older_than_days: int = 90) -> int:
        """Delete old non-undoable rows (retention policy, Fase 3).

        Only removes PURGEABLE_STATUSES older than the cutoff (by updated_at).
        `done` (undo evidence) and `pending` (unresolved) are never touched.
        """
        cutoff = self._purge_cutoff(older_than_days)
        placeholders = ",".join("?" for _ in self.PURGEABLE_STATUSES)
        cur = self.conn.execute(
            f"""
            DELETE FROM operations
            WHERE status IN ({placeholders})
              AND updated_at < ?
            """,
            (*self.PURGEABLE_STATUSES, cutoff),
        )
        self.conn.commit()
        return int(cur.rowcount)

    # F-16 (E2): hard size quota on top of the age-based policy. The quota
    # only ever deletes the OLDEST PURGEABLE_STATUSES rows; undo evidence
    # (`done`), unresolved (`pending`) and verification-required
    # (`needs_verify`) rows are never evicted — the journal can grow, but it
    # cannot lose recoverable work silently. Protected statuses are already
    # outside PURGEABLE_STATUSES; the guard makes that invariant explicit.
    QUOTA_PROTECTED_STATUSES = ("done", "pending", "needs_verify", "undo_partial")

    def count_rows(self) -> int:
        """Total number of journal rows (for quota checks)."""
        cur = self.conn.execute("SELECT COUNT(*) FROM operations")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def enforce_quota(self, *, max_rows: int = 100_000) -> int:
        """Trim the journal to at most *max_rows* rows.

        Deletes only the oldest purgeable rows (same statuses as ``purge``)
        until the row count fits or nothing purgeable remains. Protected
        statuses above are never deleted regardless of age. Returns the
        number of rows removed.
        """
        if max_rows < 0:
            raise ValueError("max_rows must be >= 0")
        excess = self.count_rows() - max_rows
        if excess <= 0:
            return 0
        placeholders = ",".join("?" for _ in self.PURGEABLE_STATUSES)
        cur = self.conn.execute(
            f"""
            DELETE FROM operations WHERE id IN (
                SELECT id FROM operations
                WHERE status IN ({placeholders})
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (*self.PURGEABLE_STATUSES, excess),
        )
        self.conn.commit()
        return int(cur.rowcount)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
