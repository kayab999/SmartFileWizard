from pathlib import Path

from filewizard.engine import Engine
from filewizard.executor import Executor, undo_operations
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule
from filewizard.template import TemplateError, render_filename_template


def test_match_and_move_txt(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    source_dir.mkdir()
    output_dir.mkdir()

    file = source_dir / "note.txt"
    file.write_text("hello", encoding="utf-8")

    rule = Rule(
        id="move-txt",
        name="Move TXT files",
        priority=10,
        when=Condition(
            extensions=["txt"],
        ),
        then=Action(
            move_to=str(output_dir),
            create_target_dir=True,
            on_collision="append",
        ),
    )

    engine = Engine([rule])

    facts = collect_facts(file)

    matches = list(engine.evaluate(facts))
    assert len(matches) == 1
    assert any("extension" in e for e in matches[0].explanations)

    journal = Journal(tmp_path / "journal.db")
    executor = Executor(journal=journal, dry_run=False)

    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
        conditions=matches[0].conditions,
    )

    assert op is not None
    assert op.status == "planned"
    assert op.conditions
    assert op.conditions[0].key == "extension"

    results = executor.execute([op])

    assert results[0].status == "done"
    assert (output_dir / "note.txt").exists()
    assert not file.exists()

    journal.close()


def test_no_match_for_other_extension(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source_dir.mkdir()

    file = source_dir / "note.md"
    file.write_text("hello", encoding="utf-8")

    rule = Rule(
        id="move-txt",
        name="Move TXT files",
        priority=10,
        when=Condition(
            extensions=["txt"],
        ),
        then=Action(
            move_to=str(tmp_path / "output"),
        ),
    )

    engine = Engine([rule])
    facts = collect_facts(file)

    matches = list(engine.evaluate(facts))

    assert len(matches) == 0


def test_dry_run_does_not_move(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()

    file = source_dir / "note.txt"
    file.write_text("hello", encoding="utf-8")

    rule = Rule(
        id="move-txt",
        name="Move TXT files",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(output_dir)),
    )

    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))

    journal = Journal(tmp_path / "journal.db")
    executor = Executor(journal=journal, dry_run=True)

    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
    )
    assert op is not None
    assert op.status == "planned"

    results = executor.execute([op])
    assert results[0].status == "dry-run"
    assert file.exists()
    assert not (output_dir / "note.txt").exists()

    journal.close()


def test_undo_restores_file(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()

    file = source_dir / "note.txt"
    file.write_text("hello", encoding="utf-8")

    rule = Rule(
        id="move-txt",
        name="Move TXT files",
        priority=10,
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(output_dir)),
    )

    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))

    journal_path = tmp_path / "journal.db"
    journal = Journal(journal_path)
    executor = Executor(journal=journal, dry_run=False)

    op = executor.plan(
        facts=facts,
        rule=matches[0].rule,
        explanations=matches[0].explanations,
    )
    results = executor.execute([op])
    assert results[0].status == "done"
    assert (output_dir / "note.txt").exists()

    rows = journal.last_successful_moves(limit=10)
    assert len(rows) == 1

    undo_results = undo_operations(journal, rows, dry_run=False)
    assert undo_results[0]["status"] == "done"
    assert file.exists() or any(source_dir.glob("note*.txt"))
    assert file.read_text(encoding="utf-8") == "hello"

    journal.close()


def test_invalid_filename_template(tmp_path: Path) -> None:
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    facts = collect_facts(file)

    try:
        render_filename_template("bad/name", facts)
        assert False, "expected TemplateError"
    except TemplateError:
        pass


def test_filename_regex_match(tmp_path: Path) -> None:
    file = tmp_path / "Screenshot_001.png"
    file.write_bytes(b"\x89PNG\r\n\x1a\n")

    rule = Rule(
        id="shots",
        name="Screenshots",
        priority=10,
        when=Condition(
            filename_regex="(?i)screenshot",
        ),
        then=Action(rename="{date}_{original_name}"),
    )

    facts = collect_facts(file)
    matches = list(Engine([rule]).evaluate(facts))
    assert len(matches) == 1
