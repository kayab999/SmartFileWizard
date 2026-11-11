"""R8 assurance: E1-only completion, atomic publication and saga convergence."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from filewizard.executor import (
    Executor,
    _status_from_identity,
    undo_operations,
)
from filewizard.fsmove import move_noreplace
from filewizard.identity import capture_identity
from filewizard.journal import Journal


def _identity_kwargs(path: Path):
    identity = capture_identity(path)
    assert identity is not None
    return {
        "size": identity.size,
        "sha256": identity.sha256,
        "device": identity.device,
        "inode": identity.inode,
    }


def _shm_dir(tmp_path: Path, name: str) -> Path:
    root = Path("/dev/shm")
    if not root.is_dir() or os.stat(root).st_dev == os.stat(tmp_path).st_dev:
        pytest.skip("a real second filesystem is required")
    path = root / f"fw-r8-{os.getpid()}-{name}"
    path.mkdir(exist_ok=True)
    return path


def test_r81_same_inode_in_place_modification_is_not_done(tmp_path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("before", encoding="utf-8")
    expected = _identity_kwargs(src)
    os.rename(src, dst)
    original_ino = dst.stat().st_ino
    dst.write_text("tamper", encoding="utf-8")
    assert dst.stat().st_ino == original_ino
    assert _status_from_identity(dst, **expected) == "needs_verify"


def test_r81_different_inode_with_correct_hash_is_e1_done(tmp_path) -> None:
    import shutil

    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("payload", encoding="utf-8")
    expected = _identity_kwargs(src)
    shutil.copy2(src, dst)
    assert dst.stat().st_ino != src.stat().st_ino
    assert _status_from_identity(dst, **expected) == "done"


def test_r81_cross_device_correct_hash_is_done(tmp_path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("cross-device-e1", encoding="utf-8")
    expected = _identity_kwargs(src)
    dst = _shm_dir(tmp_path, "e1") / "a.txt"
    try:
        move_noreplace(src, dst)
        assert dst.stat().st_dev != expected["device"]
        assert _status_from_identity(dst, **expected) == "done"
    finally:
        import shutil

        shutil.rmtree(dst.parent, ignore_errors=True)


def test_r81_cross_device_without_hash_is_needs_verify(tmp_path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("cross-device-e2", encoding="utf-8")
    expected = _identity_kwargs(src)
    expected["sha256"] = None
    dst = _shm_dir(tmp_path, "e2") / "a.txt"
    try:
        move_noreplace(src, dst)
        assert _status_from_identity(dst, **expected) == "needs_verify"
    finally:
        import shutil

        shutil.rmtree(dst.parent, ignore_errors=True)


def test_r81_absent_identity_is_never_done(tmp_path) -> None:
    dst = tmp_path / "a.txt"
    dst.write_text("x", encoding="utf-8")
    assert (
        _status_from_identity(
            dst, size=None, sha256=None, device=None, inode=None
        )
        == "needs_verify"
    )


def test_r81_wrong_hash_after_move_is_never_done(tmp_path) -> None:
    dst = tmp_path / "a.txt"
    dst.write_text("x", encoding="utf-8")
    expected = _identity_kwargs(dst)
    expected["sha256"] = "0" * 64
    assert _status_from_identity(dst, **expected) == "needs_verify"


def _crossfs_race_script(cwd: Path) -> str:
    return (
        "import os, sys, time\n"
        f"sys.path.insert(0, {str(cwd)!r})\n"
        "from pathlib import Path\n"
        "import filewizard.fsmove as fm\n"
        "src, dst, ready, go = map(Path, sys.argv[1:5])\n"
        "real_publish = fm._publish_noreplace\n"
        "def gated_publish(tmp, destination):\n"
        "    ready.write_text('ready')\n"
        "    deadline = time.monotonic() + 30\n"
        "    while not go.exists() and time.monotonic() < deadline:\n"
        "        time.sleep(0.01)\n"
        "    return real_publish(tmp, destination)\n"
        "fm._publish_noreplace = gated_publish\n"
        "try:\n"
        "    fm.move_noreplace(src, dst)\n"
        "except fm.DestinationExistsError:\n"
        "    os._exit(3)\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__, str(exc), file=sys.stderr)\n"
        "    os._exit(4)\n"
        "os._exit(0)\n"
    )


@pytest.mark.parametrize("occupant", ["empty", "nonempty", "symlink"])
def test_r82_exdev_publication_never_overwrites_substituted_object(
    tmp_path, occupant
) -> None:
    """Real EXDEV copy, paused before publication, then a foreign object appears."""
    dst_dir = _shm_dir(tmp_path, f"pub-{occupant}")
    src = tmp_path / "source.txt"
    dst = dst_dir / "target.txt"
    ready = tmp_path / "ready"
    go = tmp_path / "go"
    src.write_text("source-data", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _crossfs_race_script(Path.cwd()),
             str(src), str(dst), str(ready), str(go)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            assert proc.poll() is None
            time.sleep(0.01)
        assert ready.exists()
        if occupant == "empty":
            dst.write_bytes(b"")
        elif occupant == "nonempty":
            dst.write_text("foreign", encoding="utf-8")
        else:
            victim = dst_dir / "victim.txt"
            victim.write_text("precious", encoding="utf-8")
            dst.symlink_to(victim)
        go.write_text("go")
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 3, (out, err)
        assert src.read_text(encoding="utf-8") == "source-data"
        if occupant == "empty":
            assert dst.read_bytes() == b""
        elif occupant == "nonempty":
            assert dst.read_text(encoding="utf-8") == "foreign"
        else:
            assert dst.is_symlink()
            assert (dst_dir / "victim.txt").read_text(encoding="utf-8") == "precious"
        assert not list(dst_dir.glob(".target.txt.fwtmp-*"))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        import shutil

        shutil.rmtree(dst_dir, ignore_errors=True)


def test_r82_exdev_two_real_publishers_one_wins(tmp_path) -> None:
    dst_dir = _shm_dir(tmp_path, "publish-race")
    dst = dst_dir / "target.txt"
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "from pathlib import Path\n"
        "from filewizard.fsmove import move_noreplace, DestinationExistsError\n"
        "try:\n"
        "    move_noreplace(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        "except DestinationExistsError:\n"
        "    os._exit(3)\n"
        "os._exit(0)\n"
    )
    sources = []
    for tag in ("A", "B"):
        src = tmp_path / f"{tag}.txt"
        src.write_text(f"content-{tag}", encoding="utf-8")
        sources.append(src)
    try:
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(src), str(dst)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for src in sources
        ]
        results = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
        assert sorted(item[2] for item in results) == [0, 3], results
        assert dst.read_text(encoding="utf-8") in {"content-A", "content-B"}
        assert sum(src.exists() for src in sources) == 1
        assert not list(dst_dir.glob(".target.txt.fwtmp-*"))
    finally:
        import shutil

        shutil.rmtree(dst_dir, ignore_errors=True)


def test_r82_crash_after_publication_before_source_unlink(tmp_path) -> None:
    dst_dir = _shm_dir(tmp_path, "post-publish")
    src = tmp_path / "source.txt"
    dst = dst_dir / "target.txt"
    src.write_text("after-publish", encoding="utf-8")
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "from pathlib import Path\n"
        "from filewizard.fsmove import move_noreplace\n"
        "real_unlink = os.unlink\n"
        "def die(path, *a, **k):\n"
        "    if Path(path) == Path(sys.argv[1]):\n"
        "        os._exit(89)\n"
        "    return real_unlink(path, *a, **k)\n"
        "os.unlink = die\n"
        "move_noreplace(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        "os._exit(0)\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(src), str(dst)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 89, proc.stderr
        assert src.read_text(encoding="utf-8") == "after-publish"
        assert dst.read_text(encoding="utf-8") == "after-publish"
        assert not list(dst_dir.glob(".target.txt.fwtmp-*"))
    finally:
        import shutil

        shutil.rmtree(dst_dir, ignore_errors=True)


@pytest.mark.parametrize("occupant", ["empty", "symlink"])
def test_r83_reconcile_preserves_foreign_destination_and_backup(
    tmp_path, occupant
) -> None:
    from filewizard.executor import _planned_backup_path

    state = tmp_path / "state"
    src = tmp_path / "source.txt"
    dst = tmp_path / "target.txt"
    src.write_text("new", encoding="utf-8")
    with Journal(state / "journal.db") as journal:
        op_id = journal.start_operation(
            "b", "r", "move", src, dst, byte_size=3
        )
        backup = _planned_backup_path(journal, op_id, dst)
        journal.set_displaced(
            op_id, backup, **_displaced_record("old", dst)
        )
        backup.parent.mkdir(parents=True)
        backup.write_text("old", encoding="utf-8")
        if occupant == "empty":
            dst.write_bytes(b"")
        else:
            victim = tmp_path / "victim"
            victim.write_text("victim", encoding="utf-8")
            dst.symlink_to(victim)
        promoted, pending = journal.reconcile_pending()
        assert (promoted, pending) == (1, 0)
        row = journal.get_operation(op_id)
        assert row["status"] == "needs_verify"
        assert "occupied" in row["error"]
        assert backup.read_text(encoding="utf-8") == "old"
        if occupant == "empty":
            assert dst.read_bytes() == b""
        else:
            assert dst.is_symlink()
        assert journal.reconcile_pending() == (0, 0)


def _displaced_record(content: str, path: Path) -> dict:
    from filewizard.perception.cache import file_content_hash

    # Evidence is captured before the destination exists in this helper by
    # using a sibling with the displaced bytes.
    evidence = path.with_name(path.name + ".evidence")
    evidence.write_text(content, encoding="utf-8")
    identity = capture_identity(evidence)
    assert identity is not None
    evidence.unlink()
    return {
        "size": identity.size,
        "sha256": file_content_hash(evidence) if evidence.exists() else identity.sha256,
        "mtime_ns": identity.mtime_ns,
        "device": identity.device,
        "inode": identity.inode,
    }


def _replace(tmp_path: Path):
    """Run the production replace path and return its original journal row."""
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation

    state = tmp_path / "state"
    src = tmp_path / "source.txt"
    dst = tmp_path / "target.txt"
    src.write_text("new-content", encoding="utf-8")
    dst.write_text("old-occupant", encoding="utf-8")
    identity = capture_identity(src)
    op = PlannedOperation(
        source=src, rule_id="r", rule_name="R", destination=dst,
        on_collision="replace",
        conditions=[ConditionCheck("always", True, "x")],
        identity_size=identity.size,
        identity_sha256=identity.sha256,
        identity_mtime_ns=identity.mtime_ns,
        identity_dev=identity.device,
        identity_ino=identity.inode,
    )
    with Journal(state / "journal.db") as journal:
        result = Executor(journal=journal, dry_run=False).execute([op])[0]
        assert result.status == "done"
        return journal.last_successful_moves()[0]


def test_r84_lost_backup_and_absent_destination_stays_partial(tmp_path) -> None:
    row = _replace(tmp_path)
    state = tmp_path / "state"
    backup = Path(row["displaced_path"])
    dst = Path(row["destination"])
    backup.unlink()
    with Journal(state / "journal.db") as journal:
        result = undo_operations(journal, [row], dry_run=False)[0]
        assert result["displaced"] == "displaced_absent"
        assert journal.get_operation(int(row["id"]))["status"] == "undo_partial"
        assert not dst.exists()
        assert Path(row["source"]).read_text(encoding="utf-8") == "new-content"


def test_r84_lost_backup_foreign_occupant_is_not_undone(tmp_path) -> None:
    row = _replace(tmp_path)
    state = tmp_path / "state"
    dst = Path(row["destination"])
    Path(row["displaced_path"]).unlink()
    os.rename(dst, Path(row["source"]))  # effect A is verifiably home
    dst.write_text("foreign", encoding="utf-8")
    with Journal(state / "journal.db") as journal:
        result = undo_operations(journal, [row], dry_run=False)[0]
        assert result["status"] != "done"
        assert journal.get_operation(int(row["id"]))["status"] != "undone"
        assert dst.read_text(encoding="utf-8") == "foreign"


def _undo_crash_script(cwd: Path) -> str:
    """Full production undo flow; hard death before the intent-clear commit."""
    return (
        "import os, sys\n"
        f"sys.path.insert(0, {str(cwd)!r})\n"
        "from pathlib import Path\n"
        "from filewizard.executor import undo_operations\n"
        "from filewizard.journal import Journal\n"
        "state, op_id = Path(sys.argv[1]), int(sys.argv[2])\n"
        "journal = Journal(state / 'journal.db')\n"
        "row = journal.get_operation(op_id)\n"
        "def die(*a, **k):\n"
        "    os._exit(43)\n"
        "journal.clear_displaced = die\n"
        "undo_operations(journal, [row], dry_run=False)\n"
        "os._exit(0)\n"
    )


def test_r84_productive_undo_crash_then_converges_and_retry(tmp_path) -> None:
    row = _replace(tmp_path)
    state = tmp_path / "state"
    proc = subprocess.run(
        [sys.executable, "-c", _undo_crash_script(Path.cwd()),
         str(state), str(row["id"])],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 43, proc.stderr
    assert Path(row["source"]).read_text(encoding="utf-8") == "new-content"
    assert Path(row["destination"]).read_text(encoding="utf-8") == "old-occupant"
    with Journal(state / "journal.db") as journal:
        crashed = journal.get_operation(int(row["id"]))
        assert crashed["displaced_path"] is not None
        result = undo_operations(journal, [crashed], dry_run=False)[0]
        assert result["status"] == "already_restored"
        assert result["displaced_evidence"] == "content"
        assert journal.get_operation(int(row["id"]))["status"] == "undone"
        # Repeated retry is an explicit no-op, never another mutation.
        retry = undo_operations(journal, [crashed], dry_run=False)[0]
        assert retry["status"] == "skipped"


def test_r84_crash_during_undo_partial_retry_converges(tmp_path, monkeypatch) -> None:
    import filewizard.executor as executor_mod

    row = _replace(tmp_path)
    state = tmp_path / "state"
    monkeypatch.setattr(
        executor_mod,
        "_restore_displaced",
        lambda *a, **k: {"status": "displaced_error", "detail": "injected"},
    )
    with Journal(state / "journal.db") as journal:
        result = undo_operations(journal, [row], dry_run=False)[0]
        assert result["status"] == "undo_partial"
        assert journal.get_operation(int(row["id"]))["status"] == "undo_partial"
    monkeypatch.undo()
    proc = subprocess.run(
        [sys.executable, "-c", _undo_crash_script(Path.cwd()),
         str(state), str(row["id"])],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 43, proc.stderr
    with Journal(state / "journal.db") as journal:
        partial = journal.get_operation(int(row["id"]))
        result = undo_operations(journal, [partial], dry_run=False)[0]
        assert result["status"] == "displaced_already_restored"
        assert journal.get_operation(int(row["id"]))["status"] == "undone"


def test_r85_displaced_missing_corrupt_inaccessible_journal_fail_closed(
    tmp_path, monkeypatch
) -> None:
    from filewizard.displaced import (
        DisplacedError,
        displaced_root,
        purge_displaced,
        scan_displaced,
    )

    state = tmp_path / "state"
    root = displaced_root(state)
    root.mkdir(parents=True)
    backup = root / "1.txt"
    backup.write_text("keep", encoding="utf-8")
    for mutate in ("missing", "corrupt"):
        if mutate == "corrupt":
            (state / "journal.db").write_bytes(b"not sqlite")
        with pytest.raises(DisplacedError):
            scan_displaced(state)
        with pytest.raises(DisplacedError):
            purge_displaced(state, execute=True)
        assert backup.read_text(encoding="utf-8") == "keep"
        (state / "journal.db").unlink(missing_ok=True)

    # Create a recoverable journal, then make opening fail explicitly.
    with Journal(state / "journal.db") as journal:
        op_id = journal.start_operation("b", "r", "move", tmp_path / "a", tmp_path / "b")
        journal.set_displaced(op_id, backup, size=4)
    import sqlite3

    def denied(*a, **k):
        raise sqlite3.OperationalError("permission denied")

    monkeypatch.setattr(sqlite3, "connect", denied)
    with pytest.raises(DisplacedError):
        scan_displaced(state)
    monkeypatch.undo()
    report = scan_displaced(state)
    assert report.entries[0].protected
    assert backup.read_text(encoding="utf-8") == "keep"


def test_r85_replace_refuses_early_without_displace_capacity(
    tmp_path, monkeypatch
) -> None:
    import filewizard.executor as executor_mod
    import filewizard.fsmove as fsmove
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation

    src = tmp_path / "source"
    dst = tmp_path / "target"
    src.write_text("new-content", encoding="utf-8")
    dst.write_text("old-occupant", encoding="utf-8")
    identity = capture_identity(src)
    op = PlannedOperation(
        source=src, rule_id="r", rule_name="R", destination=dst,
        on_collision="replace", conditions=[ConditionCheck("always", True, "x")],
        identity_size=identity.size, identity_sha256=identity.sha256,
        identity_mtime_ns=identity.mtime_ns,
        identity_dev=identity.device, identity_ino=identity.inode,
    )
    monkeypatch.setattr(fsmove, "_same_fs", lambda a, b: False)

    class FullFS:
        f_bavail = 1
        f_frsize = 1

    monkeypatch.setattr(executor_mod.os, "statvfs", lambda p: FullFS())
    with Journal(tmp_path / "state" / "journal.db") as journal:
        result = Executor(journal=journal, dry_run=False).execute([op])[0]
        assert result.status == "error"
        assert "insufficient free space" in (result.error or "")
    assert src.read_text(encoding="utf-8") == "new-content"
    assert dst.read_text(encoding="utf-8") == "old-occupant"


def test_r86_real_exdev_preserves_mode_and_timestamps_in_move_backup_restore(
    tmp_path,
) -> None:
    import shutil
    from filewizard.engine import ConditionCheck
    from filewizard.executor import PlannedOperation

    dst_dir = _shm_dir(tmp_path, "metadata")
    src = tmp_path / "source.txt"
    dst = dst_dir / "target.txt"
    src.write_text("new-content", encoding="utf-8")
    dst.write_text("old-occupant", encoding="utf-8")
    os.chmod(src, 0o751)
    os.chmod(dst, 0o640)
    new_mtime = 1_650_000_000_123_456_789
    old_mtime = 1_640_000_000_987_654_321
    os.utime(src, ns=(new_mtime, new_mtime))
    os.utime(dst, ns=(old_mtime, old_mtime))
    identity = capture_identity(src)
    op = PlannedOperation(
        source=src, rule_id="r", rule_name="R", destination=dst,
        on_collision="replace", conditions=[ConditionCheck("always", True, "x")],
        identity_size=identity.size, identity_sha256=identity.sha256,
        identity_mtime_ns=identity.mtime_ns,
        identity_dev=identity.device, identity_ino=identity.inode,
    )
    try:
        with Journal(tmp_path / "state" / "journal.db") as journal:
            result = Executor(journal=journal, dry_run=False).execute([op])[0]
            assert result.status == "done"
            assert dst.stat().st_mode & 0o777 == 0o751
            assert dst.stat().st_mtime_ns == new_mtime
            row = journal.last_successful_moves()[0]
            backup = Path(row["displaced_path"])
            assert backup.stat().st_dev != dst_dir.stat().st_dev
            assert backup.stat().st_mode & 0o777 == 0o640
            assert backup.stat().st_mtime_ns == old_mtime
            result = undo_operations(journal, [row], dry_run=False)[0]
            assert result["status"] == "done"
            assert dst.stat().st_mode & 0o777 == 0o640
            assert dst.stat().st_mtime_ns == old_mtime
            assert src.stat().st_mode & 0o777 == 0o751
            assert src.stat().st_mtime_ns == new_mtime
    finally:
        shutil.rmtree(dst_dir, ignore_errors=True)


def test_r87_source_change_during_copy_retains_original_and_no_destination(
    tmp_path, monkeypatch
) -> None:
    import filewizard.fsmove as fsmove

    dst_dir = _shm_dir(tmp_path, "source-change")
    src = tmp_path / "source.txt"
    dst = dst_dir / "target.txt"
    src.write_text("before", encoding="utf-8")
    real_copy2 = fsmove.shutil.copy2

    def changing_copy(source, destination, **kwargs):
        result = real_copy2(source, destination, **kwargs)
        Path(source).write_text("mutate", encoding="utf-8")
        return result

    monkeypatch.setattr(fsmove.shutil, "copy2", changing_copy)
    try:
        with pytest.raises(OSError, match="source changed"):
            move_noreplace(src, dst)
        assert src.read_text(encoding="utf-8") == "mutate"
        assert not dst.exists()
        assert not list(dst_dir.glob(".target.txt.fwtmp-*"))
    finally:
        import shutil

        shutil.rmtree(dst_dir, ignore_errors=True)


@pytest.mark.parametrize("tag", ["after_displace_intent", "after_displace"])
def test_r88_w1_w2_resolve_pending_after_real_owner_death(tmp_path, tag) -> None:
    # Sibling-module import: pytest's prepend import mode puts tests/ on
    # sys.path, so this works under both `pytest` and `python -m pytest`
    # (an absolute `tests.` import only works in the latter).
    from test_integrity_remediation import (
        _crash_child_script,
        _run_crash_child,
    )

    state = tmp_path / "state"
    src = tmp_path / "source.txt"
    dst = tmp_path / "target.txt"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")
    _run_crash_child(
        _crash_child_script(Path.cwd()), [tag, str(state), str(src), str(dst)]
    )
    with Journal(state / "journal.db") as journal:
        assert len(journal.pending_operations()) == 1
        journal.reconcile_pending()
        # The owner really died (os._exit in another process), so stale rows
        # become interrupted rather than being retained for a live owner.
        assert journal.resolve_pending() == 1
        row = journal.recent_operations(limit=1)[0]
        assert row["status"] == "interrupted"


def test_r88_giveup_persistence_failure_has_observable_error_state(
    tmp_path, monkeypatch
) -> None:
    from click.testing import CliRunner
    from filewizard.cli import cli
    from filewizard.watch import _giveups_path, _record_giveup, read_giveup_error

    real_open = Path.open

    def failing_open(self, *args, **kwargs):
        if self == _giveups_path(tmp_path):
            raise OSError("read-only giveup log")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    assert not _record_giveup(
        tmp_path, source=tmp_path, path=tmp_path / "bad", attempts=3,
        last_status="error", reason="max_attempts_exhausted",
    )
    assert read_giveup_error(tmp_path)["error"] == "read-only giveup log"
    result = CliRunner().invoke(
        cli, ["watch", "giveups", "--state-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "persistence ERROR" in result.output
