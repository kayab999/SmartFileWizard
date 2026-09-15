"""Afilado de reglas y templates (0.9.x): negación por patrón + {cascade_category}."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from filewizard.engine import Engine
from filewizard.facts import collect_facts
from filewizard.models import Action, Condition, Rule
from filewizard.template import (
    CASCADE_CATEGORY_FALLBACK,
    cascade_category_slug,
    render_path_template,
)


def _rule(**when) -> Rule:
    return Rule(
        id="r",
        name="R",
        priority=10,
        when=Condition(**when),
        then=Action(move_to="~/Pictures/X"),
    )


def _facts_with_patterns(tmp_path: Path, name: str, patterns: list[str]):
    target = tmp_path / name
    target.write_text("x", encoding="utf-8")
    facts = collect_facts(target)
    return replace(facts, features={**facts.features, "filename_patterns": patterns})


def test_not_filename_pattern_blocks(tmp_path: Path) -> None:
    facts = _facts_with_patterns(tmp_path, "IMG-2024-WA001.jpg", ["whatsapp"])
    matches = list(
        Engine([_rule(not_filename_pattern_any=["whatsapp"])]).evaluate(facts)
    )
    assert matches == []


def test_not_filename_pattern_passes_without_match(tmp_path: Path) -> None:
    facts = _facts_with_patterns(tmp_path, "IMG-2024.jpg", ["camera"])
    matches = list(
        Engine([_rule(not_filename_pattern_any=["whatsapp"])]).evaluate(facts)
    )
    assert len(matches) == 1
    assert matches[0].conditions[-1].key == "not_filename_pattern"


def test_not_filename_pattern_empty_features_pass(tmp_path: Path) -> None:
    target = tmp_path / "plain.txt"
    target.write_text("x", encoding="utf-8")
    facts = collect_facts(target)
    assert "filename_patterns" not in facts.features
    matches = list(
        Engine([_rule(not_filename_pattern_any=["whatsapp"])]).evaluate(facts)
    )
    assert len(matches) == 1


def test_camera_rule_excludes_whatsapp_filename(tmp_path: Path) -> None:
    """End-to-end del choque IMG-WA: la regla de cámara no debe matchear."""
    target = tmp_path / "IMG-20240101-WA0001.jpg"
    target.write_bytes(b"\xff\xd8fake")
    facts = collect_facts(target)
    camera = Rule(
        id="camera-photos",
        name="Fotos de cámara",
        priority=20,
        when=Condition(
            mime_prefixes=["image/"],
            not_filename_regex="(?i)WA[-_]?\\d|whatsapp",
        ),
        then=Action(move_to="~/Pictures/Camera"),
    )
    assert list(Engine([camera]).evaluate(facts)) == []


def test_cascade_category_slug_values(tmp_path: Path) -> None:
    target = tmp_path / "a.jpg"
    target.write_text("x", encoding="utf-8")
    base = collect_facts(target)

    with_cascade = replace(
        base, features={**base.features, "cascade": {"category": "factura"}}
    )
    assert cascade_category_slug(with_cascade) == "factura"

    assert cascade_category_slug(base) == CASCADE_CATEGORY_FALLBACK
    unknown = replace(
        base, features={**base.features, "cascade": {"category": "unknown"}}
    )
    assert cascade_category_slug(unknown) == CASCADE_CATEGORY_FALLBACK

    noisy = replace(
        base, features={**base.features, "cascade": {"category": "Factura!!"}}
    )
    assert cascade_category_slug(noisy) == "factura"


def test_sharp_preset_loads() -> None:
    from filewizard.pipeline import load_ruleset

    ruleset = load_ruleset(Path("rules_sharp.yaml"))
    ids = [r.id for r in ruleset.rules]
    assert "social-whatsapp-filename" in ids
    assert "images-fallback" in ids


def test_sharp_whatsapp_filename_beats_camera(tmp_path: Path) -> None:
    """IMG-…-WA… con EXIF de cámara debe ir a Social, no a Camera."""
    from filewizard.executor import Executor
    from filewizard.journal import Journal
    from filewizard.pipeline import load_ruleset, plan_operations

    ruleset = load_ruleset(Path("rules_sharp.yaml"))
    src = tmp_path / "src"
    src.mkdir()
    target = src / "IMG-20240101-WA0001.jpg"
    target.write_bytes(b"\xff\xd8fake")
    with Journal(Path(":memory:")) as journal:
        ops, scanned = plan_operations(
            source=src,
            rules=ruleset,
            executor=Executor(journal=journal, dry_run=True),
            extractors=(),
        )
    assert scanned == 1
    assert len(ops) == 1
    assert ops[0].rule_id == "social-whatsapp-filename"
    assert "Social" in str(ops[0].destination)


def test_ocr_total_alone_no_longer_matches_invoice() -> None:
    from filewizard.pipeline import load_ruleset

    ruleset = load_ruleset(Path("rules.example.yaml"))
    ocr_rule = next(r for r in ruleset.rules if r.id == "invoices-by-ocr")
    assert ocr_rule.when.ocr_contains_any is not None
    assert "total" not in [t.casefold() for t in ocr_rule.when.ocr_contains_any]


def _wa_source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "IMG-20240101-WA0001.jpg").write_bytes(b"\xff\xd8fake")
    return src


def test_cli_preset_wa_goes_social(tmp_path: Path) -> None:
    """CLI run --preset images-cascade aplica la regla WA explícita."""
    from click.testing import CliRunner

    from filewizard.cli import cli

    src = _wa_source(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--source",
            str(src),
            "--preset",
            "images-cascade",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "social-whatsapp-filename" in result.output
    assert "Social" in result.output


def test_cli_presets_import_refreshes_stale_builtin(tmp_path: Path) -> None:
    """Un builtin obsoleto se actualiza con presets import --overwrite."""
    from click.testing import CliRunner

    from filewizard.cli import cli

    state = tmp_path / "state"
    presets = state / "presets"
    presets.mkdir(parents=True)
    stale = presets / "images-cascade.yaml"
    stale.write_text(
        "version: 1\nrules:\n"
        "  - id: old\n    name: Old\n"
        "    when: {always: true}\n"
        "    then: {move_to: '~/X'}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "presets",
            "import",
            "rules_sharp.yaml",
            "--name",
            "images-cascade",
            "--overwrite",
            "--state-dir",
            str(state),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "social-whatsapp-filename" in stale.read_text(encoding="utf-8")


def test_mcp_plan_preset_wa_goes_social(tmp_path: Path) -> None:
    """MCP plan --preset images-cascade (auto-seed) aplica la regla WA."""
    from filewizard.mcp.tools import filewizard_plan

    src = _wa_source(tmp_path)
    payload = filewizard_plan(src, tmp_path / "state", preset="images-cascade")
    assert payload["ok"] is True, payload.get("error")
    assert len(payload["operations"]) == 1
    assert payload["operations"][0]["rule_id"] == "social-whatsapp-filename"
    assert "Social" in (payload["operations"][0]["destination"] or "")


def test_mcp_apply_labels_category_template(tmp_path: Path) -> None:
    """{cascade_category} se interpola vía MCP apply_agent_labels."""
    from filewizard.mcp.tools import filewizard_apply_agent_labels

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"\xff\xd8fake")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: cat\n    name: Cat\n"
        "    when: {cascade_category_any: [factura]}\n"
        "    then: {move_to: '~/Pictures/{cascade_category}'}\n",
        encoding="utf-8",
    )
    payload = filewizard_apply_agent_labels(
        {str((src / "a.jpg").resolve()): {"cascade": {"category": "factura"}}},
        source=src,
        rules=rules,
    )
    assert payload["ok"] is True, payload.get("error")
    assert payload["plan"] is not None
    assert len(payload["plan"]["operations"]) == 1
    assert payload["plan"]["operations"][0]["destination"].endswith(
        __import__("os").path.join("Pictures", "factura", "a.jpg")
    )


def test_cascade_ml_fallback_uses_category_template() -> None:
    from filewizard.pipeline import load_ruleset

    ruleset = load_ruleset(Path("rules_cascade_ml.example.yaml"))
    fallback = next(r for r in ruleset.rules if r.id == "images-fallback")
    assert "{cascade_category}" in (fallback.then.move_to or "")


def test_template_cascade_category_interpolates(tmp_path: Path) -> None:
    target = tmp_path / "a.jpg"
    target.write_text("x", encoding="utf-8")
    facts = replace(
        collect_facts(target),
        features={
            **collect_facts(target).features,
            "cascade": {"category": "recibo", "status": "confirmed"},
        },
    )
    rendered = render_path_template("~/Pictures/{cascade_category}/{year}", facts)
    assert f"Pictures{__import__('os').sep}recibo" in str(rendered)

    plain = collect_facts(target)
    fallback = render_path_template("~/Pictures/{cascade_category}", plain)
    assert fallback.name == CASCADE_CATEGORY_FALLBACK
