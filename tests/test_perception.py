from pathlib import Path
from unittest.mock import patch

from filewizard.cancel import CancelToken, CancelledError
from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.perception.config import (
    PerceptionConfig,
    config_from_profile,
    load_perception_config,
    save_perception_config,
)
from filewizard.perception.factory import build_extractors
from filewizard.perception.http_openai import parse_vision_json
from filewizard.pipeline import plan_operations


def test_profiles_lite_and_recommended() -> None:
    lite = config_from_profile("lite")
    assert lite.ocr.provider == "tesseract"
    assert lite.vision.provider == "none"

    rec = config_from_profile("recommended")
    assert rec.ocr.provider == "llama_http"
    assert rec.vision.provider == "llama_http"
    assert "8080" in rec.ocr.base_url
    assert "8081" in rec.vision.base_url


def test_build_extractors_lite_force_ocr() -> None:
    cfg = config_from_profile("lite")
    assert cfg.ocr.provider == "tesseract"
    xs = build_extractors(cfg)
    names = [getattr(x, "name", "") for x in xs]
    assert "heuristics" in names
    assert "ocr" in names
    assert "vision" not in names

    # Default config (no profile file): OCR off until force_ocr
    default = PerceptionConfig()
    assert default.ocr.provider == "none"
    xs0 = build_extractors(default, force_ocr=False)
    assert "ocr" not in [getattr(x, "name", "") for x in xs0]
    xs1 = build_extractors(default, force_ocr=True)
    assert "ocr" in [getattr(x, "name", "") for x in xs1]


def test_build_extractors_recommended_uses_cascade() -> None:
    cfg = config_from_profile("recommended")
    assert cfg.cascade.enabled is True
    xs = build_extractors(cfg)
    names = [getattr(x, "name", "") for x in xs]
    assert names == ["cascade"]


def test_parse_vision_json() -> None:
    raw = '```json\n{"labels": {"screenshot": 0.9, "document": 0.1}, "text": "Hi"}\n```'
    parsed = parse_vision_json(raw, ["screenshot", "document", "photo"])
    assert parsed["labels"]["screenshot"] == 0.9
    assert parsed["labels"]["photo"] == 0.0
    assert parsed["text"] == "Hi"


def test_save_load_config(tmp_path: Path) -> None:
    cfg = config_from_profile("recommended")
    path = save_perception_config(cfg, tmp_path / "perception.yaml")
    loaded = load_perception_config(path)
    assert loaded.ocr.provider == "llama_http"
    assert loaded.vision.model == "Qwen3-VL-2B-Instruct"


def test_plan_cancel(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    for i in range(20):
        (src / f"f{i}.txt").write_text("x", encoding="utf-8")

    rules = RuleSet(
        version=1,
        rules=[
            Rule(
                id="all",
                name="All",
                when=Condition(always=True),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ],
    )
    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=True)
    token = CancelToken()
    token.cancel()

    try:
        plan_operations(
            source=src,
            rules=rules,
            executor=executor,
            extractors=[],
            cancel=token,
        )
        assert False, "expected CancelledError"
    except CancelledError:
        pass
    finally:
        journal.close()


def test_llama_http_ocr_mock(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    cfg = PerceptionConfig.model_validate(
        {
            "heuristics": False,
            "ocr": {
                "provider": "llama_http",
                "base_url": "http://127.0.0.1:9/v1",
                "model": "fake",
            },
            "vision": {"provider": "none"},
        }
    )
    xs = build_extractors(cfg)
    with patch(
        "filewizard.perception.extractors.chat_completion_with_image",
        return_value="Invoice total 42",
    ):
        from filewizard.facts import collect_facts

        facts = collect_facts(img, extractors=xs)
    assert facts.features["ocr"]["text"] == "Invoice total 42"
    assert facts.features["ocr"]["provider"] == "llama_http"
