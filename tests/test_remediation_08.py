from pathlib import Path

from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.perception.cascade import _category_from_invoice_hint
from filewizard.perception.snapshot import format_perception_evidence
from filewizard.pipeline import plan_operations
from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.mcp.tools import filewizard_plan


def test_invoice_hint_does_not_force_factura_from_status() -> None:
    assert _category_from_invoice_hint("recibo", "recibo total 10 01/01/2026") == "recibo"
    assert _category_from_invoice_hint("factura", "factura nif total") == "factura"
    assert (
        _category_from_invoice_hint("documento_escaneado", "total iva 01/01/2026")
        == "documento_escaneado"
    )
    # status string must not flip hint (the old `or status` bug)
    assert _category_from_invoice_hint("recibo", "probable confirmed") == "recibo"


def test_only_paths_matches_unresolved(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x", encoding="utf-8")
    rules = RuleSet(
        rules=[
            Rule(
                id="t",
                name="t",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ]
    )
    with Journal(tmp_path / "j.db") as journal:
        ops, n = plan_operations(
            source=src,
            rules=rules,
            executor=Executor(journal=journal, dry_run=True),
            extractors=[],
            only_paths={Path(str(f))},  # not resolved
        )
    assert n == 1
    assert len(ops) == 1


def test_mcp_plan_matches_screenshot_heuristic_without_http(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "Screenshot_2026-01-01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: cap\n    name: cap\n"
        "    when:\n      cascade_category_any: [captura_pantalla]\n"
        f"    then:\n      move_to: {tmp_path / 'shots'}\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    (state / "perception.yaml").write_text(
        "heuristics: true\n"
        "cascade:\n  enabled: true\n  enable_stage2: false\n  enable_stage3: false\n"
        "ocr:\n  provider: none\n"
        "vision:\n  provider: none\n",
        encoding="utf-8",
    )
    payload = filewizard_plan(src, state, rules=rules)
    assert payload["ok"] is True, payload
    assert payload["scanned"] == 1
    assert len(payload["operations"]) == 1
    assert payload["operations"][0]["rule_id"] == "cap"
    assert (src / "Screenshot_2026-01-01.png").is_file()


def test_format_perception_evidence() -> None:
    line = format_perception_evidence(
        {
            "cascade": {
                "category": "factura",
                "status": "confirmed",
                "stage_used": 2,
                "confidence": 0.88,
            }
        }
    )
    assert "factura" in line
    assert "etapa 2" in line
    assert format_perception_evidence(None) == ""
