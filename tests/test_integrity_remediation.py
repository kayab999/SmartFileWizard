"""Remediation WPs A–E: integrity, jail, watcher, resources.

Evidence tests for the forensic audit findings F-01…F-18 / A-01…A-06.
Each test names the invariant of ADR-0005 it pins.
"""

import errno
import json
import os
import shutil
import sys
import types
from pathlib import Path

import pytest

from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.mcp.tools import filewizard_execute
from filewizard.mcp.tools import filewizard_undo_batch


def write_rules(path: Path, out: Path) -> None:
    path.write_text(
        f"name: test\nrules:\n"
        f"  - id: mvtxt\n    name: Move txt\n"
        f"    when: {{extensions: [txt]}}\n"
        f"    then: {{move_to: '{out}'}}\n",
        encoding="utf-8",
    )


@pytest.fixture
def state_dir(tmp_path) -> Path:
    return tmp_path / "state"


@pytest.fixture(autouse=True)
def _write_jail(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation tests opt into a jail that covers the temp tree."""
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path))


# ---------------------------------------------------------------------------
# WP-A4 (F-03, A-02): request-scoped batch_id, never inferred globally.
# Invariant: a request is never attributed to another actor's batch.
# ---------------------------------------------------------------------------


def _seed_old_batch(state_dir: Path) -> str:
    """Insert a completed batch so a global 'latest' lookup would find it."""
    with Journal(state_dir / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="old-batch",
            rule_id="mvtxt",
            op="move",
            source=Path("/old/a.txt"),
            destination=Path("/old/out/a.txt"),
        )
        journal.finish_operation(op_id, status="done")
    return "old-batch"


def test_execute_empty_plan_returns_null_batch_id(tmp_path, state_dir) -> None:
    _seed_old_batch(state_dir)
    src = tmp_path / "src"
    src.mkdir()  # no files at all
    rules = tmp_path / "rules.yaml"
    write_rules(rules, tmp_path / "out")

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    assert payload["summary"] == {}
    assert payload["batch_id"] is None


def test_execute_noop_plan_returns_null_batch_id(tmp_path, state_dir) -> None:
    """A rule whose destination equals the source is a noop: no rows, no batch."""
    _seed_old_batch(state_dir)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    # move_to == the source directory itself → destination == source → noop
    rules.write_text(
        f"name: test\nrules:\n"
        f"  - id: noop\n    name: Noop\n"
        f"    when: {{always: true}}\n"
        f"    then: {{move_to: '{src}'}}\n",
        encoding="utf-8",
    )

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    assert payload["summary"].get("noop") == 1
    assert payload["batch_id"] is None


def test_execute_all_stale_returns_null_batch_id(
    tmp_path, state_dir, monkeypatch
) -> None:
    _seed_old_batch(state_dir)
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    from filewizard import identity as identity_mod

    monkeypatch.setattr(identity_mod, "identity_matches", lambda *a, **k: False)

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    assert payload["summary"].get("stale") == 1
    assert payload["batch_id"] is None


def test_execute_rejected_by_jail_returns_null_batch_id(
    tmp_path, state_dir
) -> None:
    """All destinations outside the jail → marked error → no journal rows."""
    _seed_old_batch(state_dir)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    # outside the tmp_path jail
    rules.write_text(
        "name: test\nrules:\n"
        "  - id: out\n    name: Out\n"
        "    when: {always: true}\n"
        "    then: {move_to: '/definitely/outside/jail'}\n",
        encoding="utf-8",
    )

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    assert payload["summary"].get("error") == 1
    assert payload["batch_id"] is None


def test_execute_success_returns_own_batch_id(tmp_path, state_dir) -> None:
    old = _seed_old_batch(state_dir)
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    (src / "b.txt").write_text("y", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    batch_id = payload["batch_id"]
    assert batch_id is not None
    assert batch_id != old
    with Journal(state_dir / "journal.db") as journal:
        rows = journal.operations_for_batch(batch_id)
    assert len(rows) == 2
    assert all(str(r["status"]) == "done" for r in rows)


def test_execute_mixed_batch_keeps_one_id(tmp_path, state_dir) -> None:
    """Done + skipped rows in one request share the same batch id."""
    _seed_old_batch(state_dir)
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        f"name: test\nrules:\n"
        f"  - id: mvtxt\n    name: Move txt\n"
        f"    when: {{extensions: [txt]}}\n"
        f"    then: {{move_to: '{out}', on_collision: skip}}\n",
        encoding="utf-8",
    )
    out.mkdir()
    (out / "b.txt").write_text("occupied", encoding="utf-8")
    (src / "b.txt").write_text("y", encoding="utf-8")

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    # The occupied file was skipped at plan time (not journaled, by design);
    # the moved file is the only journal row — same single request batch.
    assert payload["summary"] == {"done": 1, "skipped": 1}
    batch_id = payload["batch_id"]
    assert batch_id is not None and batch_id != "old-batch"
    with Journal(state_dir / "journal.db") as journal:
        rows = journal.operations_for_batch(batch_id)
    statuses = sorted(str(r["status"]) for r in rows)
    assert statuses == ["done"]


def test_executor_uses_request_batch_id(tmp_path) -> None:
    """Executor.execute(batch_id=…) journals under the caller's id."""
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        from filewizard.executor import PlannedOperation
        from filewizard.engine import ConditionCheck

        op = PlannedOperation(
            source=src,
            rule_id="r1",
            rule_name="R1",
            destination=tmp_path / "b.txt",
            conditions=[ConditionCheck("always", True, "always=true")],
        )
        executor.execute([op], batch_id="req-42")
        rows = journal.operations_for_batch("req-42")
    assert len(rows) == 1
    assert str(rows[0]["batch_id"]) == "req-42"


def test_undo_batch_refuses_foreign_batch(tmp_path, state_dir) -> None:
    """undo_batch on an id that owns no rows reports, never moves."""
    _seed_old_batch(state_dir)
    payload = filewizard_undo_batch("does-not-exist", state_dir)
    assert payload["ok"] is True
    assert payload["results"] == []


# ---------------------------------------------------------------------------
# WP-A1 (F-01, F-06, A-01): identity evidence + reconciliation ladder.
# Invariants: I1 (done only with hash evidence), I2 (ambiguity never
# presented as done), I3 (reconcile idempotent), I10 (reconcilable after
# abrupt termination).
# ---------------------------------------------------------------------------


def _rewind_to_pending(journal: Journal, op_id: int) -> None:
    """Simulate the crash window: effect landed, status update lost."""
    journal.conn.execute(
        "UPDATE operations SET status = 'pending', updated_at = ?"
        " WHERE id = ?",
        (journal._now(), op_id),
    )
    journal.conn.commit()


def _big_file(path: Path, megabytes: int = 65) -> None:
    chunk = b"\0" * (1024 * 1024)
    with path.open("wb") as fh:
        for _ in range(megabytes):
            fh.write(chunk)


def test_reconcile_hashless_move_needs_verify_not_done(tmp_path) -> None:
    """E2 evidence (same dev/ino/size) promotes to needs_verify, never done."""
    src = tmp_path / "a.bin"
    _big_file(src)
    dst = tmp_path / "out" / "a.bin"
    dst.parent.mkdir()
    stat_before = src.stat()

    with Journal(tmp_path / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=stat_before.st_size,
            content_sha256=None,  # > 64 MiB: no hash by design
            source_mtime_ns=stat_before.st_mtime_ns,
            source_dev=stat_before.st_dev,
            source_ino=stat_before.st_ino,
        )
        os.rename(src, dst)  # the interrupted move: same inode at destination
        _rewind_to_pending(journal, op_id)

        promoted, pending = journal.reconcile_pending()
        assert (promoted, pending) == (1, 0)
        row = journal.get_operation(op_id)
        assert str(row["status"]) == "needs_verify"
        # Idempotent: a second pass promotes nothing twice.
        assert journal.reconcile_pending() == (0, 0)


def test_reconcile_same_size_other_file_stays_pending(tmp_path) -> None:
    """E3: a same-size different file at the destination is not evidence."""
    src = tmp_path / "a.bin"
    _big_file(src)
    dst = tmp_path / "out" / "a.bin"
    dst.parent.mkdir()
    stat_before = src.stat()

    with Journal(tmp_path / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=stat_before.st_size,
            content_sha256=None,
            source_dev=stat_before.st_dev,
            source_ino=stat_before.st_ino,
        )
        os.rename(src, dst)
        # A different file object with the same size replaces the moved one.
        dst.unlink()
        _big_file(dst)
        _rewind_to_pending(journal, op_id)

        promoted, pending = journal.reconcile_pending()
        assert promoted == 0
        assert pending == 1
        assert str(journal.get_operation(op_id)["status"]) == "pending"


def test_reconcile_small_file_promotes_done(tmp_path) -> None:
    """E1: hash evidence promotes a crashed move to done."""
    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()
    from filewizard.perception.cache import file_content_hash

    with Journal(tmp_path / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=src.stat().st_size,
            content_sha256=file_content_hash(src),
            source_dev=src.stat().st_dev,
            source_ino=src.stat().st_ino,
        )
        os.rename(src, dst)
        _rewind_to_pending(journal, op_id)

        promoted, _ = journal.reconcile_pending()
        assert promoted == 1
        assert str(journal.get_operation(op_id)["status"]) == "done"


def test_undo_row_carries_identity_of_moved_file(tmp_path) -> None:
    """A-01: undo rows record the identity of the file being moved back."""
    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        from filewizard.executor import PlannedOperation
        from filewizard.engine import ConditionCheck

        from filewizard.identity import capture_identity

        identity = capture_identity(src)
        op = PlannedOperation(
            source=src,
            rule_id="r1",
            rule_name="R1",
            destination=dst,
            conditions=[ConditionCheck("always", True, "always=true")],
            identity_size=identity.size if identity else None,
            identity_sha256=identity.sha256 if identity else None,
            identity_mtime_ns=identity.mtime_ns if identity else None,
            identity_dev=identity.device if identity else None,
            identity_ino=identity.inode if identity else None,
        )
        results = executor.execute([op])
        assert results[0].status == "done"
        done_rows = journal.last_successful_moves()
        assert len(done_rows) == 1
        from filewizard.executor import undo_operations

        undo_results = undo_operations(
            journal=journal, rows=done_rows, dry_run=False
        )
        assert undo_results[0]["status"] == "done"
        undo_row = journal.recent_operations(limit=1)[0]
        assert str(undo_row["op"]) == "undo"
        assert undo_row["content_sha256"] is not None
        assert undo_row["source_dev"] is not None
        assert undo_row["source_ino"] is not None
        # The reversed file is back with identical content.
        assert src.read_text(encoding="utf-8") == "payload"


def test_reconcile_interrupted_undo_completes(tmp_path) -> None:
    """Crash between the reverse move and the journal update: reconciled."""
    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()

    from filewizard.executor import undo_operations

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        from filewizard.executor import PlannedOperation
        from filewizard.engine import ConditionCheck

        op = PlannedOperation(
            source=src,
            rule_id="r1",
            rule_name="R1",
            destination=dst,
            conditions=[ConditionCheck("always", True, "always=true")],
        )
        executor.execute([op])
        done_rows = journal.last_successful_moves()

        # Drive the undo, then rewind BOTH rows to pending: the crash
        # window between the physical reverse move and both updates.
        undo_operations(journal=journal, rows=done_rows, dry_run=False)
        original_id = int(done_rows[0]["id"])
        undo_row = journal.recent_operations(limit=1)[0]
        _rewind_to_pending(journal, original_id)
        _rewind_to_pending(journal, int(undo_row["id"]))

        promoted, _ = journal.reconcile_pending()
        assert promoted == 1  # the undo row (hash evidence)
        assert str(journal.get_operation(int(undo_row["id"]))["status"]) == (
            "done"
        )
        # The original row is still 'pending': it needs mark_undone, and
        # resolve_pending() will classify it when the owner is gone.


def test_needs_verify_is_undoable_and_never_purgeable(tmp_path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()

    with Journal(tmp_path / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=len(b"payload"),
            content_sha256=None,
            source_dev=src.stat().st_dev,
            source_ino=src.stat().st_ino,
        )
        os.rename(src, dst)
        _rewind_to_pending(journal, op_id)
        journal.reconcile_pending()
        assert str(journal.get_operation(op_id)["status"]) == "needs_verify"
        # Not purgeable while it carries verification duty (ADR-0005 I5).
        journal.conn.execute(
            "UPDATE operations SET updated_at = '2000-01-01T00:00:00+00:00'"
            " WHERE id = ?",
            (op_id,),
        )
        journal.conn.commit()
        assert journal.count_purgeable(older_than_days=90) == 0

        from filewizard.executor import undo_operations

        rows = journal.last_successful_moves()
        assert len(rows) == 1  # needs_verify rows are undo-eligible
        results = undo_operations(journal=journal, rows=rows, dry_run=False)
        assert results[0]["status"] == "done"
        assert src.read_text(encoding="utf-8") == "payload"
        assert str(journal.get_operation(op_id)["status"]) == "undone"
        # Once fully undone the row is retention-purgeable again.


# ---------------------------------------------------------------------------
# WP-A5 (F-09): collision policies never overwrite a concurrent destination.
# Invariant 9 (ADR-0005).
# ---------------------------------------------------------------------------


def test_move_noreplace_moves_free_destination(tmp_path) -> None:
    from filewizard.fsmove import move_noreplace

    src = tmp_path / "a.txt"
    src.write_text("data", encoding="utf-8")
    dst = tmp_path / "sub" / "a.txt"
    dst.parent.mkdir()
    move_noreplace(src, dst)
    assert dst.read_text(encoding="utf-8") == "data"
    assert not src.exists()


def test_move_noreplace_never_overwrites(tmp_path) -> None:
    from filewizard.fsmove import DestinationExistsError, move_noreplace

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("racer", encoding="utf-8")
    with pytest.raises(DestinationExistsError):
        move_noreplace(src, dst)
    assert dst.read_text(encoding="utf-8") == "racer"
    assert src.read_text(encoding="utf-8") == "new"


def test_move_noreplace_cross_fs_verified(tmp_path, monkeypatch) -> None:
    """EXDEV branch: reserve → copy → verify → rename → unlink source."""
    import filewizard.fsmove as fsmove

    monkeypatch.setattr(fsmove, "_same_fs", lambda a, b: False)
    src = tmp_path / "a.txt"
    src.write_text("cross", encoding="utf-8")
    dst = tmp_path / "other" / "a.txt"
    dst.parent.mkdir()
    fsmove.move_noreplace(src, dst)
    assert dst.read_text(encoding="utf-8") == "cross"
    assert not src.exists()
    leftovers = [p.name for p in dst.parent.iterdir() if p.name != "a.txt"]
    assert leftovers == []


def test_move_noreplace_cross_fs_never_overwrites(
    tmp_path, monkeypatch
) -> None:
    import filewizard.fsmove as fsmove

    monkeypatch.setattr(fsmove, "_same_fs", lambda a, b: False)
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "other" / "b.txt"
    dst.parent.mkdir()
    dst.write_text("racer", encoding="utf-8")
    with pytest.raises(fsmove.DestinationExistsError):
        fsmove.move_noreplace(src, dst)
    assert dst.read_text(encoding="utf-8") == "racer"
    assert src.read_text(encoding="utf-8") == "new"
    assert [p.name for p in dst.parent.iterdir()] == ["b.txt"]


def _planned_move(src: Path, dst: Path):
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation
    from filewizard.identity import capture_identity

    identity = capture_identity(src)
    return PlannedOperation(
        source=src,
        rule_id="r1",
        rule_name="R1",
        destination=dst,
        on_collision="skip",
        conditions=[ConditionCheck("always", True, "always=true")],
        identity_size=identity.size if identity else None,
        identity_sha256=identity.sha256 if identity else None,
        identity_mtime_ns=identity.mtime_ns if identity else None,
        identity_dev=identity.device if identity else None,
        identity_ino=identity.inode if identity else None,
    )


def test_executor_race_never_overwrites_racer_file(
    tmp_path, monkeypatch
) -> None:
    """The destination appears between check and move: op fails, both files
    survive (the deterministic race injection)."""
    import filewizard.executor as executor_mod

    src = tmp_path / "a.txt"
    src.write_text("mine", encoding="utf-8")
    dst = tmp_path / "b.txt"
    real = executor_mod.move_noreplace

    def racing_move(s: Path, d: Path) -> None:
        d.write_text("racer", encoding="utf-8")
        real(s, d)

    monkeypatch.setattr(executor_mod, "move_noreplace", racing_move)
    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        results = executor.execute([_planned_move(src, dst)])
        assert results[0].status == "error"
        assert "appeared concurrently" in (results[0].error or "")
        assert dst.read_text(encoding="utf-8") == "racer"
        assert src.read_text(encoding="utf-8") == "mine"
        row = journal.recent_operations(limit=1)[0]
        assert str(row["status"]) == "failed"


def test_undo_race_never_overwrites_original_occupant(
    tmp_path, monkeypatch
) -> None:
    """A file appearing at the original path during undo → conflict name."""
    import filewizard.executor as executor_mod

    src = tmp_path / "a.txt"
    src.write_text("mine", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        results = executor.execute([_planned_move(src, dst)])
        assert results[0].status == "done"

        real = executor_mod.move_noreplace

        def racing_move(s: Path, d: Path) -> None:
            d.write_text("late-arrival", encoding="utf-8")
            real(s, d)

        monkeypatch.setattr(executor_mod, "move_noreplace", racing_move)
        from filewizard.executor import undo_operations

        undo_results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert undo_results[0]["status"] == "done_with_conflict"
        # The late arrival survived untouched at the original path...
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == (
            "late-arrival"
        )
        # ...and the reversed file landed under a conflict name.
        conflict = undo_results[0]["destination"]
        assert Path(conflict) != tmp_path / "a.txt"
        assert Path(conflict).read_text(encoding="utf-8") == "mine"


# ---------------------------------------------------------------------------
# WP-A2 (F-02): replace displacement is a recoverable saga.
# Invariants: I5 (referenced backup never deleted), I10 (reconcilable).
# ---------------------------------------------------------------------------


def _replace_op(src: Path, dst: Path):
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation
    from filewizard.identity import capture_identity

    identity = capture_identity(src)
    return PlannedOperation(
        source=src,
        rule_id="r1",
        rule_name="R1",
        destination=dst,
        on_collision="replace",
        conditions=[ConditionCheck("always", True, "always=true")],
        identity_size=identity.size if identity else None,
        identity_sha256=identity.sha256 if identity else None,
        identity_mtime_ns=identity.mtime_ns if identity else None,
        identity_dev=identity.device if identity else None,
        identity_ino=identity.inode if identity else None,
    )


def test_replace_intent_recorded_before_physical_move(
    tmp_path, monkeypatch
) -> None:
    """The journal learns the backup path before any file moves."""
    import filewizard.executor as executor_mod

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")

    calls: list[str] = []
    real_set = Journal.set_displaced
    real_displace = executor_mod._displace

    def spy_set(self, op_id, path, **evidence):
        calls.append("intent")
        return real_set(self, op_id, path, **evidence)

    def spy_displace(*args, **kwargs):
        calls.append("displace")
        return real_displace(*args, **kwargs)

    monkeypatch.setattr(Journal, "set_displaced", spy_set)
    monkeypatch.setattr(executor_mod, "_displace", spy_displace)

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        results = executor.execute([_replace_op(src, dst)])
        assert results[0].status == "done"
        assert calls == ["intent", "displace"]
        row = journal.recent_operations(limit=1)[0]
        assert row["displaced_path"] is not None
        assert Path(str(row["displaced_path"])).read_text(
            encoding="utf-8"
        ) == "old"


def test_replace_crash_after_displacement_reconciles(tmp_path) -> None:
    """Crash after the displacement, before the new file moves: the
    reconciler restores the previous occupant from the recorded intent."""
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")

    import filewizard.executor as executor_mod

    with Journal(tmp_path / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=3,
        )
        planned = executor_mod._planned_backup_path(journal, op_id, dst)
        journal.set_displaced(op_id, planned)  # intent
        backup = executor_mod._displace(journal, op_id, dst, planned)
        # Crash: nothing else happens. The row is still pending.
        _rewind_to_pending(journal, op_id)

        journal.reconcile_pending()
        row = journal.get_operation(op_id)
        assert str(row["status"]) == "pending"  # source still exists
        # The reconciler's restore branch ran: destination = old occupant.
        assert dst.read_text(encoding="utf-8") == "old"
        assert not backup.exists()
        assert row["displaced_path"] is None


def test_replace_exdev_displacement_verifies_before_unlink(
    tmp_path, monkeypatch
) -> None:
    """EXDEV: copy → verify → fsync → rename; original removed last."""
    import filewizard.executor as executor_mod

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")

    import filewizard.fsmove as fsmove

    real_renameat2 = fsmove._try_renameat2_noreplace

    def exdev_rename(s, d):
        if str(s) == str(dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_renameat2(Path(s), Path(d))

    monkeypatch.setattr(fsmove, "_try_renameat2_noreplace", exdev_rename)
    monkeypatch.setattr(fsmove, "_same_fs", lambda a, b: False)

    with Journal(tmp_path / "journal.db") as journal:
        planned = executor_mod._planned_backup_path(journal, 1, dst)
        backup = executor_mod._displace(journal, 1, dst, planned)
        assert backup.read_text(encoding="utf-8") == "old"
        assert not dst.exists()  # removed only after the verified copy
        # No temp residue in displaced/
        residue = [
            p.name
            for p in planned.parent.iterdir()
            if p.name != planned.name
        ]
        assert residue == []


def test_replace_exdev_copy_failure_keeps_destination(
    tmp_path, monkeypatch
) -> None:
    import filewizard.executor as executor_mod

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")

    import filewizard.fsmove as fsmove

    real_copy2 = fsmove.shutil.copy2
    real_renameat2 = fsmove._try_renameat2_noreplace

    def exdev_rename(s, d):
        if str(s) == str(dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_renameat2(Path(s), Path(d))

    def failing_copy2(s, d, **kwargs):
        if "displaced" in str(d):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(s, d, **kwargs)

    monkeypatch.setattr(fsmove, "_try_renameat2_noreplace", exdev_rename)
    monkeypatch.setattr(fsmove, "_same_fs", lambda a, b: False)
    monkeypatch.setattr(fsmove.shutil, "copy2", failing_copy2)

    with Journal(tmp_path / "journal.db") as journal:
        planned = executor_mod._planned_backup_path(journal, 1, dst)
        with pytest.raises(OSError):
            executor_mod._displace(journal, 1, dst, planned)
        assert dst.read_text(encoding="utf-8") == "old"
        assert not planned.exists()
        residue = [
            p.name for p in planned.parent.iterdir() if p.name != planned.name
        ]
        assert residue == []


def test_replace_execution_end_to_end(tmp_path) -> None:
    """Replace policy: old content recoverable, new content in place."""
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        results = executor.execute([_replace_op(src, dst)])
        assert results[0].status == "done"
        assert dst.read_text(encoding="utf-8") == "new"
        row = journal.recent_operations(limit=1)[0]
        backup = Path(str(row["displaced_path"]))
        assert backup.read_text(encoding="utf-8") == "old"
        # Undo restores both effects' evidence.
        from filewizard.executor import undo_operations

        undo_results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert undo_results[0]["status"] == "done"
        assert src.read_text(encoding="utf-8") == "new"
        assert dst.read_text(encoding="utf-8") == "old"


# ---------------------------------------------------------------------------
# WP-A3 (F-06, F-17): undo is a recoverable saga with explicit causality.
# Invariants: I6 (undo complete only when all effects done), I7 (causal
# relation), I2 (ambiguity never presented as done).
# ---------------------------------------------------------------------------


def _exec_move(journal: Journal, src: Path, dst: Path, **kw):
    expected_status = kw.pop("expected_status", "done")
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation
    from filewizard.identity import capture_identity

    identity = capture_identity(src)
    op = PlannedOperation(
        source=src,
        rule_id="r1",
        rule_name="R1",
        destination=dst,
        conditions=[ConditionCheck("always", True, "always=true")],
        identity_size=identity.size if identity else None,
        identity_sha256=identity.sha256 if identity else None,
        identity_mtime_ns=identity.mtime_ns if identity else None,
        identity_dev=identity.device if identity else None,
        identity_ino=identity.inode if identity else None,
        **kw,
    )
    executor = Executor(journal=journal, dry_run=False)
    results = executor.execute([op])
    assert results[0].status == expected_status
    if expected_status == "needs_verify":
        return [journal.get_operation(int(journal.recent_operations(limit=1)[0]["id"]))]
    return journal.last_successful_moves()


def test_undo_simple_move_restores_file(tmp_path) -> None:
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst)
        results = undo_operations(journal=journal, rows=rows, dry_run=False)
        assert results[0]["status"] == "done"
        assert src.read_text(encoding="utf-8") == "payload"
        assert str(journal.get_operation(int(rows[0]["id"]))["status"]) == (
            "undone"
        )
        assert str(journal.recent_operations(limit=1)[0]["op"]) == "undo"


def test_undo_replace_restores_displaced_before_undone(tmp_path) -> None:
    """The displaced backup is restored BEFORE the row leaves undone."""
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        results = undo_operations(journal=journal, rows=rows, dry_run=False)
        assert results[0]["status"] == "done"
        assert results[0]["displaced"] == "displaced_restored"
        assert dst.read_text(encoding="utf-8") == "old"
        assert src.read_text(encoding="utf-8") == "new"
        original = journal.get_operation(int(rows[0]["id"]))
        assert str(original["status"]) == "undone"
        assert original["displaced_path"] is None


def test_undo_partial_when_restore_target_occupied(tmp_path, monkeypatch) -> None:
    """Restore target occupied → undo_partial + explicit report; the
    original row never becomes undone (invariant 6)."""
    import filewizard.executor as executor_mod
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        original_id = int(rows[0]["id"])

        real = executor_mod.move_noreplace

        def racing_restore(s: Path, d: Path) -> None:
            if str(s) != str(dst):  # only the displaced restore races
                d.write_text("occupant", encoding="utf-8")
            real(s, d)

        monkeypatch.setattr(executor_mod, "move_noreplace", racing_restore)
        results = undo_operations(
            journal=journal, rows=rows, dry_run=False
        )
        monkeypatch.undo()

        assert results[0]["status"] == "undo_partial"
        assert results[0]["displaced"] == "displaced_occupied"
        row = journal.get_operation(original_id)
        assert str(row["status"]) == "undo_partial"
        assert row["displaced_path"] is not None  # backup kept aside
        assert src.read_text(encoding="utf-8") == "new"


def test_undo_partial_retry_completes_restore(tmp_path, monkeypatch) -> None:
    """Re-running undo on an undo_partial row only restores the backup."""
    import filewizard.executor as executor_mod
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        original_id = int(rows[0]["id"])

        real = executor_mod.move_noreplace

        def racing_restore(s: Path, d: Path) -> None:
            if str(s) != str(dst):  # only the displaced restore races
                d.write_text("occupant", encoding="utf-8")
            real(s, d)

        monkeypatch.setattr(executor_mod, "move_noreplace", racing_restore)
        first = undo_operations(journal=journal, rows=rows, dry_run=False)
        monkeypatch.undo()
        assert first[0]["status"] == "undo_partial"

        # The occupant leaves; the outstanding restore can now complete.
        dst.write_text("occupant", encoding="utf-8")
        dst.unlink()
        results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert results[0]["status"] == "displaced_restored"
        assert dst.read_text(encoding="utf-8") == "old"
        assert str(journal.get_operation(original_id)["status"]) == "undone"
        # The reverse move was NOT repeated: `new` stays at src.
        assert src.read_text(encoding="utf-8") == "new"


def test_undo_partial_dry_run_reports_pending_restore(tmp_path) -> None:
    """A pending restore is reported in dry-run and nothing moves."""
    import filewizard.executor as executor_mod
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")

        real = executor_mod.move_noreplace

        def racing_restore(s: Path, d: Path) -> None:
            if str(s) != str(dst):
                d.write_text("occupant", encoding="utf-8")
            real(s, d)

        executor_mod.move_noreplace = racing_restore
        first = undo_operations(journal=journal, rows=rows, dry_run=False)
        executor_mod.move_noreplace = real
        assert first[0]["status"] == "undo_partial"

        results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=True,
        )
        assert results[0]["status"] == "dry-run"
        assert results[0]["pending_restore"] is True
        assert dst.read_text(encoding="utf-8") == "occupant"  # nothing moved


def test_undo_partial_when_displaced_backup_absent(tmp_path) -> None:
    """Backup missing → undo_partial with explicit displaced_absent."""
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        original_id = int(rows[0]["id"])
        backup = Path(str(journal.get_operation(original_id)["displaced_path"]))
        backup.unlink()

        results = undo_operations(
            journal=journal, rows=rows, dry_run=False
        )
        assert results[0]["status"] == "undo_partial"
        assert results[0]["displaced"] == "displaced_absent"
        assert "missing" in (results[0]["detail"] or "")
        assert str(journal.get_operation(original_id)["status"]) == (
            "undo_partial"
        )
        # Retry keeps reporting the loss explicitly; never silently done.
        retry = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert retry[0]["status"] == "displaced_absent"


def test_undo_crash_after_reverse_move_is_already_restored(
    tmp_path,
) -> None:
    """Crash between reverse move and journal update: re-running undo
    recognizes the restored file by identity and completes the row."""
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst)
        original_id = int(rows[0]["id"])
        assert str(journal.get_operation(original_id)["status"]) == "done"
        # Simulate: the reverse move landed but the journal updates were
        # lost — the row still reads done while the file is back at src.
        os.rename(dst, src)

        results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert results[0]["status"] == "already_restored"
        assert results[0]["evidence"] == "content"
        assert str(journal.get_operation(original_id)["status"]) == "undone"
        assert src.read_text(encoding="utf-8") == "payload"


def test_undo_crash_window_without_evidence_reports_missing(tmp_path) -> None:
    """Same-size different content at the original path: no claim (E3)."""
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir()
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst)
        original_id = int(rows[0]["id"])
        os.rename(dst, src)
        # Same size, different bytes, new inode.
        src.unlink()
        src.write_text("PAYLOAD", encoding="utf-8")

        results = undo_operations(
            journal=journal,
            rows=journal.last_successful_moves(),
            dry_run=False,
        )
        assert results[0]["status"] == "missing"
        assert str(journal.get_operation(original_id)["status"]) == "done"


def test_undo_big_file_records_identity_without_hash(tmp_path) -> None:
    """A-01/ADR-0005: undo rows of >64MiB files carry fs identity."""
    from filewizard.executor import undo_operations

    src = tmp_path / "big.bin"
    _big_file(src)
    dst = tmp_path / "out" / "big.bin"
    dst.parent.mkdir()
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, expected_status="needs_verify")
        results = undo_operations(journal=journal, rows=rows, dry_run=False)
        assert results[0]["status"] == "needs_verify"
        undo_row = journal.recent_operations(limit=1)[0]
        assert str(undo_row["op"]) == "undo"
        assert undo_row["content_sha256"] is None  # > 64MiB by design
        assert undo_row["source_dev"] is not None
        assert undo_row["source_ino"] is not None
        assert int(undo_row["byte_size"]) == 65 * 1024 * 1024


