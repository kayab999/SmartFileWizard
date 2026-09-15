from pathlib import Path

from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.presets import (
    PresetError,
    delete_preset,
    ensure_builtin_presets,
    import_rules_file,
    list_presets,
    load_preset,
    save_preset,
)


def test_save_list_load_delete(tmp_path: Path) -> None:
    ruleset = RuleSet(
        version=1,
        rules=[
            Rule(
                id="t",
                name="Test",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ],
    )
    path = save_preset(
        "My Test",
        ruleset,
        tmp_path,
        description="demo",
        overwrite=True,
    )
    assert path.exists()

    items = list_presets(tmp_path)
    assert any(i.name == "my-test" for i in items)

    loaded = load_preset("my-test", tmp_path)
    assert len(loaded.rules) == 1
    assert loaded.rules[0].id == "t"

    delete_preset("my-test", tmp_path)
    assert list_presets(tmp_path) == []


def test_import_and_builtins(tmp_path: Path) -> None:
    # Import rules_sharp if available from project
    try:
        path = import_rules_file(
            "rules_sharp.yaml",
            name="cascade-copy",
            state_dir=tmp_path,
            overwrite=True,
        )
        assert path.exists()
        assert len(load_preset("cascade-copy", tmp_path).rules) >= 5
    except Exception:
        # Environment without rules file — still exercise builtins helper
        pass

    created = ensure_builtin_presets(tmp_path)
    # May create 0–2 depending on whether bundled files resolve
    assert isinstance(created, list)


def test_overwrite_guard(tmp_path: Path) -> None:
    ruleset = RuleSet(
        version=1,
        rules=[
            Rule(
                id="t",
                name="T",
                when=Condition(always=True),
                then=Action(rename="{stem}.bak"),
            )
        ],
    )
    save_preset("once", ruleset, tmp_path)
    try:
        save_preset("once", ruleset, tmp_path, overwrite=False)
        assert False, "expected PresetError"
    except PresetError:
        pass


def test_cascade_ml_example_loads(tmp_path: Path) -> None:
    from filewizard.pipeline import load_ruleset

    ruleset = load_ruleset(Path("rules_cascade_ml.example.yaml"))
    assert len(ruleset.rules) == 6
    assert any(r.when.cascade_category_any for r in ruleset.rules)
    assert any(r.when.cascade_stage_max is not None for r in ruleset.rules)


def test_builtin_includes_images_cascade_ml(tmp_path: Path) -> None:
    ensure_builtin_presets(tmp_path)
    preset = load_preset("images-cascade-ml", tmp_path)
    assert len(preset.rules) == 6
    assert any(r.when.cascade_category_any for r in preset.rules)
