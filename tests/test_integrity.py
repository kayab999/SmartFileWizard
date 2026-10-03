"""Plan identity, undo hash, replace backup, and exclusive destination names."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from filewizard.engine import Engine
from filewizard.executor import Executor, append_unique, undo_operations
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule
from filewizard.perception.cache import file_content_hash


def _rule(dest: Path, collision: str = "append") -> Rule:
    return Rule(
        id="mv",
        name="mv",
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(dest), on_collision=collision),
    )


def _execute(tmp_path: Path, name: str, text: str, collision: str = "append"):
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    file = src / name
    file.write_text(text, encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    engine = Engine([_rule(out, collision)])
    executor = Executor(journal=journal, dry_run=False)
    facts = collect_facts(file)
    match = next(engine.evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=[])
    assert op is not None
    results = executor.execute([op])
    return journal, file, out, results


def test_same_size_rewrite_with_restored_mtime_is_stale(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    file = src / "a.txt"
    file.write_text("hello", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    engine = Engine([_rule(out)])
    executor = Executor(journal=journal, dry_run=False)
    facts = collect_facts(file)
    match = next(engine.evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=[])
    assert op is not None
    stamp = file.stat().st_mtime_ns
    file.write_text("hellp", encoding="utf-8")
    os.utime(file, ns=(stamp, stamp))
    results = executor.execute([op])
    journal.close()
    assert results[0].status == "stale"
    assert file.is_file()
    assert not (out / "a.txt").exists()


def test_undo_refuses_hash_mismatch_when_size_matches(tmp_path: Path) -> None:
    journal, _file, out, results = _execute(tmp_path, "a.txt", "hello")
    assert results[0].status == "done"
    moved = out / "a.txt"
    moved.write_text("hellp", encoding="utf-8")
    rows = journal.last_successful_moves()
    undone = undo_operations(journal, rows, dry_run=False)
    journal.close()
    assert undone[0]["status"] == "state_mismatch"
    assert "hash" in undone[0]["error"]
    assert moved.read_text(encoding="utf-8") == "hellp"


def test_reconcile_ignores_stranger_of_the_same_size(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    dest = tmp_path / "out" / "a.txt"
    source.write_text("hello", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    journal.start_operation(
        batch_id="b",
        rule_id="r",
        op="move",
        source=source,
        destination=dest,
        byte_size=source.stat().st_size,
        content_sha256=file_content_hash(source),
    )
    dest.parent.mkdir()
    dest.write_text("hellp", encoding="utf-8")
    source.unlink()
    promoted, remaining = journal.reconcile_pending()
    journal.close()
    assert promoted == 0
    assert remaining == 1


def test_replace_failure_restores_the_previous_file(tmp_path: Path, monkeypatch) -> None:
    real_move = __import__("shutil").move

    def boom(src, dst, *args, **kwargs):
        if "displaced" in str(src):
            return real_move(src, dst)
        raise OSError("disk full")

    monkeypatch.setattr("filewizard.executor.shutil.move", boom)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_text("old", encoding="utf-8")
    src = tmp_path / "in"
    src.mkdir()
    file = src / "a.txt"
    file.write_text("new", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    engine = Engine([_rule(out, "replace")])
    executor = Executor(journal=journal, dry_run=False)
    facts = collect_facts(file)
    match = next(engine.evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=[])
    assert op is not None
    results = executor.execute([op])
    journal.close()
    assert results[0].status == "error"
    assert (out / "a.txt").read_text(encoding="utf-8") == "old"
    assert file.read_text(encoding="utf-8") == "new"


def test_undo_replace_restores_both_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_text("old", encoding="utf-8")
    src = tmp_path / "in"
    src.mkdir()
    file = src / "a.txt"
    file.write_text("new", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    engine = Engine([_rule(out, "replace")])
    executor = Executor(journal=journal, dry_run=False)
    facts = collect_facts(file)
    match = next(engine.evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=[])
    assert op is not None
    results = executor.execute([op])
    assert results[0].status == "done"
    assert (out / "a.txt").read_text(encoding="utf-8") == "new"
    rows = journal.last_successful_moves()
    undone = undo_operations(journal, rows, dry_run=False)
    journal.close()
    assert undone[0]["status"] == "done"
    assert file.read_text(encoding="utf-8") == "new"
    assert (out / "a.txt").read_text(encoding="utf-8") == "old"


def test_append_unique_two_threads_get_different_names(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    barrier = threading.Barrier(2)
    found: list[Path] = []

    def worker() -> None:
        barrier.wait()
        found.append(append_unique(target))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(found)) == 2
    assert all(path.is_file() for path in found)


def test_unknown_condition_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        Condition(extensions_typo=["pdf"])  # type: ignore[call-arg]


def test_description_on_ruleset_is_kept() -> None:
    from filewizard.models import RuleSet

    rules = RuleSet.model_validate(
        {
            "description": "notes",
            "rules": [
                {
                    "id": "r",
                    "name": "R",
                    "when": {"extensions": ["txt"]},
                    "then": {"move_to": "/tmp/out"},
                }
            ],
        }
    )
    assert rules.description == "notes"