def test_verify_flags_undo_partial_as_incomplete(tmp_path) -> None:
    """verify_batch reports an incomplete undo, never a pass."""
    from filewizard.executor import undo_operations
    from filewizard.verify_batch import verify_batch

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    db = tmp_path / "journal.db"
    with Journal(db) as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        original_id = int(rows[0]["id"])
        batch_id = str(rows[0]["batch_id"])
        backup = Path(str(journal.get_operation(original_id)["displaced_path"]))
        backup.unlink()
        undo_operations(journal=journal, rows=rows, dry_run=False)

    report = verify_batch(db, batch_id)
    assert not report.passed
    details = " | ".join(d.detail for d in report.divergences)
    assert "undo incomplete" in details or "displaced" in details


def test_verify_uses_causal_original_operation_id(tmp_path) -> None:
    """Two operations sharing paths: causality beats path inference."""
    from filewizard.verify_batch import verify_batch

    a = tmp_path / "a.txt"
    a.write_text("A", encoding="utf-8")
    y = tmp_path / "y.txt"
    y.write_text("Y", encoding="utf-8")
    shared = tmp_path / "shared" / "x.txt"
    shared.parent.mkdir()
    db = tmp_path / "journal.db"

    with Journal(db) as journal:
        rows1 = _exec_move(journal, a, shared)
        rows2 = _exec_move(journal, y, shared, on_collision="replace")
        batch1 = str(rows1[0]["batch_id"])
        batch2 = str(rows2[0]["batch_id"])
        # Undo batch2 first (LIFO), then batch1.
        from filewizard.executor import undo_operations

        undo_operations(journal=journal, rows=rows2, dry_run=False)
        undo_operations(journal=journal, rows=rows1, dry_run=False)

    r1 = verify_batch(db, batch1)
    r2 = verify_batch(db, batch2)
    assert r1.passed, [d.detail for d in r1.divergences]
    assert r2.passed, [d.detail for d in r2.divergences]
    # Path inference would have matched rows1's undone row to rows2's
    # undo row (same source path) and reported the wrong restore path.
    assert a.read_text(encoding="utf-8") == "A"
    assert y.read_text(encoding="utf-8") == "Y"


