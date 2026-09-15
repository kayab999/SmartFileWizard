from pathlib import Path

from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.pipeline import (
    default_extractors,
    load_ruleset,
    plan_operations,
    resolve_rules_path,
)


def test_resolve_and_load_rules_sharp() -> None:
    path = resolve_rules_path("rules_sharp.yaml")
    ruleset = load_ruleset(path)
    assert len(ruleset.rules) >= 5
    ids = [r.id for r in ruleset.rules]
    assert "screenshots-by-name" in ids
    assert "images-misc" in ids


def test_plan_operations_multi_rule_cascade(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()

    (src / "Screenshot_1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (src / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (src / "note.txt").write_text("x", encoding="utf-8")

    ruleset = RuleSet(
        version=1,
        rules=[
            Rule(
                id="shots",
                name="Capturas",
                priority=10,
                when=Condition(filename_regex="(?i)screenshot"),
                then=Action(move_to=str(out / "shots")),
            ),
            Rule(
                id="imgs",
                name="Imágenes",
                priority=20,
                when=Condition(mime_prefixes=["image/"]),
                then=Action(move_to=str(out / "imgs")),
            ),
            Rule(
                id="txt",
                name="Texto",
                priority=30,
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(out / "txt")),
            ),
        ],
    )

    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=True)
    ops, scanned = plan_operations(
        source=src,
        rules=ruleset,
        executor=executor,
        extractors=default_extractors(ocr=False),
    )
    journal.close()

    assert scanned == 3
    by_name = {Path(op.source).name: op.rule_id for op in ops}
    assert by_name["Screenshot_1.png"] == "shots"
    assert by_name["foto.png"] == "imgs"
    assert by_name["note.txt"] == "txt"


def test_ui_ruleset_from_options_cascade(tmp_path: Path) -> None:
    from filewizard.ui.workers import ruleset_from_options

    ruleset = ruleset_from_options({"rules_file": "rules_sharp.yaml"})
    assert len(ruleset.rules) > 1

    single = ruleset_from_options(
        {
            "always": True,
            "move_to": str(tmp_path / "x"),
            "rule_name": "One",
        }
    )
    assert len(single.rules) == 1
    assert single.rules[0].name == "One"
