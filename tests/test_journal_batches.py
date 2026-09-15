from pathlib import Path

from filewizard.engine import Engine
from filewizard.executor import Executor, undo_operations
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule
from filewizard.ui.util import elide_middle, relative_time


def test_recent_batches_and_rule_name(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    for i in range(3):
        (src / f"a{i}.txt").write_text(str(i), encoding="utf-8")

    rule = Rule(
        id="move-txt",
        name="Mover textos",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(out)),
    )
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    engine = Engine([rule])

    ops = []
    for path in sorted(src.glob("*.txt")):
        facts = collect_facts(path)
        match = next(engine.evaluate(facts))
        ops.append(
            executor.plan(
                facts=facts,
                rule=match.rule,
                explanations=match.explanations,
            )
        )
    results = executor.execute(ops)
    assert all(r.status == "done" for r in results)

    batches = journal.recent_batches(10)
    assert len(batches) == 1
    b = batches[0]
    assert int(b["done"]) == 3
    assert "Mover textos" in (b["rule_names"] or "")
    assert "move" in (b["ops"] or "")

    rows = journal.operations_for_batch(b["batch_id"])
    assert len(rows) == 3
    assert rows[0]["rule_name"] == "Mover textos"

    done = journal.done_moves_for_batch(b["batch_id"])
    assert len(done) == 3

    # Undo becomes its own batch
    undo_operations(journal, done, dry_run=False)
    batches2 = journal.recent_batches(10)
    assert len(batches2) >= 2
    assert any("undo" in (b["ops"] or "") for b in batches2)

    journal.close()


def test_elide_and_relative_time() -> None:
    assert elide_middle("short") == "short"
    long = "a" * 80
    out = elide_middle(long, 20)
    assert "…" in out
    assert len(out) <= 20

    from datetime import datetime, timezone, timedelta

    iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert "h" in relative_time(iso) or "min" in relative_time(iso)