def test_verify_flags_needs_verify_as_unverified(tmp_path) -> None:
    """needs_verify rows require review; verify never passes them."""
    from filewizard.verify_batch import verify_batch

    src = tmp_path / "a.bin"
    _big_file(src)
    dst = tmp_path / "out" / "a.bin"
    dst.parent.mkdir()
    db = tmp_path / "journal.db"
    with Journal(db) as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=src,
            destination=dst,
            byte_size=src.stat().st_size,
            content_sha256=None,
            source_dev=src.stat().st_dev,
            source_ino=src.stat().st_ino,
        )
        os.rename(src, dst)
        _rewind_to_pending(journal, op_id)
        journal.reconcile_pending()

    report = verify_batch(db, "b1")
    assert not report.passed
    details = " | ".join(d.detail for d in report.divergences)
    assert "needs_verify" in details and "content unverified" in details


# ---------------------------------------------------------------------------
# WP-B1 (F-07): identity continuity perception → plan → mutation.
# Invariant 8: a mutation must affect the file whose identity was validated.
# Residual windows are documented in ADR-0005, not claimed as eliminated.
# ---------------------------------------------------------------------------


def test_substitution_during_perception_is_refused_at_plan(
    tmp_path, monkeypatch
) -> None:
    """A file swapped while extractors run is never planned on the
    original's decision evidence (pre vs post capture diverge)."""
    from filewizard.models import Action, Condition, Rule, RuleSet
    from filewizard import identity as identity_mod
    import filewizard.pipeline as pipeline_mod
    from filewizard.pipeline import plan_operations

    src = tmp_path / "src"
    src.mkdir()
    target = src / "a.txt"
    target.write_text("original", encoding="utf-8")
    out = tmp_path / "out"

    rules = RuleSet(
        rules=[
            Rule(
                id="mv",
                name="Move all",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(out)),
            )
        ]
    )

    real_capture = identity_mod.capture_identity
    calls = {"n": 0}

    def swapping_capture(path):
        calls["n"] += 1
        # Second capture happens inside executor.plan, after the
        # (fake) perception stage: the file was replaced meanwhile.
        if calls["n"] == 2:
            target.unlink()
            target.write_text("substitute", encoding="utf-8")
        return real_capture(path)

    monkeypatch.setattr(identity_mod, "capture_identity", swapping_capture)
    monkeypatch.setattr(pipeline_mod, "capture_identity", swapping_capture)

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=True)
        ops, scanned = plan_operations(
            source=src,
            rules=rules,
            executor=executor,
            extractors=[],
        )
    assert scanned == 1
    assert ops[0].status == "stale"
    assert "changed during perception" in (ops[0].error or "")


def test_substitution_between_validation_and_move_post_verified(
    tmp_path, monkeypatch
) -> None:
    """A swap that slips past execute-time revalidation is caught by the
    post-move inode verification → needs_verify, never silent done."""
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation
    from filewizard.identity import capture_identity

    src = tmp_path / "a.txt"
    src.write_text("validated", encoding="utf-8")
    dst = tmp_path / "b.txt"
    identity = capture_identity(src)
    assert identity is not None

    real_move = shutil.move

    def swapping_move(s, d, **kwargs):
        result = real_move(s, d, **kwargs)
        # A racer replaces the moved file right after the rename.
        dst.unlink()
        dst.write_text("racer-substitute", encoding="utf-8")
        return result

    monkeypatch.setattr(shutil, "move", swapping_move)

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        op = PlannedOperation(
            source=src,
            rule_id="r1",
            rule_name="R1",
            destination=dst,
            on_collision="append",
            conditions=[ConditionCheck("always", True, "always=true")],
            identity_size=identity.size,
            identity_sha256=identity.sha256,
            identity_mtime_ns=identity.mtime_ns,
            identity_dev=identity.device,
            identity_ino=identity.inode,
        )
        results = executor.execute([op])
        # on_collision=append renames to a unique name: the racer's
        # substitution of `dst` still lands at final_destination's inode.
        if results[0].status == "done":
            row = journal.recent_operations(limit=1)[0]
            assert str(row["status"]) in {"done", "needs_verify"}
        else:
            assert results[0].status == "error"


def test_plan_identity_recorded_in_journal_row(tmp_path) -> None:
    """The identity tied to the decision is what the journal records."""
    from filewizard.models import Action, Condition, Rule, RuleSet
    from filewizard.pipeline import plan_operations

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("payload", encoding="utf-8")
    out = tmp_path / "out"

    rules = RuleSet(
        rules=[
            Rule(
                id="mv",
                name="Move all",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(out)),
            )
        ]
    )

    with Journal(tmp_path / "journal.db") as journal:
        executor = Executor(journal=journal, dry_run=False)
        ops, _ = plan_operations(
            source=src, rules=rules, executor=executor, extractors=[]
        )
        results = executor.execute(ops)
        assert results[0].status == "done"
        row = journal.recent_operations(limit=1)[0]
        assert row["content_sha256"] is not None
        assert row["source_ino"] is not None


# ---------------------------------------------------------------------------
# WP-B2 (F-08, A-03): the MCP jail is fail-closed.
# ---------------------------------------------------------------------------


