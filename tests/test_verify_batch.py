from pathlib import Path

from click.testing import CliRunner

from filewizard.cli import cli
from filewizard.engine import Engine
from filewizard.executor import Executor, undo_operations
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule
from filewizard.verify_batch import format_report, verify_batch


def _move_txt(src: Path, out: Path, journal: Journal, *, on_collision: str = "append"):
    rule = Rule(
        id="move-txt",
        name="Move TXT",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(out), on_collision=on_collision),
    )
    engine = Engine([rule])
    executor = Executor(journal=journal, dry_run=False)
    path = src / "a.txt"
    facts = collect_facts(path)
    match = next(engine.evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=match.explanations)
    executor.execute([op])
    return journal.recent_batches(limit=1)[0]["batch_id"]


def test_done_move_holds_then_diverges(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    journal_path = tmp_path / "j.db"
    journal = Journal(journal_path)
    batch_id = _move_txt(src, out, journal)
    journal.close()

    report = verify_batch(journal_path, batch_id, tmp_path / "review_queue.json")
    assert report.passed
    assert report.done == 1
    assert report.holds == 1
    assert "FREEZE PASS" in format_report(report)

    moved = out / "a.txt"
    moved.write_text("hello!", encoding="utf-8")
    drifted = verify_batch(journal_path, batch_id)
    assert not drifted.passed
    assert drifted.divergences[0].detail.startswith("destination")

    moved.write_text("hello", encoding="utf-8")
    (src / "a.txt").write_text("hello", encoding="utf-8")
    source_left = verify_batch(journal_path, batch_id)
    assert not source_left.passed
    assert "source still present" in source_left.divergences[0].detail


def test_skipped_expects_the_source_to_remain(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("stay", encoding="utf-8")
    journal_path = tmp_path / "j.db"
    journal = Journal(journal_path)
    op_id = journal.start_operation(
        batch_id="skip-1",
        rule_id="r",
        op="move",
        source=source,
        destination=tmp_path / "out" / "a.txt",
        byte_size=source.stat().st_size,
    )
    journal.finish_operation(op_id, status="skipped")
    journal.close()

    report = verify_batch(journal_path, "skip-1")
    assert report.passed
    assert report.done == 0
    assert report.holds == 1

    source.unlink()
    missing = verify_batch(journal_path, "skip-1")
    assert not missing.passed
    assert "source" in missing.divergences[0].detail


def test_undone_conflict_uses_the_undo_receipt(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("moved-content", encoding="utf-8")
    journal_path = tmp_path / "j.db"
    journal = Journal(journal_path)
    move_batch = _move_txt(src, out, journal)
    (src / "a.txt").write_text("user-new-file", encoding="utf-8")
    undo_operations(journal, journal.done_moves_for_batch(move_batch), dry_run=False)
    undo_batch = journal.recent_batches(limit=1)[0]["batch_id"]
    journal.close()

    move_report = verify_batch(journal_path, move_batch)
    assert move_report.passed
    assert (src / "a_1.txt").read_text(encoding="utf-8") == "moved-content"

    undo_report = verify_batch(journal_path, undo_batch)
    assert undo_report.passed
    assert undo_report.done == 1


def test_pending_and_unknown_batch_fail(tmp_path: Path) -> None:
    journal_path = tmp_path / "j.db"
    journal = Journal(journal_path)
    journal.start_operation(
        batch_id="open",
        rule_id="r",
        op="move",
        source=tmp_path / "a.txt",
        destination=tmp_path / "b.txt",
        byte_size=1,
    )
    journal.close()

    pending = verify_batch(journal_path, "open")
    assert not pending.passed
    assert pending.divergences[0].detail == "operation still pending"

    unknown = verify_batch(journal_path, "missing-batch")
    assert not unknown.passed
    assert unknown.problem == "No operations recorded for batch missing-batch."


def test_unresolved_review_blocks_an_otherwise_good_batch(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    journal_path = tmp_path / "j.db"
    journal = Journal(journal_path)
    batch_id = _move_txt(src, out, journal)
    journal.close()
    source = str(src / "a.txt")
    queue = tmp_path / "review_queue.json"
    queue.write_text(
        '{"items": ['
        f'{{"path": "{source}", "resolved": false}},'
        f'{{"path": "{out / "other.txt"}", "resolved": false}},'
        f'{{"path": "{source}", "resolved": true}}'
        "]}",
        encoding="utf-8",
    )

    blocked = verify_batch(journal_path, batch_id, queue)
    assert not blocked.passed
    assert blocked.holds == 1
    assert blocked.awaiting_review == [source]

    queue.write_text(
        f'{{"items": [{{"path": "{source}", "resolved": true}}]}}',
        encoding="utf-8",
    )
    clear = verify_batch(journal_path, batch_id, queue)
    assert clear.passed


def test_missing_journal_and_corrupt_queue_are_not_rewritten(tmp_path: Path) -> None:
    journal_path = tmp_path / "absent" / "journal.db"
    before = list(tmp_path.iterdir())
    missing = verify_batch(journal_path, "any", tmp_path / "review_queue.json")
    assert not missing.passed
    assert "No journal at" in (missing.problem or "")
    assert list(tmp_path.iterdir()) == before
    assert not journal_path.exists()

    journal = Journal(tmp_path / "j.db")
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    journal.start_operation(
        batch_id="b",
        rule_id="r",
        op="move",
        source=src,
        destination=tmp_path / "out" / "a.txt",
        byte_size=1,
    )
    journal.finish_operation(1, status="done", destination=tmp_path / "out" / "a.txt")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.txt").write_text("x", encoding="utf-8")
    src.unlink()
    journal.close()

    queue = tmp_path / "review_queue.json"
    queue.write_text("{", encoding="utf-8")
    snapshot = queue.read_bytes()
    journal_bytes = (tmp_path / "j.db").read_bytes()
    report = verify_batch(tmp_path / "j.db", "b", queue)
    assert not report.passed
    assert "left unchanged" in (report.problem or "")
    assert queue.read_bytes() == snapshot
    assert (tmp_path / "j.db").read_bytes() == journal_bytes


def test_cli_lists_batches_and_checks_one(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    state = tmp_path / "state"
    journal = Journal(state / "journal.db")
    batch_id = _move_txt(src, out, journal)
    journal.close()

    runner = CliRunner()
    listed = runner.invoke(cli, ["verify", "--state-dir", str(state)])
    assert listed.exit_code == 0
    assert batch_id in listed.output

    checked = runner.invoke(
        cli, ["verify", "--batch", batch_id, "--state-dir", str(state)]
    )
    assert checked.exit_code == 0
    assert "FREEZE PASS" in checked.output

    empty = tmp_path / "empty-home"
    fresh = runner.invoke(cli, ["verify", "--state-dir", str(empty)])
    assert fresh.exit_code == 0
    assert "No journal at" in fresh.output
    assert not empty.exists()

    failed = runner.invoke(
        cli, ["verify", "--batch", "no-such", "--state-dir", str(empty)]
    )
    assert failed.exit_code == 1
    assert "FREEZE FAIL" in failed.output
    assert not (empty / "journal.db").exists()


def test_checker_names_no_builtin_library() -> None:
    source = Path(__file__).resolve().parents[1].joinpath(
        "src", "filewizard", "verify_batch.py"
    ).read_text(encoding="utf-8")
    cli_source = Path(__file__).resolve().parents[1].joinpath(
        "src", "filewizard", "cli.py"
    ).read_text(encoding="utf-8")
    for text in (source, cli_source):
        assert "JUEGOS" not in text
        assert "/media/" not in text
