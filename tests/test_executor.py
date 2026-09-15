from pathlib import Path

import pytest

from filewizard.engine import Engine
from filewizard.executor import Executor, append_unique
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule


def _move_rule(dest: Path, **action_kwargs) -> Rule:
    return Rule(
        id="move",
        name="Move",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(dest), **action_kwargs),
    )


def _plan_execute(
    tmp_path: Path,
    source: Path,
    dest: Path,
    dry_run: bool = False,
    **action_kwargs,
):
    rule = _move_rule(dest, **action_kwargs)
    facts = collect_facts(source)
    matches = list(Engine([rule]).evaluate(facts))
    assert matches
    journal = Journal(tmp_path / "journal.db")
    executor = Executor(journal=journal, dry_run=dry_run)
    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
        conditions=matches[0].conditions,
    )
    results = executor.execute([op]) if op else []
    return journal, op, results


def test_destination_collision_skip(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (out / "a.txt").write_text("existing", encoding="utf-8")
    file = src / "a.txt"
    file.write_text("new", encoding="utf-8")

    _, op, results = _plan_execute(
        tmp_path, file, out, on_collision="skip"
    )
    assert op is not None
    assert op.status in {"skipped", "planned"}
    # plan marks skipped before execute when destination exists
    if op.status == "skipped":
        assert file.exists()
        assert (out / "a.txt").read_text(encoding="utf-8") == "existing"
    else:
        assert results[0].status == "skipped"
        assert file.exists()


def test_destination_collision_append(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (out / "a.txt").write_text("existing", encoding="utf-8")
    file = src / "a.txt"
    file.write_text("new", encoding="utf-8")

    journal, op, results = _plan_execute(
        tmp_path, file, out, on_collision="append"
    )
    assert results[0].status == "done"
    assert (out / "a.txt").read_text(encoding="utf-8") == "existing"
    assert (out / "a_1.txt").read_text(encoding="utf-8") == "new"
    assert not file.exists()
    journal.close()


def test_destination_collision_replace(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (out / "a.txt").write_text("existing", encoding="utf-8")
    file = src / "a.txt"
    file.write_text("new", encoding="utf-8")

    journal, op, results = _plan_execute(
        tmp_path, file, out, on_collision="replace"
    )
    assert results[0].status == "done"
    assert (out / "a.txt").read_text(encoding="utf-8") == "new"
    assert not file.exists()
    journal.close()


def test_source_missing_at_plan(tmp_path: Path) -> None:
    missing = tmp_path / "gone.txt"
    # Create, collect facts, then delete
    missing.write_text("x", encoding="utf-8")
    facts = collect_facts(missing)
    missing.unlink()

    rule = _move_rule(tmp_path / "out")
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    op = executor.plan(facts=facts, rule=rule, explanations=[])
    assert op is not None
    assert op.status == "error"
    assert "no longer exists" in (op.error or "")
    journal.close()


def test_source_missing_mid_execute(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    file = src / "a.txt"
    file.write_text("x", encoding="utf-8")

    rule = _move_rule(out)
    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
    )
    assert op is not None and op.status == "planned"
    file.unlink()
    results = executor.execute([op])
    assert results[0].status == "error"
    assert "no longer exists" in (results[0].error or "")
    journal.close()


def test_missing_destination_dir_without_create(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    file = src / "a.txt"
    file.write_text("x", encoding="utf-8")
    dest = tmp_path / "does-not-exist"

    journal, op, _ = _plan_execute(
        tmp_path, file, dest, create_target_dir=False
    )
    assert op is not None
    assert op.status == "error"
    assert "does not exist" in (op.error or "")
    journal.close()


def test_rename_collision_append(tmp_path: Path) -> None:
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    # rename to existing name in same dir
    (tmp_path / "b.txt").write_text("other", encoding="utf-8")

    rule = Rule(
        id="ren",
        name="Rename",
        priority=1,
        when=Condition(extensions=["txt"]),
        then=Action(rename="b.txt", on_collision="append"),
    )
    # Only match a.txt
    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
    )
    assert op is not None
    assert op.status == "planned"
    assert op.destination is not None
    assert op.destination.name == "b_1.txt"
    results = executor.execute([op])
    assert results[0].status == "done"
    assert (tmp_path / "b_1.txt").exists()
    journal.close()


def test_move_onto_self_is_noop(tmp_path: Path) -> None:
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")

    rule = Rule(
        id="noop",
        name="Noop",
        priority=1,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(tmp_path)),
    )
    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
    )
    assert op is not None
    assert op.status == "noop"
    results = executor.execute([op])
    assert results[0].status == "noop"
    assert file.exists()
    journal.close()


def test_execute_progress_counts_noop_and_missing(tmp_path: Path) -> None:
    """H2: every early-exit path still increments on_progress."""
    from filewizard.executor import PlannedOperation

    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    src = tmp_path / "gone.txt"
    dest = tmp_path / "out" / "gone.txt"
    ops = [
        PlannedOperation(
            source=src,
            rule_id="r",
            rule_name="r",
            destination=dest,
            status="planned",
        ),
        PlannedOperation(
            source=tmp_path / "a.txt",
            rule_id="r",
            rule_name="r",
            destination=tmp_path / "a.txt",
            status="planned",
        ),
    ]
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    seen: list[tuple[int, int]] = []
    executor.execute(ops, on_progress=lambda d, t: seen.append((d, t)))
    journal.close()
    assert seen == [(1, 2), (2, 2)]
    assert ops[0].status == "error"
    assert ops[1].status == "noop"


def test_mid_batch_failure_keeps_prior_successes(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()

    f1 = src / "ok1.txt"
    f2 = src / "ok2.txt"
    f3 = src / "fail.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")
    f3.write_text("3", encoding="utf-8")

    rule = _move_rule(out)
    engine = Engine([rule])
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)

    ops = []
    for path in (f1, f2, f3):
        facts = collect_facts(path)
        match = next(engine.evaluate(facts))
        ops.append(
            executor.plan(
                facts=facts,
                rule=match.rule,
                explanations=match.explanations,
            )
        )

    # Delete third source after planning so execute fails mid-batch
    f3.unlink()

    results = executor.execute(ops)
    assert results[0].status == "done"
    assert results[1].status == "done"
    assert results[2].status == "error"
    assert (out / "ok1.txt").exists()
    assert (out / "ok2.txt").exists()
    assert len(journal.last_successful_moves()) == 2
    journal.close()


def test_permission_denied_on_destination(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "locked"
    src.mkdir()
    out.mkdir()
    file = src / "a.txt"
    file.write_text("x", encoding="utf-8")

    # Make destination directory non-writable
    out.chmod(0o555)
    try:
        journal, op, results = _plan_execute(tmp_path, file, out)
        # On some systems root may still write; skip if so
        if results and results[0].status == "done":
            pytest.skip("environment allows write into mode 555")
        assert results[0].status == "error"
        assert results[0].error
        assert file.exists()  # not moved
        journal.close()
    finally:
        out.chmod(0o755)


def test_append_unique_helper(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("a", encoding="utf-8")
    assert append_unique(p) == tmp_path / "f_1.txt"
    (tmp_path / "f_1.txt").write_text("b", encoding="utf-8")
    assert append_unique(p) == tmp_path / "f_2.txt"