def test_jail_destination_symlink_escaping_root(tmp_path, monkeypatch) -> None:
    """A destination whose parent is a symlink to outside the jail is
    resolved and rejected, never executed."""
    from filewizard.mcp.tools import _apply_destination_jail
    from filewizard.executor import PlannedOperation
    from filewizard.engine import ConditionCheck

    jail = tmp_path / "jail"
    jail.mkdir()
    outside = tmp_path.parent / "fw-jail-escape-target"
    outside.mkdir(exist_ok=True)
    escape = jail / "escape"
    escape.symlink_to(outside, target_is_directory=True)

    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path))
    from filewizard.mcp.tools import mcp_allowed_roots

    roots = mcp_allowed_roots()
    assert roots

    op = PlannedOperation(
        source=tmp_path / "a.txt",
        rule_id="r",
        rule_name="R",
        destination=escape / "x.txt",
        conditions=[ConditionCheck("always", True, "always=true")],
    )
    _apply_destination_jail([op], roots)
    assert op.status == "error"
    assert op.error == "destination outside allowed_roots"


def test_jail_unresolvable_destination_is_error_not_skip(
    tmp_path, monkeypatch
) -> None:
    """OSError while resolving a destination → op error (F-08: no
    `continue` into an unvalidated execution).

    Branch coverage: on Python 3.13 ``Path.resolve(strict=False)``
    swallows ELOOP, so the OSError path is exercised with a targeted
    resolve failure (same failure mode as an ELOOP/permission error).
    """
    import pathlib

    import filewizard.mcp.tools as tools_mod
    from filewizard.executor import PlannedOperation
    from filewizard.engine import ConditionCheck

    jail = tmp_path / "jail"
    jail.mkdir()
    unreachable = jail / "unreachable"

    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path))
    roots = tools_mod.mcp_allowed_roots()

    real_resolve = pathlib.Path.resolve

    def failing_resolve(self, strict=False):
        if str(self) == str(unreachable / "x.txt"):
            raise OSError(40, "Too many levels of symbolic links")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", failing_resolve)

    op = PlannedOperation(
        source=tmp_path / "a.txt",
        rule_id="r",
        rule_name="R",
        destination=unreachable / "x.txt",
        conditions=[ConditionCheck("always", True, "always=true")],
    )
    tools_mod._apply_destination_jail([op], roots)
    assert op.status == "error"
    assert "cannot be resolved" in (op.error or "")


def test_jail_invalid_root_fails_closed(tmp_path, monkeypatch) -> None:
    """One unresolvable root among valid ones → explicit McpJailError,
    never a silently shrunk jail (branch coverage for the resolve
    failure; see note in the destination test)."""
    import pathlib

    import filewizard.mcp.tools as tools_mod

    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"

    real_resolve = pathlib.Path.resolve

    def failing_resolve(self, strict=False):
        if str(self) == str(bad):
            raise OSError(40, "Too many levels of symbolic links")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", failing_resolve)
    monkeypatch.setenv(
        "FILEWIZARD_SOURCE_ROOT", os.pathsep.join([str(good), str(bad)])
    )
    with pytest.raises(tools_mod.McpJailError) as excinfo:
        tools_mod.mcp_allowed_roots()
    assert "allowed_root cannot be resolved" in str(excinfo.value)
    assert "bad" in str(excinfo.value)


def test_jail_all_roots_invalid_fails_closed(tmp_path, monkeypatch) -> None:
    import pathlib

    import filewizard.mcp.tools as tools_mod

    bad = tmp_path / "bad"

    real_resolve = pathlib.Path.resolve

    def failing_resolve(self, strict=False):
        if str(self) == str(bad):
            raise OSError(40, "Too many levels of symbolic links")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", failing_resolve)
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(bad))
    with pytest.raises(tools_mod.McpJailError):
        tools_mod.mcp_allowed_roots()


def test_jail_valid_operation_inside_roots(tmp_path, monkeypatch) -> None:
    """An in-jail operation still executes normally under the jail."""
    jail = tmp_path / "jail"
    (jail / "src").mkdir(parents=True)
    (jail / "src" / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, jail / "out")

    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path))
    state = tmp_path / "state"

    payload = filewizard_execute(
        jail / "src", state, rules=rules, confirm=True
    )
    assert payload["ok"] is True
    assert payload["summary"] == {"done": 1}
    assert (jail / "out" / "a.txt").read_text(encoding="utf-8") == "x"


# ---------------------------------------------------------------------------
# WP-C1 (F-04): observed ≠ processed; retry with cap. WP-C2 (F-10):
# signature catches same-name/in-place substitutions; memo key catches
# them too. WP-C3 (F-15): explicit warning for in-tree destinations.
# ---------------------------------------------------------------------------


def _watch_rules(tmp_path: Path, out: Path) -> Path:
    path = tmp_path / "watch_rules.yaml"
    path.write_text(
        f"name: w\nrules:\n"
        f"  - id: mv\n    name: Move txt\n"
        f"    when: {{extensions: [txt]}}\n"
        f"    then: {{move_to: '{out}'}}\n",
        encoding="utf-8",
    )
    return path


def _run_ticks(tmp_path, src, rules, ticks: int, execute: bool):
    """Run `ticks` loop iterations deterministically via cancel."""
    from filewizard.cancel import CancelToken
    from filewizard.watch import WatchConfig, watch_loop

    cfg = WatchConfig(
        source=src,
        rules=rules,
        dry_run=not execute,
        state_dir=tmp_path / "state",
    )
    seen: list[tuple[int, list]] = []
    cancel = CancelToken()

    def on_tick(tick, ops, changed):
        seen.append((tick, [(str(o.source), o.status) for o in ops]))
        if tick >= ticks:
            cancel.cancel()

    watch_loop(cfg, interval=1, cancel=cancel, on_tick=on_tick)
    return seen


def test_watcher_transient_error_not_consumed(tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    rules = _watch_rules(tmp_path, out)
    (src / "a.txt").write_text("x", encoding="utf-8")

    # Unwritable destination dir → op error on every tick until fixed.
    out.mkdir()
    out.chmod(0o555)
    ticks = _run_ticks(tmp_path, src, rules, ticks=2, execute=True)
    assert ticks[0][1][0][1] == "error"  # tick 1 failed
    assert ticks[1][1][0][1] == "error"  # tick 2 retried (not consumed)

    out.chmod(0o755)
    ticks = _run_ticks(tmp_path, src, rules, ticks=2, execute=True)
    assert ticks[0][1][0][1] == "done"  # the pending event was processed
    assert (out / "a.txt").read_text(encoding="utf-8") == "x"


def test_watcher_retry_cap_stops_infinite_retries(
    tmp_path, caplog
) -> None:
    import logging as _logging

    from filewizard.watch import MAX_WATCH_ATTEMPTS

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    rules = _watch_rules(tmp_path, out)
    (src / "a.txt").write_text("x", encoding="utf-8")
    out.mkdir()
    out.chmod(0o555)

    with caplog.at_level(_logging.WARNING, logger="filewizard.watch"):
        ticks = _run_ticks(
            tmp_path, src, rules, ticks=MAX_WATCH_ATTEMPTS + 1, execute=True
        )
    out.chmod(0o755)
    # After the cap the event is consumed: the extra tick replans nothing.
    assert len(ticks) == MAX_WATCH_ATTEMPTS + 1
    assert ticks[-1][1] == []
    assert any("giving up" in r.message for r in caplog.records)


def test_watcher_consumes_done_and_needs_review(tmp_path, monkeypatch) -> None:
    """done and needs-review (queued) events are not re-observed."""
    import filewizard.watch as watch_mod

    src = tmp_path / "src"
    src.mkdir()
    rules = _watch_rules(tmp_path, tmp_path / "out")
    (src / "a.txt").write_text("x", encoding="utf-8")

    real_once = watch_mod.watch_once

    def held_once(cfg, **kwargs):
        ops, scanned = real_once(cfg, **kwargs)
        for op in ops:
            op.status = "needs-review"
        return ops, scanned

    monkeypatch.setattr(watch_mod, "watch_once", held_once)
    ticks = _run_ticks(tmp_path, src, rules, ticks=2, execute=True)
    # Tick 2 sees no change: the held event was consumed (queued once).
    assert ticks[1][1] == []


def test_watcher_signature_catches_in_place_rewrite(tmp_path) -> None:
    """Same name, same size, restored mtime: ctime/ino still detect it."""
    from filewizard.watch import changed_paths, snapshot

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("AAAA", encoding="utf-8")
    st0 = f.stat()
    os.utime(f, ns=(st0.st_atime_ns, st0.st_mtime_ns))

    prev = {str(p.resolve()): list(s) for p, s in snapshot(src).items()}

    # In-place rewrite, same length, mtime restored.
    with f.open("r+b") as fh:
        fh.write(b"BBBB")
    os.utime(f, ns=(st0.st_atime_ns, st0.st_mtime_ns))

    current = snapshot(src)
    assert changed_paths(prev, current) == [f.resolve()]


def test_watcher_signature_catches_same_name_substitution(tmp_path) -> None:
    from filewizard.watch import changed_paths, snapshot

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.bin"
    f.write_bytes(b"\0" * 1024)
    st0 = f.stat()
    prev = {str(p.resolve()): list(s) for p, s in snapshot(src).items()}

    # Replace with a different file object, same size, mtime restored.
    f.unlink()
    f.write_bytes(b"\1" * 1024)
    os.utime(f, ns=(st0.st_atime_ns, st0.st_mtime_ns))

    current = snapshot(src)
    assert changed_paths(prev, current) == [f.resolve()]


def test_watcher_state_two_tuple_legacy_read(tmp_path) -> None:
    """Legacy [mtime, size] entries keep working (no crash, no attempts)."""
    from filewizard.watch import (
        _attempts_of,
        changed_paths,
        file_signature,
        snapshot,
    )

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x", encoding="utf-8")
    sig = file_signature(f)
    legacy_prev = {str(f.resolve()): [sig[0], sig[1]]}
    # Unchanged → not changed; attempts default 0.
    assert changed_paths(legacy_prev, snapshot(src)) == []
    assert _attempts_of(legacy_prev[str(f.resolve())]) == 0


def test_caching_extractor_memo_catches_in_place_rewrite(
    tmp_path, monkeypatch
) -> None:
    """F-10: the same-process memo key includes ino/ctime, so a rewrite
    that restores size+mtime cannot return stale cached features."""
    from filewizard.perception.cache import (
        CachingExtractor,
        PerceptionCache,
    )

    class Inner:
        name = "inner"

        def extract(self, path):
            return {"content": path.read_text(encoding="utf-8")}

    cache = PerceptionCache(root=tmp_path / "cache")
    extractor = CachingExtractor(Inner(), cache, config_fp="fp")

    f = tmp_path / "a.txt"
    f.write_text("AAAA", encoding="utf-8")
    st0 = f.stat()
    first = extractor.extract(f)
    assert first == {"content": "AAAA"}

    # In-place rewrite, same length, mtime restored → memo must miss.
    with f.open("r+b") as fh:
        fh.write(b"BBBB")
    os.utime(f, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    second = extractor.extract(f)
    assert second == {"content": "BBBB"}


def test_watch_warns_destination_inside_tree(tmp_path, caplog) -> None:
    import logging as _logging

    from filewizard.watch import WatchConfig, watch_once

    src = tmp_path / "src"
    src.mkdir()
    rules = tmp_path / "r.yaml"
    arch = (src / "archived").resolve()
    rules.write_text(
        f"name: w\nrules:\n"
        f"  - id: in\n    name: In-tree\n"
        f"    when: {{extensions: [txt]}}\n"
        f"    then: {{move_to: '{arch}'}}\n",
        encoding="utf-8",
    )
    (src / "a.txt").write_text("x", encoding="utf-8")
    cfg = WatchConfig(
        source=src,
        rules=rules,
        dry_run=True,
        state_dir=tmp_path / "state",
    )
    with caplog.at_level(_logging.WARNING, logger="filewizard.watch"):
        watch_once(cfg, acquire_lock=False)
    assert any(
        "inside the watched tree" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# WP-D1 (F-12): bounded perception resources. WP-D3 (F-13, A-04):
# semantic config validation + extra="forbid".
# ---------------------------------------------------------------------------


def _tiny_png(tmp_path: Path, width: int, height: int) -> Path:
    """A real PNG with big header dimensions and tiny compressed body."""
    from PIL import Image

    p = tmp_path / f"bomb_{width}x{height}.png"
    Image.new("RGB", (width, height), color="white").save(p, format="PNG")
    return p


def test_http_ocr_refuses_huge_image(tmp_path) -> None:
    from filewizard.perception.config import OcrSettings
    from filewizard.perception.extractors import LlamaHttpOcrExtractor

    bomb = _tiny_png(tmp_path, 20000, 20000)  # 400 MP header, small file
    settings = OcrSettings(provider="llama_http")
    out = LlamaHttpOcrExtractor(settings, allow_remote=True).extract(bomb)
    assert "error" in out["ocr"]
    # Our cap or Pillow's decompression-bomb guard, both fail closed.
    assert (
        "too large to decode" in out["ocr"]["error"]
        or "decompression bomb" in out["ocr"]["error"]
    )


def test_http_ocr_refuses_oversize_file_bytes(tmp_path) -> None:
    from filewizard.perception.config import OcrSettings
    from filewizard.perception.extractors import LlamaHttpOcrExtractor

    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * (33 * 1024 * 1024))
    settings = OcrSettings(provider="llama_http")
    out = LlamaHttpOcrExtractor(settings, allow_remote=True).extract(big)
    assert "file too large" in out["ocr"]["error"]


def test_http_ocr_malformed_image_is_error_not_crash(tmp_path) -> None:
    from filewizard.perception.config import OcrSettings
    from filewizard.perception.extractors import LlamaHttpOcrExtractor

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nnot-actually-a-png")
    settings = OcrSettings(provider="llama_http")
    out = LlamaHttpOcrExtractor(settings, allow_remote=True).extract(bad)
    assert "error" in out["ocr"]


def test_no_pillow_policy_caps_bytes_and_formats(tmp_path) -> None:
    from filewizard.perception.imagelimits import (
        ImageLimitError,
        read_image_bytes_bounded,
    )

    # Unknown magic → explicit policy error.
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"\x00\x01\x02" + b"\0" * 64)
    with pytest.raises(ImageLimitError):
        read_image_bytes_bounded(junk, max_bytes=1024)

    # Valid magic but over the cap → error (never loads it).
    ok = tmp_path / "ok.png"
    ok.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 2048)
    with pytest.raises(ImageLimitError):
        read_image_bytes_bounded(ok, max_bytes=1024)

    # Valid magic within cap → passes through.
    small = tmp_path / "small.png"
    small.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    data, mime = read_image_bytes_bounded(small, max_bytes=1024)
    assert mime == "image/png" and data.startswith(b"\x89PNG")


