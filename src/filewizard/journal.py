from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


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
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                now,
                now,
            ),
        )

        self.conn.commit()

        return int(cur.lastrowid)

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

    def mark_undone(self, op_id: int) -> None:
        now = self._now()

        self.conn.execute(
            """
            UPDATE operations
            SET
                status = 'undone',
                updated_at = ?
            WHERE id = ?
              AND status = 'done'
            """,
            (
                now,
                op_id,
            ),
        )

        self.conn.commit()

    def last_successful_moves(self, limit: int = 100) -> list[Any]:
        """Only moves still eligible for undo (status=done, not already undone)."""
        cur = self.conn.execute(
            """
            SELECT *
            FROM operations
            WHERE op = 'move'
              AND status = 'done'
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
        cur = self.conn.execute(
            """
            SELECT * FROM operations
            WHERE batch_id = ? AND op = 'move' AND status = 'done'
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

    def resolve_pending(self, status: str = "interrupted") -> int:
        """R4: mark interrupted pending rows so they are not stuck forever."""
        cur = self.conn.execute(
            """
            UPDATE operations
            SET status = ?, updated_at = ?
            WHERE status = 'pending'
            """,
            (status, self._now()),
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

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
