from filewizard.ui.options import build_rule, parse_csv


def test_parse_csv() -> None:
    assert parse_csv("") is None
    assert parse_csv("  ") is None
    assert parse_csv("jpg, png, pdf") == ["jpg", "png", "pdf"]


def test_build_rule_screenshots() -> None:
    rule = build_rule(
        {
            "image_only": True,
            "filename_regex": "(?i)(screenshot|captura)",
            "move_to": "~/Pictures/Screenshots/{year}/{month}",
            "rename": "{date}_{original_name}",
            "create_target_dir": True,
            "on_collision": "append",
            "rule_name": "Separar capturas",
        }
    )

    assert rule.name == "Separar capturas"
    assert rule.when.mime_prefixes == ["image/"]
    assert rule.when.filename_regex == "(?i)(screenshot|captura)"
    assert rule.then.move_to is not None
    assert rule.then.rename is not None


def test_build_rule_sharpened_fields() -> None:
    rule = build_rule(
        {
            "filename_pattern_any": "whatsapp, screenshot",
            "not_filename_pattern_any": "invoice",
            "has_camera_metadata": True,
            "cascade_category_any": "factura, recibo",
            "move_to": "~/Pictures/{cascade_category}/{year}",
        }
    )
    assert rule.when.filename_pattern_any == ["whatsapp", "screenshot"]
    assert rule.when.not_filename_pattern_any == ["invoice"]
    assert rule.when.has_camera_metadata is True
    assert rule.when.cascade_category_any == ["factura", "recibo"]

    rule_none = build_rule({"extensions": "jpg", "move_to": "~/X"})
    assert rule_none.when.filename_pattern_any is None
    assert rule_none.when.has_camera_metadata is None
    assert rule_none.when.cascade_category_any is None


def test_wizard_rule_matches_yaml_equivalent(tmp_path) -> None:
    from dataclasses import replace

    from filewizard.engine import Engine
    from filewizard.facts import collect_facts

    target = tmp_path / "IMG-2024-WA001.jpg"
    target.write_text("x", encoding="utf-8")
    facts = replace(
        collect_facts(target),
        features={**collect_facts(target).features, "filename_patterns": ["whatsapp"]},
    )
    rule = build_rule(
        {
            "filename_pattern_any": "whatsapp",
            "not_filename_pattern_any": "invoice",
            "move_to": "~/Pictures/Social",
        }
    )
    assert len(list(Engine([rule]).evaluate(facts))) == 1


def test_build_rule_always() -> None:
    rule = build_rule(
        {
            "always": True,
            "rename": "{date}_{original_name}",
        }
    )
    assert rule.when.always is True
    assert rule.then.rename == "{date}_{original_name}"