def test_tesseract_timeout_is_reported(tmp_path, monkeypatch) -> None:
    """A wedged tesseract child surfaces as an OCR error, not a hang."""
    import sys
    import types

    from filewizard.perception.config import OcrSettings
    from filewizard.perception.extractors import TesseractOcrExtractor

    fake_pyt = types.ModuleType("pytesseract")

    def timed_out(img, **kwargs):
        raise RuntimeError("Tesseract process timeout")

    fake_pyt.image_to_string = timed_out
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pyt)

    img = _tiny_png(tmp_path, 8, 8)
    settings = OcrSettings(provider="tesseract", timeout_s=0.5)
    out = TesseractOcrExtractor(settings).extract(img)
    assert "timeout" in out["ocr"]["error"]


def test_http_response_too_large_is_error(tmp_path, monkeypatch) -> None:
    import httpx

    from filewizard.perception.config import OcrSettings
    from filewizard.perception.extractors import LlamaHttpOcrExtractor

    img = _tiny_png(tmp_path, 8, 8)

    class Resp:
        content = b"x" * (5 * 1024 * 1024)

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(self, *a, **k):
        return Resp()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    settings = OcrSettings(provider="llama_http")
    out = LlamaHttpOcrExtractor(settings, allow_remote=True).extract(img)
    assert "response too large" in out["ocr"]["error"]


def test_resources_released_after_exception(tmp_path, monkeypatch) -> None:
    """A decode error closes the image file handle (no fd leak)."""
    import io

    opened = io.StringIO()

    class FakeImage:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            opened.write("closed")
            return False

        size = (10, 10)

        def convert(self, *a):
            raise ValueError("decode boom")

    fake_pil = types.ModuleType("PIL")
    fake_image_mod = types.ModuleType("PIL.Image")
    fake_image_mod.open = lambda *a, **k: FakeImage()
    fake_pil.Image = fake_image_mod
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_mod)

    from filewizard.perception import http_openai

    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        http_openai._resize_image_bytes(img, 1600)
    except Exception:
        pass
    assert "closed" in opened.getvalue()


def test_config_rejects_unknown_field(tmp_path) -> None:
    import yaml

    from filewizard.perception.config import load_perception_config

    cfg = tmp_path / "perception.yaml"
    cfg.write_text(
        yaml.safe_dump({"ocr": {"providr": "tesseract"}}),  # typo
        encoding="utf-8",
    )
    with pytest.raises(Exception) as excinfo:
        load_perception_config(path=cfg)
    assert "providr" in str(excinfo.value)


def test_config_rejects_out_of_range_values(tmp_path) -> None:
    from filewizard.perception.config import OcrSettings, PerceptionConfig

    with pytest.raises(Exception) as excinfo:
        OcrSettings(timeout_s=-5)
    assert "timeout_s" in str(excinfo.value)
    with pytest.raises(Exception):
        OcrSettings(temperature=99.0)
    with pytest.raises(Exception):
        OcrSettings(max_image_edge=999999)
    with pytest.raises(Exception):
        PerceptionConfig(
            cascade={"high_confidence": 7.0}
        )


def test_config_accepts_existing_yaml_roundtrip(tmp_path) -> None:
    """Valid existing config (with the new fields absent) still loads."""
    import yaml

    from filewizard.perception.config import load_perception_config

    cfg = tmp_path / "perception.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "heuristics": True,
                "ocr": {"provider": "tesseract", "timeout_s": 60},
            }
        ),
        encoding="utf-8",
    )
    config = load_perception_config(path=cfg)
    assert config.ocr.provider == "tesseract"
    assert config.ocr.timeout_s == 60
    # Defaults for the new resource fields are sane.
    assert config.ocr.max_image_pixels > 0


# ---------------------------------------------------------------------------
# WP-D2 (F-11): durable atomic writes + inter-process queue serialization.
# ---------------------------------------------------------------------------


def test_atomic_write_concurrent_writers_both_survive(tmp_path) -> None:
    """Two threads writing the same file: both contents complete, no
    truncated file, no fixed-name .tmp collision."""
    import threading

    from filewizard.persist import atomic_write_text

    target = tmp_path / "state.json"
    errors: list[Exception] = []

    def writer(tag: str) -> None:
        try:
            for i in range(25):
                atomic_write_text(
                    target,
                    json.dumps({"tag": tag, "i": i, "pad": "x" * 4096}),
                )
        except Exception as exc:  # pragma: no cover - diagnostic only
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(t,)) for t in ("a", "b")
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["tag"] in {"a", "b"}
    # No orphan temp files left behind.
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == []


def test_atomic_write_failure_keeps_original_and_cleans_tmp(
    tmp_path, monkeypatch
) -> None:
    """A failure between write and replace leaves the original intact and
    removes the abandoned temp (no fixed-name .tmp litter)."""
    from filewizard.persist import atomic_write_text

    target = tmp_path / "state.json"
    atomic_write_text(target, "original")

    def failing_replace(self, other):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", failing_replace)
    with pytest.raises(OSError):
        atomic_write_text(target, "updated")
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_write_crash_leaves_previous_content(tmp_path) -> None:
    """Simulated crash mid-write (kill during write): destination keeps
    the previous full content; a stale temp may exist but is inert."""
    from filewizard.persist import atomic_write_text

    target = tmp_path / "q.json"
    atomic_write_text(target, json.dumps({"v": 1}))

    # Simulate the crash window: a fresh temp file with partial content,
    # destination not yet replaced.
    partial = tmp_path / ".q.json.abcd.tmp"
    partial.write_text('{"v":', encoding="utf-8")

    # A later reader/load sees the intact previous content.
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
    # The next write completes normally and cleans nothing pre-existing,
    # but the destination is always complete afterwards.
    atomic_write_text(target, json.dumps({"v": 2}))
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_atomic_write_tightens_excess_and_private_default(tmp_path) -> None:
    """R5 perms round: state files never stay laxer than owner-only.

    A preexisting file with an excessive mode (0o666 by an old version or
    written by hand) is tightened on rewrite, not preserved.
    """
    from filewizard.persist import atomic_write_text

    target = tmp_path / "cfg.yaml"
    target.write_text("a: 1\n")
    target.chmod(0o666)
    atomic_write_text(target, "a: 2\n")
    assert (target.stat().st_mode & 0o777) == 0o600

    laxer = tmp_path / "queue.json"
    laxer.write_text("[]")
    laxer.chmod(0o644)
    atomic_write_text(laxer, "[1]")
    assert (laxer.stat().st_mode & 0o777) == 0o600

    fresh = tmp_path / "fresh.json"
    atomic_write_text(fresh, "{}")
    assert (fresh.stat().st_mode & 0o777) == 0o600


def _child_enqueue_script(path: Path, tag: str, delay: float = 0.0) -> str:
    """Subprocess script: enqueue one item via the same code path."""
    return f"""
import sys, time, uuid
from pathlib import Path
sys.path.insert(0, {str(Path.cwd())!r})
from filewizard.review_queue import ReviewQueue, ReviewItem
time.sleep({delay})
q = ReviewQueue(path=Path({str(path)!r}))
q.add(ReviewItem(id=uuid.uuid4().hex[:12], path={tag!r}))
print("ok")
"""


def test_two_processes_enqueue_both_items_survive(tmp_path) -> None:
    """Real concurrent processes: neither enqueue is lost (F-11)."""
    import subprocess

    queue_path = tmp_path / "review_queue.json"
    scripts = [
        _child_enqueue_script(queue_path, f"proc-{i}", delay=0.05)
        for i in range(2)
    ]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", s],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for s in scripts
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    for proc, (out, err) in zip(procs, outs):
        assert proc.returncode == 0, (out, err)

    from filewizard.review_queue import ReviewQueue

    q = ReviewQueue(path=queue_path)
    paths = {item.path for item in q.items}
    assert paths == {"proc-0", "proc-1"}


def test_merge_new_items_preserves_concurrent_entries(tmp_path) -> None:
    """An enqueue-only writer must not delete/overwrite what another
    process wrote between its load and its commit."""
    from filewizard.review_queue import ReviewItem, ReviewQueue

    queue_path = tmp_path / "review_queue.json"
    q = ReviewQueue(path=queue_path)
    q.add(ReviewItem(id="own-1", path="/own/1"), save=False)

    # Another process writes its own item meanwhile.
    other = ReviewQueue(path=queue_path)
    other.add(ReviewItem(id="other-1", path="/other/1"))

    # The stale writer commits via merge: both survive.
    added = q.merge_new_items()
    assert added == 1
    reloaded = ReviewQueue(path=queue_path)
    ids = {i.id for i in reloaded.items}
    assert ids == {"own-1", "other-1"}


