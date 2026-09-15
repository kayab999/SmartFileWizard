from pathlib import Path

from filewizard.perception.cascade import (
    CascadeExtractor,
    CascadeResult,
    CascadeThresholds,
    map_heuristic_category,
    validate_invoice_ocr,
)
from filewizard.perception.config import config_from_profile
from filewizard.perception.factory import build_extractors
from filewizard.plugins.heuristics import ImageHeuristics


def test_validate_invoice_ocr() -> None:
    text = "Factura NIF 12345678A TOTAL 100 EUR IVA 21% 01/08/2026"
    assert validate_invoice_ocr(text) == "confirmed"
    assert validate_invoice_ocr("hola mundo") == "rejected"
    assert validate_invoice_ocr("total 10") in {"probable", "rejected"}


def test_stage0_screenshot_shortcut(tmp_path: Path) -> None:
    f = tmp_path / "Screenshot_2026-01-01.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    h = ImageHeuristics().extract(f)
    r = map_heuristic_category(h)
    assert r is not None
    assert r.category == "captura_pantalla"
    # C1 parity: filename alone must not confirm (spoof-safe).
    assert r.status == "probable"
    assert r.stage_used == 0


def test_cascade_extractor_stage0(tmp_path: Path) -> None:
    f = tmp_path / "captura_pantalla_x.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    cfg = config_from_profile("lite")
    # lite has cascade disabled by default — force cascade extractor directly
    cfg = cfg.model_copy(
        update={
            "cascade": {
                "enabled": True,
                "enable_stage2": False,
                "enable_stage3": False,
            },
            "ocr": {"provider": "none"},
            "vision": {"provider": "none"},
        }
    )
    ext = CascadeExtractor(cfg, enable_stage2=False, enable_stage3=False)
    feats = ext.extract(f)
    assert feats.get("cascade", {}).get("category") == "captura_pantalla"
    assert feats.get("vision", {}).get("screenshot", 0) >= 0.9


def test_recommended_uses_cascade() -> None:
    cfg = config_from_profile("recommended")
    assert cfg.cascade.enabled is True
    xs = build_extractors(cfg)
    names = [getattr(x, "name", "") for x in xs]
    assert names == ["cascade"]


def test_cascade_result_to_features() -> None:
    r = CascadeResult(
        stage_used=1,
        category="captura_pantalla",
        confidence=0.9,
        status="confirmed",
        vision_scores={"screenshot": 0.9},
    )
    f = r.to_features()
    assert f["cascade"]["stage_used"] == 1
    assert f["vision"]["screenshot"] >= 0.9


def test_stage1_zeroshot_confirms(tmp_path: Path) -> None:
    """Mock zeroshot_fn high score → confirmed at stage 1 without OCR/VLM."""
    f = tmp_path / "random_photo.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    def fake_zeroshot(path: Path, labels: list[str]) -> list[dict]:
        return [
            {"label": "foto_paisaje", "score": 0.92},
            {"label": "foto_persona", "score": 0.05},
        ]

    cfg = config_from_profile("lite").model_copy(
        update={
            "cascade": {
                "enabled": True,
                "high_confidence": 0.75,
                "enable_stage2": False,
                "enable_stage3": False,
            },
            "ocr": {"provider": "none"},
            "vision": {"provider": "none"},
        }
    )
    ext = CascadeExtractor(
        cfg,
        thresholds=CascadeThresholds(high_confidence=0.75),
        enable_stage2=False,
        enable_stage3=False,
        zeroshot_fn=fake_zeroshot,
    )
    feats = ext.extract(f)
    cas = feats.get("cascade") or {}
    # Filename may trigger stage0 screenshot? "random_photo" should not.
    assert cas.get("stage_used") == 1
    assert cas.get("category") == "foto_paisaje"
    assert cas.get("status") == "confirmed"
    assert cas.get("confidence", 0) >= 0.9


def test_on_facts_hook_in_pipeline(tmp_path: Path) -> None:
    from filewizard.executor import Executor
    from filewizard.journal import Journal
    from filewizard.models import Action, Condition, Rule, RuleSet
    from filewizard.pipeline import plan_operations

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")

    rules = RuleSet(
        rules=[
            Rule(
                id="t",
                name="txt",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ]
    )
    seen: list[str] = []

    def on_facts(facts) -> None:
        seen.append(facts.filename)

    with Journal(tmp_path / "j.db") as journal:
        ops, scanned = plan_operations(
            source=src,
            rules=rules,
            executor=Executor(journal=journal, dry_run=True),
            extractors=[],
            on_facts=on_facts,
        )
    assert scanned == 1
    assert seen == ["a.txt"]
    assert len(ops) == 1
