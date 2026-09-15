from pathlib import Path

from filewizard.engine import Engine
from filewizard.executor import Executor, undo_operations
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule


def _move_all_txt(src_dir: Path, out_dir: Path, journal: Journal) -> list:
    rule = Rule(
        id="move-txt",
        name="Move TXT",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(out_dir), create_target_dir=True),
    )
    engine = Engine([rule])
    executor = Executor(journal=journal, dry_run=False)
    ops = []
    for path in sorted(src_dir.glob("*.txt")):
        facts = collect_facts(path)
        match = next(engine.evaluate(facts))
        op = executor.plan(
            facts=facts,
            rule=match.rule,
            explanations=match.explanations,
        )
        ops.append(op)
    return executor.execute(ops)


def test_partial_batch_then_undo_successes_only(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()

    for i in range(5):
        (src / f"f{i}.txt").write_text(str(i), encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    rule = Rule(
        id="move-txt",
        name="Move TXT",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(out)),
    )
    engine = Engine([rule])
    executor = Executor(journal=journal, dry_run=False)

    ops = []
    paths = sorted(src.glob("*.txt"))
    for path in paths:
        facts = collect_facts(path)
        match = next(engine.evaluate(facts))
        ops.append(
            executor.plan(
                facts=facts,
                rule=match.rule,
                explanations=match.explanations,
            )
        )

    # Fail the last two at execute time
    paths[3].unlink()
    paths[4].unlink()

    results = executor.execute(ops)
    done = [r for r in results if r.status == "done"]
    failed = [r for r in results if r.status == "error"]
    assert len(done) == 3
    assert len(failed) == 2

    rows = journal.last_successful_moves()
    assert len(rows) == 3

    undo_results = undo_operations(journal, rows, dry_run=False)
    assert all(r["status"] == "done" for r in undo_results)
    # Original three restored
    assert len(list(src.glob("*.txt"))) == 3
    assert len(list(out.glob("*.txt"))) == 0
    # Undone ops no longer listed
    assert journal.last_successful_moves() == []
    journal.close()


def test_double_undo_is_safe(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    _move_all_txt(src, out, journal)

    rows = journal.last_successful_moves()
    assert len(rows) == 1

    first = undo_operations(journal, rows, dry_run=False)
    assert first[0]["status"] == "done"
    assert (src / "a.txt").exists()

    # Second undo: no remaining done moves
    rows2 = journal.last_successful_moves()
    assert rows2 == []
    second = undo_operations(journal, rows, dry_run=False)
    # Old row status is now undone → skipped
    assert second[0]["status"] == "skipped"
    journal.close()


def test_undo_missing_destination_refuses(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    _move_all_txt(src, out, journal)

    moved = out / "a.txt"
    assert moved.exists()
    moved.unlink()  # user deleted

    rows = journal.last_successful_moves()
    results = undo_operations(journal, rows, dry_run=False)
    assert results[0]["status"] == "missing"
    # Still listed as done (not silently cleared)
    assert len(journal.last_successful_moves()) == 1
    journal.close()


def test_undo_size_mismatch_refuses(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    _move_all_txt(src, out, journal)

    moved = out / "a.txt"
    moved.write_text("hello world modified", encoding="utf-8")

    rows = journal.last_successful_moves()
    results = undo_operations(journal, rows, dry_run=False)
    assert results[0]["status"] == "state_mismatch"
    assert "Size mismatch" in (results[0].get("error") or "")
    # File left intact at destination
    assert moved.exists()
    assert journal.last_successful_moves()  # still done
    journal.close()


def test_undo_does_not_overwrite_original_path(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("moved-content", encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    _move_all_txt(src, out, journal)

    # User creates a new file at original path
    (src / "a.txt").write_text("user-new-file", encoding="utf-8")

    rows = journal.last_successful_moves()
    results = undo_operations(journal, rows, dry_run=False)
    assert results[0]["status"] == "done_with_conflict"
    assert results[0]["conflict"] is True
    # Original user file preserved
    assert (src / "a.txt").read_text(encoding="utf-8") == "user-new-file"
    # Restored content under unique name
    restored = Path(results[0]["destination"])
    assert restored.exists()
    assert restored.read_text(encoding="utf-8") == "moved-content"
    journal.close()


def test_undo_dry_run_does_not_change_fs(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    journal = Journal(tmp_path / "j.db")
    _move_all_txt(src, out, journal)

    rows = journal.last_successful_moves()
    results = undo_operations(journal, rows, dry_run=True)
    assert results[0]["status"] == "dry-run"
    assert (out / "a.txt").exists()
    assert not (src / "a.txt").exists()
    journal.close()