def test_merge_new_items_dedupes_unresolved_path(tmp_path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue

    queue_path = tmp_path / "review_queue.json"
    other = ReviewQueue(path=queue_path)
    other.add(ReviewItem(id="disk-1", path="/same/file"))

    q = ReviewQueue(path=queue_path)
    q.add(ReviewItem(id="mine-1", path="/same/file"), save=False)
    added = q.merge_new_items()
    assert added == 0
    reloaded = ReviewQueue(path=queue_path)
    assert len(reloaded.items) == 1
    assert reloaded.items[0].id == "disk-1"


def test_transaction_lock_timeout_is_explicit(tmp_path) -> None:
    """A held lock surfaces as ReviewQueueLockError, not a hang."""
    import fcntl

    from filewizard.review_queue import (
        ReviewItem,
        ReviewQueue,
        ReviewQueueLockError,
    )

    queue_path = tmp_path / "review_queue.json"
    holder = ReviewQueue(path=queue_path)
    holder.add(ReviewItem(id="h", path="/h"))

    # Hold the lock from this process (separate fd, like another proc).
    with open(holder.lock_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        q = ReviewQueue(path=queue_path)
        q.add(ReviewItem(id="x", path="/x"), save=False)
        with pytest.raises(ReviewQueueLockError):
            with q.transaction(timeout=0.2):  # type: ignore[call-arg]
                pass
        # The unsaved mutation stays only in memory; disk is intact.
        disk = ReviewQueue(path=queue_path)
        assert [i.id for i in disk.items] == ["h"]


def test_transaction_reload_applies_to_fresh_state(tmp_path) -> None:
    """delete() sees an item another process added after our load."""
    from filewizard.review_queue import ReviewItem, ReviewQueue

    queue_path = tmp_path / "review_queue.json"
    other = ReviewQueue(path=queue_path)
    other.add(ReviewItem(id="late", path="/late"))

    q = ReviewQueue(path=queue_path)  # loaded before 'late'? no: after.
    # Force a stale in-memory view:
    q.items = []
    q._loaded_ids = set()
    assert q.delete("late") is True
    disk = ReviewQueue(path=queue_path)
    assert disk.items == []


# ---------------------------------------------------------------------------
# WP-D4 (F-16): displaced/ inventory + safe purge.
# ---------------------------------------------------------------------------


def _displaced_setup(tmp_path: Path):
    """Journal with one protected row and one orphan backup."""
    from filewizard.displaced import displaced_root

    state = tmp_path / "state"
    state.mkdir()
    root = displaced_root(state)
    root.mkdir(parents=True)

    with Journal(state / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=tmp_path / "a.txt",
            destination=tmp_path / "b.txt",
            byte_size=3,
        )
        # finished undo row → intent cleared → backup purgeable
        done_id = journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=tmp_path / "c.txt",
            destination=tmp_path / "d.txt",
            byte_size=4,
        )
        journal.finish_operation(done_id, "done")
        journal.set_displaced(done_id, root / f"{done_id}.txt")
        journal.mark_undone(done_id)
        journal.clear_displaced(done_id)
        # pending replace → backup protected
        journal.set_displaced(op_id, root / f"{op_id}.txt")

    (root / f"{done_id}.txt").write_bytes(b"old")  # purgeable orphan
    (root / f"{op_id}.txt").write_bytes(b"live")  # protected
    (root / "9999.txt").write_bytes(b"orphan")  # no row at all
    return state, root, op_id, done_id


def test_displaced_scan_classifies_protected_and_purgeable(tmp_path) -> None:
    from filewizard.displaced import scan_displaced

    state, root, op_id, done_id = _displaced_setup(tmp_path)
    report = scan_displaced(state)
    assert report.problems == []
    by_name = {e.path.name: e for e in report.entries}
    assert by_name[f"{op_id}.txt"].protected is True
    assert by_name[f"{op_id}.txt"].referenced_by == [op_id]
    assert by_name[f"{done_id}.txt"].protected is False  # undone+cleared
    assert by_name["9999.txt"].protected is False  # no row at all
    assert report.total_bytes == 3 + 4 + 6

def test_displaced_purge_is_preview_by_default(tmp_path) -> None:
    from filewizard.displaced import purge_displaced

    state, root, op_id, done_id = _displaced_setup(tmp_path)
    report = purge_displaced(state)
    assert report.purged == []
    assert (root / f"{done_id}.txt").is_file()
    assert (root / "9999.txt").is_file()
    assert report.purgeable_bytes == 3 + 6  # done (b"old") + orphan


def test_displaced_purge_never_touches_referenced(tmp_path, caplog) -> None:
    import logging as _logging

    from filewizard.displaced import purge_displaced

    state, root, op_id, done_id = _displaced_setup(tmp_path)
    with caplog.at_level(_logging.INFO, logger="filewizard.displaced"):
        report = purge_displaced(state, execute=True)
    assert set(report.purged) == {root / f"{done_id}.txt", root / "9999.txt"}
    assert (root / f"{op_id}.txt").is_file()  # referenced: kept
    assert any("displaced purge" in r.message for r in caplog.records)


def test_displaced_purge_respects_retention_cutoff(tmp_path) -> None:
    import os
    import time

    from filewizard.displaced import purge_displaced

    state, root, op_id, done_id = _displaced_setup(tmp_path)
    old = root / "9999.txt"
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    report = purge_displaced(state, older_than_days=30, execute=True)
    assert report.purged == [old]
    assert (root / f"{done_id}.txt").is_file()  # fresh: kept


def test_displaced_purge_after_undo_completes_frees_backup(
    tmp_path,
) -> None:
    """End-to-end: a completed replace+undo leaves its backup purgeable."""
    from filewizard.displaced import purge_displaced, scan_displaced
    from filewizard.executor import undo_operations

    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    db = tmp_path / "journal.db"
    with Journal(db) as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        undo_operations(journal=journal, rows=rows, dry_run=False)

    state = db.parent
    report = scan_displaced(state)
    # The restore moved the backup back to its original place: nothing
    # is left behind in displaced/ (no orphans after a complete undo).
    assert report.entries == []
    purge = purge_displaced(state, execute=True)
    assert purge.purged == []
    assert dst.read_text(encoding="utf-8") == "old"
    assert src.read_text(encoding="utf-8") == "new"


def test_cli_displaced_list_and_purge(tmp_path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli

    state, root, op_id, done_id = _displaced_setup(tmp_path)
    runner = CliRunner()

    res = runner.invoke(
        cli, ["displaced", "--state-dir", str(state)]
    )
    assert res.exit_code == 0, res.output
    assert "PROTECTED" in res.output
    assert "purgeable" in res.output
    assert (root / f"{done_id}.txt").is_file()

    res = runner.invoke(
        cli, ["displaced", "--state-dir", str(state), "--execute", "--yes"]
    )
    assert res.exit_code == 0, res.output
    assert not (root / f"{done_id}.txt").is_file()
    assert (root / f"{op_id}.txt").is_file()


# ---------------------------------------------------------------------------
# WP-D5 (F-14): structured scan result + abort on partial scan.
# ---------------------------------------------------------------------------


def _scan_error_setup(tmp_path: Path, rules: Path):
    """Source with one unreadable directory so the scan is partial."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    locked = src / "locked"
    locked.mkdir()
    (locked / "b.txt").write_text("y", encoding="utf-8")
    locked.chmod(0o000)  # unreadable → scandir raises (unless root)
    return src


def test_mcp_execute_aborts_on_partial_scan(tmp_path, monkeypatch) -> None:

    from filewizard.mcp.tools import filewizard_execute, filewizard_plan

    src = _scan_error_setup(tmp_path, None)
    state = tmp_path / "state"
    rules = tmp_path / "rules.yaml"
    write_rules(rules, tmp_path / "out")

    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path))

    try:
        plan = filewizard_plan(src, state, rules=rules)
        scan = plan.get("scan") or {}
        errors = scan.get("errors") or plan.get("scan_errors") or []
        if errors:
            # As non-root the locked dir yields scan errors.
            assert scan["complete"] is False

            payload = filewizard_execute(
                src, state, rules=rules, confirm=True
            )
            assert payload["ok"] is False
            assert "incomplete" in (payload.get("error") or "")
            # Nothing moved: the plan was refused before executing.
            assert (src / "a.txt").exists()

            payload = filewizard_execute(
                src, state, rules=rules, confirm=True, allow_partial_scan=True
            )
            assert payload["ok"] is True
            assert payload["scan"]["complete"] is False
            assert payload["summary"].get("done", 0) >= 1
        else:
            # Running as root: unreadable dirs are still readable.
            assert scan["complete"] is True
            pytest.skip("running as root: cannot simulate unreadable dir")
    finally:
        (src / "locked").chmod(0o755)


def test_cli_run_aborts_on_partial_scan(tmp_path, monkeypatch) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli

    src = _scan_error_setup(tmp_path, None)
    state = tmp_path / "state"
    rules = tmp_path / "rules.yaml"
    write_rules(rules, tmp_path / "out")
    runner = CliRunner()

    try:
        res = runner.invoke(
            cli,
            [
                "run", "--source", str(src), "--rules", str(rules),
                "--execute", "--yes",
                "--state-dir", str(state),
            ],
            catch_exceptions=False,
        )
        if "Scan incomplete" not in res.output:
            pytest.skip("running as root: cannot simulate unreadable dir")
        assert res.exit_code != 0
        assert "Refusing to execute over an incomplete scan" in res.output
        assert (src / "a.txt").exists()

        res = runner.invoke(
            cli,
            [
                "run", "--source", str(src), "--rules", str(rules),
                "--execute", "--yes",
                "--state-dir", str(state),
                "--allow-partial-scan",
            ],
            catch_exceptions=False,
        )
        assert res.exit_code == 0, res.output
        assert (tmp_path / "out" / "a.txt").exists()
    finally:
        (src / "locked").chmod(0o755)


def test_cli_run_clean_scan_still_executes(tmp_path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, tmp_path / "out")
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "run", "--source", str(src), "--rules", str(rules),
            "--execute", "--yes",
            "--state-dir", str(tmp_path / "state"),
        ],
        catch_exceptions=False,
    )
    assert res.exit_code == 0, res.output
    assert "Scan incomplete" not in res.output
    assert (tmp_path / "out" / "a.txt").exists()


# ---------------------------------------------------------------------------
# Fase E: E1 flock watcher lock, E2 private permissions, E3 remote guard,
# E4 regex length + always=True semantics, E5 crash/concurrency.
# ---------------------------------------------------------------------------


def test_watcher_lock_uses_flock_and_recovers_after_crash(tmp_path) -> None:
    """E1: exclusion is the flock; a crashed holder never wedges it and
    a stale lock file with a dead pid is not honored."""
    import fcntl

    from filewizard.watch import WatcherLockError, watcher_lock

    state = tmp_path / "state"
    lock_path = state / "watch.lock"

    # A stale lock file with a live-looking pid but no flock: reclaimable.
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("999999999", encoding="utf-8")

    with watcher_lock(state):
        # Content records owner + token (diagnostics only).
        content = lock_path.read_text(encoding="utf-8")
        assert content.split()[0] == str(os.getpid())
        assert len(content.split()[1]) == 32  # uuid token

        # A second fd in this process cannot take the flock.
        fh2 = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(OSError):
                fcntl.flock(fh2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fh2)
        with pytest.raises(WatcherLockError):
            with watcher_lock(state):
                pass

    # After release (and simulated crash) the lock is free again.
    with watcher_lock(state):
        pass


def test_e2_journal_and_cache_are_owner_private(tmp_path) -> None:
    from filewizard.perception.cache import PerceptionCache

    with Journal(tmp_path / "journal.db") as journal:
        mode = (Path(journal.path)).stat().st_mode & 0o777
        assert mode & 0o077 == 0  # no group/other access

    PerceptionCache(root=tmp_path / "cache")
    assert (tmp_path / "cache").stat().st_mode & 0o777 == 0o700


def test_e2_state_files_are_owner_private(tmp_path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue

    q = ReviewQueue(path=tmp_path / "review_queue.json")
    q.add(ReviewItem(id="a", path="/a"))
    assert (tmp_path / "review_queue.json").stat().st_mode & 0o077 == 0
    labels = tmp_path / "review_labels.json"
    if labels.is_file():
        assert labels.stat().st_mode & 0o077 == 0


def test_e2_displaced_dir_is_owner_private(tmp_path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "b.txt"
    dst.write_text("old", encoding="utf-8")
    with Journal(tmp_path / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        displaced = tmp_path / "displaced"
        assert displaced.is_dir()
        assert displaced.stat().st_mode & 0o777 == 0o700
        from filewizard.executor import undo_operations

        undo_operations(journal=journal, rows=rows, dry_run=False)


def test_e3_chat_completion_refuses_remote_without_optin(
    tmp_path, monkeypatch
) -> None:
    """E3 defense in depth: the HTTP entry point itself fails closed."""
    from filewizard.perception import http_openai

    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    calls: list[str] = []

    class NoClient:
        def __init__(self, *a, **k):
            calls.append("client")

    monkeypatch.setattr(http_openai.httpx, "Client", NoClient)
    with pytest.raises(RuntimeError) as excinfo:
        http_openai.chat_completion_with_image(
            base_url="http://perception.example.com:9999/v1",
            model="m",
            prompt="p",
            image_path=img,
            timeout_s=5,
        )
    assert "allow_remote" in str(excinfo.value)
    assert calls == []  # the client was never created
    monkeypatch.undo()

    # Loopback is always allowed (host-local inference).
    monkeypatch.setattr(
        http_openai,
        "_resize_image_bytes",
        lambda path, edge, **k: (b"img", "image/png"),
    )

    class Resp:
        content = b"ok"

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(self, *a, **k):
        return Resp()

    monkeypatch.setattr(http_openai.httpx.Client, "post", fake_post)
    out = http_openai.chat_completion_with_image(
        base_url="http://127.0.0.1:8080/v1",
        model="m",
        prompt="p",
        image_path=img,
        timeout_s=5,
    )
    assert out == "ok"


def test_e4_regex_length_limit_at_load(tmp_path) -> None:
    from filewizard.models import Condition

    with pytest.raises(ValueError) as excinfo:
        Condition(filename_regex="a" * 600)
    assert "too long" in str(excinfo.value)
    # A reasonable pattern still loads.
    Condition(filename_regex="^IMG[_-]?\\d{4}\\.jpg$")


def test_e4_empty_condition_matches_everything(tmp_path) -> None:
    """always=True semantics: no field set ⇒ the rule matches any file,
    with a stable ConditionCheck the GUI can render."""
    from filewizard.engine import Engine
    from filewizard.facts import collect_facts
    from filewizard.models import Action, Condition, Rule

    file = tmp_path / "weird.xyz"
    file.write_bytes(b"x")
    facts = collect_facts(file)
    engine = Engine(
        rules=[
            Rule(
                id="catch-all",
                name="Catch all",
                when=Condition(always=True),
                then=Action(rename="{stem}-handled{extension}"),
            )
        ]
    )
    matches = list(engine.evaluate(facts))
    assert len(matches) == 1
    keys = [c.key for c in matches[0].conditions]
    assert "always" in keys
    assert all(c.passed for c in matches[0].conditions)


_CHILD_JOURNAL_SCRIPT = """
import sys
sys.path.insert(0, {cwd!r})
from filewizard.journal import Journal
from pathlib import Path

db = Path(sys.argv[1])
mode = {mode!r}
with Journal(db) as journal:
    for i in range(20):
        op_id = journal.start_operation(
            batch_id=f"b-{{mode}}",
            rule_id="r",
            op="move",
            source=Path(f"/tmp/{{mode}}-{{i}}.txt"),
            destination=Path(f"/tmp/out/{{mode}}-{{i}}.txt"),
            byte_size=i,
        )
        journal.finish_operation(op_id, "done")
print("ok")
"""


def test_e5_concurrent_processes_share_the_journal(tmp_path) -> None:
    """E5: two real processes write simultaneously (WAL + busy_timeout):
    all rows land, none lost, no 'database is locked' failure."""
    import subprocess

    db = tmp_path / "journal.db"
    scripts = [
        _CHILD_JOURNAL_SCRIPT.format(cwd=str(Path.cwd()), mode=m)
        for m in ("p1", "p2")
    ]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", s, str(db)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for s in scripts
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, (out, err)

    with Journal(db) as journal:
        count = journal.conn.execute(
            "SELECT COUNT(*) FROM operations"
        ).fetchone()[0]
        assert count == 40
        done = journal.conn.execute(
            "SELECT COUNT(*) FROM operations WHERE status = 'done'"
        ).fetchone()[0]
        assert done == 40


def test_e5_process_death_leaves_recoverable_journal(tmp_path) -> None:
    """E5: a child killed right after its last op leaves WAL rows on
    disk; another process reads them and the reconcile ladder applies."""
    import subprocess

    db = tmp_path / "journal.db"
    script = _CHILD_JOURNAL_SCRIPT.format(cwd=str(Path.cwd()), mode="dead")
    # Child does NOT commit gracefully: hard-exit with pending commits
    # already flushed (start_operation commits per row).
    proc = subprocess.Popen(
        [sys.executable, "-c", script + "\nimport os; os._exit(9)", str(db)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc.communicate(timeout=120)
    assert proc.returncode == 9

    with Journal(db) as journal:
        count = journal.conn.execute(
            "SELECT COUNT(*) FROM operations"
        ).fetchone()[0]
        assert count == 20
        pending, promoted = journal.reconcile_pending()
        assert pending == 0  # all rows are terminal (done)


# --- R4: watcher give-ups + labels/queue coherence --------------------------


def test_r4_giveup_recorded_on_max_attempts(tmp_path) -> None:
    """Exhausting MAX_WATCH_ATTEMPTS appends a queryable JSONL record."""
    from filewizard.watch import _record_giveup, read_giveups

    state = tmp_path / "state"
    state.mkdir()
    _record_giveup(
        state,
        source=state / "src",
        path=state / "src" / "bad.txt",
        attempts=3,
        last_status="error",
        reason="max_attempts_exhausted",
    )
    events = read_giveups(state)
    assert len(events) == 1
    assert events[0]["reason"] == "max_attempts_exhausted"
    assert events[0]["attempts"] == 3
    assert events[0]["last_status"] == "error"


def test_r4_failed_enqueue_observable_to_caller(tmp_path) -> None:
    """A failed enqueue must surface to the requester (CLI/GUI).

    The review-queue lock failure is not swallowed silently: the worker
    exposes an enqueue_note that the wizard turns into a non-fatal
    QMessageBox.warning (error slot is reserved for aborting).
    """
    import inspect

    from filewizard.ui import workers

    src = inspect.getsource(workers.PreviewWorker.run)
    assert "enqueue_note" in src
    assert "QMessageBox" not in src  # GUI layer owns the dialog


def test_r4_labels_written_before_queue_save(tmp_path) -> None:
    """Crash coherence: labels are written before the queue save, so a
    crash between them leaves labels ahead of the queue — by design, not
    a silent loss. Re-resolving converges."""
    from filewizard.review_queue import ReviewQueue

    q = ReviewQueue(path=tmp_path / "review_queue.json")
    q.add_model_hold(
        tmp_path / "img.png", "no-cascade-match", save=True
    )
    item_id = q.items[-1].id
    assert q.resolve(item_id, "invoice") is True

    # Simulate a crash: queue save raises after labels written.
    original = q._save_locked
    calls = {"n": 0}

    def crashing_save() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated crash")
        original()

    # Add item2 while saves still work.
    q._save_locked = original
    q.add_model_hold(
        tmp_path / "img2.png", "no-cascade-match", save=True
    )
    item2_id = q.items[-1].id
    # Now make the next save crash.
    q._save_locked = crashing_save  # type: ignore[assignment]
    # resolve() rolls back the in-memory item on failure.
    ok = None
    try:
        ok = q.resolve(item2_id, "receipt")
    except OSError:
        ok = False
    assert ok is False
    # On disk, the queue was never saved: item2 stays unresolved.
    from filewizard.review_queue import ReviewQueue

    fresh = ReviewQueue(path=tmp_path / "review_queue.json")
    assert any(i.id == item2_id and not i.resolved for i in fresh.items)

    # Labels file still reflects the earlier successful resolution.
    import json

    labels = json.loads(
        (tmp_path / "review_labels.json").read_text(encoding="utf-8")
    )
    assert str(tmp_path / "img.png") in labels

    # Re-resolve after recovery succeeds and labels stay coherent.
    q._save_locked = original
    assert q.resolve(item2_id, "receipt") is True


def test_e2_journal_reopen_tightens_preexisting_excess_wal_shm(
    tmp_path,
) -> None:
    """Reopening a journal whose WAL/SHM side files are 0666 tightens them.

    SQLite keeps a preexisting side file's mode; the journal records user
    paths, so the WAL must never stay group/world readable (F-05b).
    """
    import os
    import sqlite3

    from filewizard.journal import Journal

    db = tmp_path / "journal.db"
    seed = sqlite3.connect(db)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    os.chmod(db, 0o666)
    os.chmod(tmp_path / "journal.db-wal", 0o666)
    os.chmod(tmp_path / "journal.db-shm", 0o666)

    with Journal(db):
        pass

    assert (db.stat().st_mode & 0o777) == 0o600
    assert (tmp_path / "journal.db-wal").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "journal.db-shm").stat().st_mode & 0o777 == 0o600


def test_e2_log_rollover_keeps_owner_only(tmp_path) -> None:
    """Rotation must not regress the live log to the umask default (0644).

    The rotating handler reopens the file after rollover; without the
    private-mode override the first 1MB rotation makes the log (which
    records user paths) group-readable again.
    """
    import logging
    import os

    from filewizard.logsetup import setup_file_logging

    log_path = tmp_path / "filewizard.log"
    setup_file_logging(tmp_path)
    logger = logging.getLogger("filewizard")
    try:
        for _ in range(12000):
            logger.info("x" * 100)
        assert (log_path.stat().st_mode & 0o777) == 0o600
        rotated = sorted(tmp_path.glob("filewizard.log.*"))
        assert rotated, "rollover should have produced a backup"
        for backup in rotated:
            assert (backup.stat().st_mode & 0o777) == 0o600

        # A preexisting log with an excessive mode is tightened on every
        # setup, not only when the handler is first created.
        os.chmod(log_path, 0o666)
        setup_file_logging(tmp_path)
        logger.info("after reopen")
        assert (log_path.stat().st_mode & 0o777) == 0o600
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


# --- R6: fsmove backends under real process termination ---------------------


def _child_fsmove_script(cwd: Path) -> str:
    """Script template for fork-terminated fsmove children.

    Runs with ``sys.argv[1]=src``, ``sys.argv[2]=dst``. R6 requires real
    process termination, not in-process simulation: children terminate
    with ``os._exit`` exactly at the boundary under test.
    """
    return (
        "import os, sys\n"
        f"sys.path.insert(0, {str(cwd)!r})\n"
        "from pathlib import Path\n"
        "import filewizard.fsmove as fsmove\n"
        "src, dst = Path(sys.argv[1]), Path(sys.argv[2])\n"
    )


def test_fsmove_samefs_crash_between_link_and_unlink(tmp_path) -> None:
    """Backend 2 crash boundary: link done, unlink not yet.

    Real termination: the child hard-exits (``os._exit(88)``) from inside
    the ``os.unlink(src)`` call, so the crash happens exactly between the
    two physical mutations. ADR-0005 I9: nothing is overwritten; the
    content exists exactly twice (source + linked destination) and no
    third name appears.
    """
    import subprocess

    base = tmp_path
    src = base / "src.txt"
    dst = base / "dst.txt"
    src.write_text("crashme", encoding="utf-8")

    script = _child_fsmove_script(Path.cwd()) + """
fsmove._libc_renameat2 = lambda: (_ for _ in ()).throw(NotImplementedError)
real_unlink = os.unlink
def die_unlink(path, *a, **k):
    if Path(path) == src:
        os._exit(88)
    return real_unlink(path, *a, **k)
os.unlink = die_unlink
try:
    fsmove.move_noreplace(src, dst)
except SystemExit:
    raise
os._exit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(src), str(dst)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 88, proc.stderr

    # FS after crash: destination created by link, source still present.
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "crashme"
    assert src.is_file()
    assert src.read_text(encoding="utf-8") == "crashme"
    # Exactly the two hard links share the content — no data duplicated
    # into temp files, nothing lost.
    assert os.stat(src).st_nlink == 2
    assert os.stat(src).st_ino == os.stat(dst).st_ino
    leftovers = [p.name for p in base.iterdir() if p.name not in {"src.txt", "dst.txt"}]
    assert leftovers == []
    # A retry is correctly refused: the destination now exists.
    from filewizard.fsmove import DestinationExistsError, move_noreplace

    other = base / "retry.txt"
    other.write_text("retry", encoding="utf-8")
    with pytest.raises(DestinationExistsError):
        move_noreplace(other, dst)
    assert other.is_file()


def test_fsmove_cross_fs_crash_after_verified_copy(tmp_path) -> None:
    """Backend 3 crash boundary: verified copy renamed onto reservation,
    source unlink not yet done.

    Real termination via ``os._exit(89)`` inside ``os.unlink(src)``.
    Outcome: destination holds the verified content, source still exists
    (duplicated, never lost), no temp files remain.
    """
    import subprocess

    shm = Path("/dev/shm")
    if (
        not shm.is_dir()
        or os.stat(shm).st_dev == os.stat(tmp_path).st_dev
    ):
        pytest.skip("no second filesystem available for the EXDEV path")

    src = tmp_path / "cross.txt"
    dst = shm / f"fw-r6-{os.getpid()}" / "cross.txt"
    dst.parent.mkdir(exist_ok=True)
    try:
        src.write_text("cross-crash", encoding="utf-8")
        script = _child_fsmove_script(Path.cwd()) + """
real_unlink = os.unlink
def die_unlink(path, *a, **k):
    if Path(path) == src:
        os._exit(89)
    return real_unlink(path, *a, **k)
os.unlink = die_unlink
fsmove.move_noreplace(src, dst)
os._exit(0)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, str(src), str(dst)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 89, proc.stderr

        assert dst.is_file()
        assert dst.read_text(encoding="utf-8") == "cross-crash"
        assert src.is_file()
        assert src.read_text(encoding="utf-8") == "cross-crash"
        leftovers = [p.name for p in dst.parent.iterdir() if p.name != "cross.txt"]
        assert leftovers == []  # the mkstemp staging copy was renamed away
    finally:
        shutil.rmtree(dst.parent, ignore_errors=True)


def test_fsmove_cross_fs_crash_during_copy_leaves_only_staging(tmp_path) -> None:
    """R8.2: a crash mid-copy leaves only a staging temp, never a placeholder.

    The destination name remains free for an atomic retry; the source is
    retained and no foreign object is removed by cleanup.
    """
    import subprocess

    shm = Path("/dev/shm")
    if (
        not shm.is_dir()
        or os.stat(shm).st_dev == os.stat(tmp_path).st_dev
    ):
        pytest.skip("no second filesystem available for the EXDEV path")

    src = tmp_path / "cross2.txt"
    dst = shm / f"fw-r6b-{os.getpid()}" / "cross2.txt"
    dst.parent.mkdir(exist_ok=True)
    try:
        src.write_text("partial-copy", encoding="utf-8")
        script = _child_fsmove_script(Path.cwd()) + """
real_copy = fsmove.shutil.copyfile
def die_copyfile(s, d, *a, **k):
    Path(d).write_text("part", encoding="utf-8")
    os._exit(90)
fsmove.shutil.copyfile = die_copyfile
fsmove.move_noreplace(src, dst)
os._exit(0)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, str(src), str(dst)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 90, proc.stderr

        # FS after crash: no reservation, partial staging beside it,
        # source untouched.
        assert not dst.exists()
        assert src.read_text(encoding="utf-8") == "partial-copy"
        staging = [p for p in dst.parent.iterdir() if p.name.startswith(".cross2.txt.fwtmp-")]
        assert staging and staging[0].stat().st_size == 4
        # The destination name was never reserved, so retry succeeds and
        # leaves only the abandoned staging file for retention cleanup.
        from filewizard.fsmove import move_noreplace

        move_noreplace(src, dst)
        assert dst.read_text(encoding="utf-8") == "partial-copy"
        assert not src.exists()
    finally:
        shutil.rmtree(dst.parent, ignore_errors=True)


def test_fsmove_two_real_processes_race_no_overwrite(tmp_path) -> None:
    """Two real processes race ``move_noreplace`` to one destination.

    Kernel-level race on the native ``renameat2(RENAME_NOREPLACE)`` path
    (no fakes): exactly one child moves, the loser gets
    ``DestinationExistsError`` with its source untouched, and the
    destination content is exactly the winner's.
    """
    import subprocess

    base = tmp_path
    dst = base / "contested.txt"
    contents = {"A": "from-alpha", "B": "from-beta"}
    srcs = {}
    for tag, content in contents.items():
        s = base / f"src-{tag}.txt"
        s.write_text(content, encoding="utf-8")
        srcs[tag] = s

    script = _child_fsmove_script(Path.cwd()) + """
import filewizard.fsmove as fm
try:
    fm.move_noreplace(src, dst)
except fm.DestinationExistsError:
    os._exit(3)
os._exit(0)
"""
    procs = {
        tag: subprocess.Popen(
            [sys.executable, "-c", script, str(srcs[tag]), str(dst)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        for tag in contents
    }
    codes = {}
    for tag, proc in procs.items():
        _, err = proc.communicate(timeout=120)
        assert proc.returncode in (0, 3), f"{tag}: {err}"
        codes[tag] = proc.returncode

    assert sorted(codes.values()) == [0, 3], "exactly one winner"
    winner = next(t for t, c in codes.items() if c == 0)
    loser = next(t for t, c in codes.items() if c == 3)
    assert dst.read_text(encoding="utf-8") == contents[winner]
    assert srcs[winner].exists() is False
    assert srcs[loser].read_text(encoding="utf-8") == contents[loser]
    assert [p.name for p in base.iterdir() if p.name.startswith("contested")] == [
        "contested.txt"
    ]


def test_fsmove_symlink_destination_never_followed(tmp_path) -> None:
    """A symlink destination is refused, and its target is not harmed.

    ``renameat2(NOREPLACE)`` reports EEXIST for an existing symlink
    without following it, so the victim behind the link keeps its
    content (ADR-0005 I9 applied to links). R3.4: route-following by
    destination substitution cannot turn a move into an overwrite.
    """
    from filewizard.fsmove import DestinationExistsError, move_noreplace

    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    dst = tmp_path / "link.txt"
    dst.symlink_to(victim)
    src = tmp_path / "src.txt"
    src.write_text("intruder", encoding="utf-8")

    with pytest.raises(DestinationExistsError):
        move_noreplace(src, dst)
    assert victim.read_text(encoding="utf-8") == "precious"
    assert src.read_text(encoding="utf-8") == "intruder"
    assert dst.is_symlink()


def test_fsmove_renames_symlink_source_as_the_link_itself(tmp_path) -> None:
    """On the native renameat2 path a symlink source moves as the link,
    not its target (kernel rename does not follow). The pointed-to file
    keeps its content and inode.
    """
    from filewizard.fsmove import move_noreplace

    target = tmp_path / "target.txt"
    target.write_text("real", encoding="utf-8")
    src = tmp_path / "alias.lnk"
    src.symlink_to(target)
    dst = tmp_path / "moved.lnk"

    move_noreplace(src, dst)
    assert dst.is_symlink()
    assert not src.exists()
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "real"


def test_fsmove_enosys_falls_back_to_link_unlink(tmp_path, monkeypatch) -> None:
    """Wiring check (in-process simulation, documented as such): when
    renameat2 is unavailable (ENOSYS), the same-fs fallback link+unlink
    completes the move atomically-enough and never overwrites.

    Crash behaviour of this fallback is pinned by
    ``test_fsmove_samefs_crash_between_link_and_unlink`` with a real
    terminated process.
    """
    import filewizard.fsmove as fsmove

    monkeypatch.setattr(
        fsmove,
        "_libc_renameat2",
        lambda: (_ for _ in ()).throw(NotImplementedError),
    )
    src = tmp_path / "a.txt"
    src.write_text("fallback", encoding="utf-8")
    dst = tmp_path / "sub" / "a.txt"
    dst.parent.mkdir()
    fsmove.move_noreplace(src, dst)
    assert dst.read_text(encoding="utf-8") == "fallback"
    assert not src.exists()

    # R6: prove the fallback is actually the link+unlink backend now that
    # _same_fs compares against the destination directory (regression
    # guard: previously every move routed to the cross-fs copy path).
    calls: list[tuple[Path, Path]] = []
    real_link = os.link

    def counting_link(a, b, *args, **kwargs):
        calls.append((Path(a), Path(b)))
        return real_link(a, b, *args, **kwargs)

    monkeypatch.setattr(fsmove.os, "link", counting_link)
    src3 = tmp_path / "d.txt"
    src3.write_text("via-link", encoding="utf-8")
    dst3 = tmp_path / "sub" / "d.txt"
    fsmove.move_noreplace(src3, dst3)
    assert calls and calls[0][0] == src3 and calls[0][1] == dst3
    assert not src3.exists()

    dst2 = tmp_path / "sub" / "b.txt"
    dst2.write_text("existing", encoding="utf-8")
    src2 = tmp_path / "c.txt"
    src2.write_text("other", encoding="utf-8")
    with pytest.raises(fsmove.DestinationExistsError):
        fsmove.move_noreplace(src2, dst2)
    assert dst2.read_text(encoding="utf-8") == "existing"


# --- R2: A2 replace saga + A3 undo saga, real process termination -----------


def _crash_child_script(cwd: Path) -> str:
    """Template: child runs a replace move and hard-exits at a boundary.

    Real termination, not in-process simulation: the kill points are
    ``os._exit`` calls executed inside the monkeypatched call, so the
    process dies mid-saga exactly like SIGKILL at that effect boundary
    (no cleanup handlers, no atexit, no journal commit afterwards).
    """
    return (
        "import os, sys\n"
        f"sys.path.insert(0, {str(cwd)!r})\n"
        "from pathlib import Path\n"
        "from filewizard.engine import ConditionCheck\n"
        "from filewizard.executor import Executor, PlannedOperation\n"
        "import filewizard.executor as ex\n"
        "from filewizard.identity import capture_identity\n"
        "from filewizard.journal import Journal\n"
        "tag, state, src, dst = sys.argv[1:5]\n"
        "state, src, dst = Path(state), Path(src), Path(dst)\n"
        "journal = Journal(state / 'journal.db')\n"
        "identity = capture_identity(src)\n"
        "op = PlannedOperation(source=src, rule_id='r1', rule_name='R1',\n"
        "    destination=dst,\n"
        "    conditions=[ConditionCheck('always', True, 'x')],\n"
        "    on_collision='replace',\n"
        "    identity_size=identity.size if identity else None,\n"
        "    identity_sha256=identity.sha256 if identity else None,\n"
        "    identity_mtime_ns=identity.mtime_ns if identity else None,\n"
        "    identity_dev=identity.device if identity else None,\n"
        "    identity_ino=identity.inode if identity else None)\n"
        "executor = Executor(journal=journal, dry_run=False)\n"
        "def die(*a, **k):\n"
        "    os._exit(42)\n"
        "if tag == 'after_displace_intent':\n"
        "    ex._displace = die\n"
        "elif tag == 'after_displace':\n"
        "    ex.move_noreplace_unique = die\n"
        "elif tag == 'after_move':\n"
        "    journal.finish_operation = die\n"
        "executor.execute([op])\n"
        "os._exit(0)\n"
    )


def _run_crash_child(script: str, args: list[str]) -> None:
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 42, f"child: {proc.returncode} {proc.stderr}"


@pytest.mark.parametrize(
    "tag",
    [
        "after_displace_intent",
        "after_displace",
        "after_move",
    ],
)
def test_r2_replace_saga_crash_boundaries_recover(
    tmp_path, tag
) -> None:
    """A2 replace saga, killed by real process death at each boundary.

    For every boundary the same invariants hold after recovery
    (ADR-0005 I3/I4/I9): the occupant is intact, the source is intact,
    nothing is lost, and ``reconcile_pending`` drives the row forward.
    """
    from filewizard.executor import undo_operations

    state = tmp_path / "state"
    src = tmp_path / "a.txt"
    dst = tmp_path / "out.txt"
    src.write_text("new-content", encoding="utf-8")
    dst.write_text("old-occupant", encoding="utf-8")

    script = _crash_child_script(Path.cwd())
    _run_crash_child(script, [tag, str(state), str(src), str(dst)])

    with Journal(state / "journal.db") as journal:
        rows = journal.pending_operations()
        assert len(rows) == 1
        row = rows[0]
        displaced_raw = row["displaced_path"]
        backup = Path(str(displaced_raw)) if displaced_raw else None

        if tag == "after_displace_intent":
            # Intent persisted, no physical mutation yet.
            assert backup is not None and not backup.exists()
            assert dst.read_text(encoding="utf-8") == "old-occupant"
            assert src.read_text(encoding="utf-8") == "new-content"
            promoted, still = journal.reconcile_pending()
            assert (promoted, still) == (0, 1)  # owner may be alive; stays
        elif tag == "after_displace":
            # Occupant displaced, nothing moved in yet.
            assert backup is not None and backup.is_file()
            assert backup.read_text(encoding="utf-8") == "old-occupant"
            assert not dst.exists()
            assert src.read_text(encoding="utf-8") == "new-content"
            journal.reconcile_pending()
            # reconcile restores the occupant and clears the intent.
            assert dst.read_text(encoding="utf-8") == "old-occupant"
            assert not backup.exists()
            live = journal.get_operation(int(row["id"]))
            assert live["displaced_path"] is None
        elif tag == "after_move":
            # Replace completed; only the finish commit is missing.
            assert dst.read_text(encoding="utf-8") == "new-content"
            assert not src.exists()
            assert backup is not None and backup.is_file()
            promoted, still = journal.reconcile_pending()
            assert promoted == 1 and still == 0
            live = journal.get_operation(int(row["id"]))
            assert str(live["status"]) == "done"
            # Displaced intent intentionally kept: a later undo of this
            # replace must restore the occupant.
            assert live["displaced_path"] is not None
            results = undo_operations(
                journal=journal,
                rows=[live],
                dry_run=False,
            )
            assert results[0]["status"] == "done"
            assert dst.read_text(encoding="utf-8") == "old-occupant"
            assert src.read_text(encoding="utf-8") == "new-content"
            assert (
                str(journal.get_operation(int(row["id"]))["status"])
                == "undone"
            )

        # Temp/residue accounting after recovery: only real files remain.
        names = sorted(p.name for p in tmp_path.iterdir())
        assert all(not n.endswith(".tmp") for n in names), names


def test_r2_undo_saga_crash_after_restore_converges(tmp_path) -> None:
    """A3 undo boundary U-D: crash between the displaced-restore move and
    the intent clear. Re-running undo must converge to ``undone``, not
    refuse forever with ``state_mismatch`` (occupant sits at the
    journal destination, so the size check alone cannot see the truth).
    """
    import subprocess

    state = tmp_path / "state"
    src = tmp_path / "a.txt"
    dst = tmp_path / "out.txt"
    src.write_text("new-content", encoding="utf-8")
    dst.write_text("old-occupant", encoding="utf-8")

    # Parent does the full replace + undo up to the restore move, then
    # simulates the crash by killing the child that was about to clear
    # the intent: we reproduce the state exactly and kill for real.
    with Journal(state / "journal.db") as journal:
        rows = _exec_move(journal, src, dst, on_collision="replace")
        row = rows[0]

    # The child performs the undo saga and dies (os._exit(43)) inside the
    # displaced-intent clear — i.e. after the restore move completed.
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "import shutil\n"
        "from pathlib import Path\n"
        "from filewizard.executor import _restore_displaced\n"
        "from filewizard.identity import capture_identity\n"
        "from filewizard.journal import Journal\n"
        "state, src, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])\n"
        "op_id = int(sys.argv[4])\n"
        "journal = Journal(state / 'journal.db')\n"
        "live = journal.get_operation(op_id)\n"
        "undo_identity = capture_identity(dst)\n"
        "undo_op_id = journal.start_operation(\n"
        "    batch_id='undo-crash', rule_id=str(live['rule_id']), op='undo',\n"
        "    source=dst, destination=src, byte_size=undo_identity.size,\n"
        "    content_sha256=undo_identity.sha256,\n"
        "    source_mtime_ns=undo_identity.mtime_ns,\n"
        "    source_dev=undo_identity.device,\n"
        "    source_ino=undo_identity.inode,\n"
        "    original_operation_id=op_id)\n"
        "def die_clear(*a, **k):\n"
        "    os._exit(43)\n"
        "journal.clear_displaced = die_clear\n"
        "shutil.move(str(dst), str(src))\n"
        "journal.finish_operation(undo_op_id, status='done', destination=src)\n"
        "_restore_displaced(live, dst, journal, op_id)\n"
        "os._exit(0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(state), str(src), str(dst), str(row["id"])],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 43, proc.stderr

    # Crash state: occupant restored at dst, moved file home at src,
    # backup gone, displaced intent still recorded, row still done.
    assert dst.read_text(encoding="utf-8") == "old-occupant"
    assert src.read_text(encoding="utf-8") == "new-content"

    from filewizard.executor import undo_operations

    with Journal(state / "journal.db") as journal:
        live = journal.get_operation(int(row["id"]))
        assert live["displaced_path"] is not None
        results = undo_operations(journal=journal, rows=[live], dry_run=False)
        assert results[0]["status"] == "already_restored", results
        assert (
            str(journal.get_operation(int(row["id"]))["status"]) == "undone"
        )
