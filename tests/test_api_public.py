"""D4: public API surface — versioned, dry-run default, deprecation helper."""

from __future__ import annotations

from pathlib import Path

from filewizard import api


def test_api_version_is_semver_string() -> None:
    assert isinstance(api.API_VERSION, str)
    major, minor = api.API_VERSION.split(".")
    assert major.isdigit() and minor.isdigit()


def test_plan_is_dry_run_by_default(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x")
    from filewizard.models import Rule, RuleSet

    ruleset = RuleSet(
        rules=[
            Rule(
                id="r1",
                name="m",
                when={"extensions": [".txt"]},
                then={"move_to": str(tmp_path / "out")},
                priority=1,
            )
        ]
    )
    operations, scanned = api.plan(src, ruleset, state_dir=tmp_path / "state")
    assert scanned == 1
    assert len(operations) == 1
    # No file was moved (dry-run / planning only).
    assert (src / "a.txt").exists()
    assert operations[0].status in {"planned", "dry-run", "needs-review"}


def test_deprecated_helper_warns() -> None:
    @api.deprecated("Use other_function() instead.")
    def old_function():
        return 42

    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = old_function()
    assert result == 42
    assert any(
        issubclass(item.category, DeprecationWarning) for item in w
    )


def test_api_undo_dry_run_default(tmp_path: Path) -> None:
    # undo() without execute=True must not mutate anything.
    state = tmp_path / "state"
    state.mkdir()
    result = api.undo(state)
    assert result == []
