"""WP-0.11.3: older_than_days and aspect ratio conditions."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filewizard.engine import Engine
from filewizard.facts import collect_facts
from filewizard.models import Action, Condition, Rule
from filewizard.ui.options import build_rule


def test_older_than_days(tmp_path: Path) -> None:
    path = tmp_path / "old.txt"
    path.write_text("x", encoding="utf-8")
    facts = collect_facts(path)
    old = replace(
        facts,
        mtime=datetime.now(timezone.utc) - timedelta(days=10),
    )
    fresh = replace(facts, mtime=datetime.now(timezone.utc) - timedelta(hours=1))
    rule = Rule(
        id="old",
        name="Old",
        when=Condition(older_than_days=7),
        then=Action(rename="{stem}.bak"),
    )
    engine = Engine([rule])
    assert list(engine.evaluate(old))
    assert not list(engine.evaluate(fresh))


def test_min_aspect_widescreen(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    base = collect_facts(path)
    wide = replace(base, width=1920, height=1080)
    tall = replace(base, width=1080, height=1920)
    missing = replace(base, width=None, height=None)
    rule = Rule(
        id="wide",
        name="Wide",
        when=Condition(min_aspect=1.5),
        then=Action(rename="{stem}.bak"),
    )
    engine = Engine([rule])
    assert list(engine.evaluate(wide))
    assert not list(engine.evaluate(tall))
    assert not list(engine.evaluate(missing))


def test_build_rule_older_than_days() -> None:
    rule = build_rule({"older_than_days": 14, "move_to": "~/Old"})
    assert rule.when.older_than_days == 14
    rule0 = build_rule({"extensions": "pdf", "move_to": "~/X"})
    assert rule0.when.older_than_days is None
