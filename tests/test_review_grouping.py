"""Unit tests for destination grouping logic (no Qt UI required)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from filewizard.ui.wizard import ReviewPage
except ImportError:
    pytest.skip("PySide6 not installed — skipping wizard grouping tests", allow_module_level=True)


def _op(source: str, dest: str | None, status: str = "planned", rule_id: str = "r"):
    return SimpleNamespace(
        source=Path(source),
        destination=Path(dest) if dest else None,
        status=status,
        rule_id=rule_id,
        explanations=["ok"],
        error=None,
    )


def test_destination_group_key() -> None:
    op = _op("/a/b/file.png", "/x/y/2026/file.png")
    assert ReviewPage._destination_group_key(op) == "/x/y/2026"

    op2 = _op("/a/b/file.png", None)
    assert "sin destino" in ReviewPage._destination_group_key(op2)


def test_grouping_counts() -> None:
    ops = [
        _op("/in/a.png", "/out/shots/a.png", rule_id="shots"),
        _op("/in/b.png", "/out/shots/b.png", rule_id="shots"),
        _op("/in/c.png", "/out/photos/c.png", rule_id="photos"),
        _op("/in/d.png", None, status="error", rule_id="shots"),
    ]

    groups: dict[str, list[int]] = {}
    for i, op in enumerate(ops):
        key = ReviewPage._destination_group_key(op)
        groups.setdefault(key, []).append(i)

    assert len(groups["/out/shots"]) == 2
    assert len(groups["/out/photos"]) == 1
    assert any("sin destino" in k for k in groups)
