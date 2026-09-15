from dataclasses import replace
from pathlib import Path

from filewizard.engine import Engine
from filewizard.facts import FileFacts, collect_facts
from filewizard.models import Action, Condition, Rule


def _txt_rule(**when_kwargs) -> Rule:
    return Rule(
        id="r1",
        name="R1",
        priority=10,
        when=Condition(**when_kwargs),
        then=Action(move_to="/tmp/out"),
    )


def test_structured_match_conditions(tmp_path: Path) -> None:
    file = tmp_path / "Screenshot_01.jpg"
    file.write_bytes(b"x" * 100)
    facts = collect_facts(file)

    rule = _txt_rule(
        filename_regex="(?i)screenshot",
        size_gt=10,
    )
    # Force mime via facts is guessed; filename is enough.
    matches = list(Engine([rule]).evaluate(facts))
    assert len(matches) == 1

    match = matches[0]
    assert match.conditions
    keys = {c.key for c in match.conditions}
    assert "filename" in keys
    assert "size_gt" in keys
    assert all(c.passed for c in match.conditions)
    assert match.explanations  # backward-compatible strings


def test_inspect_shows_failures(tmp_path: Path) -> None:
    file = tmp_path / "note.md"
    file.write_text("hi", encoding="utf-8")
    facts = collect_facts(file)

    rule = _txt_rule(extensions=["txt"], size_gt=1_000_000)
    checks = Engine([rule]).inspect(rule, facts)

    by_key = {c.key: c for c in checks}
    assert by_key["extension"].passed is False
    assert by_key["size_gt"].passed is False


def test_ocr_and_vision_conditions(tmp_path: Path) -> None:
    file = tmp_path / "doc.jpg"
    file.write_bytes(b"fake")
    facts = collect_facts(file)
    # inject features
    facts = FileFacts(
        path=facts.path,
        size=facts.size,
        mime=facts.mime,
        extension=facts.extension,
        filename=facts.filename,
        stem=facts.stem,
        mtime=facts.mtime,
        is_image=True,
        width=facts.width,
        height=facts.height,
        features={
            "ocr": {"text": "Factura Amazon total 99"},
            "vision": {"document": 0.95, "screenshot": 0.1},
        },
    )

    rule = Rule(
        id="inv",
        name="Invoice",
        priority=1,
        when=Condition(
            ocr_contains_any=["factura", "invoice"],
            vision_label_gt={"document": 0.9},
        ),
        then=Action(move_to=str(tmp_path / "out")),
    )

    matches = list(Engine([rule]).evaluate(facts))
    assert len(matches) == 1
    keys = {c.key for c in matches[0].conditions}
    assert "ocr_any" in keys
    assert "vision.document" in keys


def test_invalid_regex_fails_at_load(tmp_path: Path) -> None:
    """R3: invalid regex fails when the Condition is built, not mid-scan."""
    from pydantic import ValidationError

    try:
        Condition(filename_regex="[unclosed")
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_cascade_conditions(tmp_path: Path) -> None:
    file = tmp_path / "scan.jpg"
    file.write_bytes(b"fake")
    facts = collect_facts(file)
    facts = FileFacts(
        path=facts.path,
        size=facts.size,
        mime=facts.mime,
        extension=facts.extension,
        filename=facts.filename,
        stem=facts.stem,
        mtime=facts.mtime,
        is_image=True,
        width=facts.width,
        height=facts.height,
        features={
            "cascade": {
                "category": "factura",
                "status": "confirmed",
                "confidence": 0.88,
                "stage_used": 2,
            }
        },
    )

    rule = Rule(
        id="cas",
        name="Cascade factura",
        priority=1,
        when=Condition(
            cascade_category_any=["factura", "recibo"],
            cascade_status_any=["confirmed", "probable"],
            cascade_min_confidence=0.75,
        ),
        then=Action(move_to=str(tmp_path / "out")),
    )
    matches = list(Engine([rule]).evaluate(facts))
    assert len(matches) == 1
    keys = {c.key for c in matches[0].conditions}
    assert "cascade_category" in keys
    assert "cascade_status" in keys
    assert "cascade_min_confidence" in keys

    # Fail on low confidence
    rule_strict = Rule(
        id="cas2",
        name="Strict",
        priority=1,
        when=Condition(cascade_min_confidence=0.95),
        then=Action(move_to=str(tmp_path / "out")),
    )
    assert list(Engine([rule_strict]).evaluate(facts)) == []


def test_cascade_stage_max_condition(tmp_path: Path) -> None:
    file = tmp_path / "scan.jpg"
    file.write_bytes(b"fake")
    base = collect_facts(file)
    facts = FileFacts(
        path=base.path,
        size=base.size,
        mime=base.mime,
        extension=base.extension,
        filename=base.filename,
        stem=base.stem,
        mtime=base.mtime,
        is_image=True,
        width=base.width,
        height=base.height,
        features={"cascade": {"category": "factura", "stage_used": 1}},
    )

    def _rule(**kwargs) -> Rule:
        return Rule(
            id="smax",
            name="Stage cap",
            priority=1,
            when=Condition(**kwargs),
            then=Action(move_to=str(tmp_path / "out")),
        )

    # stage_used=1, cascade_stage_max=1 -> match
    assert list(Engine([_rule(cascade_stage_max=1)]).evaluate(facts))
    # stage_used=1, cascade_stage_max=0 -> no match
    assert not list(Engine([_rule(cascade_stage_max=0)]).evaluate(facts))
    # stage_used=3, cascade_stage_max=1 -> no match
    facts3 = replace(
        facts,
        features={"cascade": {"category": "factura", "stage_used": 3}},
    )
    assert not list(Engine([_rule(cascade_stage_max=1)]).evaluate(facts3))
    # no cascade features -> no match
    bare = replace(facts, features={})
    assert not list(Engine([_rule(cascade_stage_max=1)]).evaluate(bare))


def test_priority_order(tmp_path: Path) -> None:
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    facts = collect_facts(file)

    low = Rule(
        id="low",
        name="Low",
        priority=100,
        when=Condition(extensions=["txt"]),
        then=Action(rename="{stem}_low.{ext}"),
    )
    high = Rule(
        id="high",
        name="High",
        priority=1,
        when=Condition(extensions=["txt"]),
        then=Action(rename="{stem}_high.{ext}"),
    )

    matches = list(Engine([low, high]).evaluate(facts))
    assert matches[0].rule.id == "high"
