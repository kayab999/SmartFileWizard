from pathlib import Path

from filewizard.executor import Executor
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.perception.cache import (
    CachingExtractor,
    PerceptionCache,
    config_fingerprint,
    file_content_hash,
)
from filewizard.perception.config import PerceptionConfig, config_from_profile
from filewizard.perception.snapshot import perception_snapshot
from filewizard.pipeline import plan_operations


class _CountingExtractor:
    name = "counter"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, path: Path) -> dict:
        self.calls += 1
        return {
            "cascade": {
                "stage_used": 0,
                "category": "captura_pantalla",
                "confidence": 0.95,
                "status": "confirmed",
                "stages": {"0": {"source": "test"}},
            }
        }


def test_file_content_hash_stable(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello-cache")
    h1 = file_content_hash(f)
    assert h1 == file_content_hash(f)
    f.write_bytes(b"hello-cache!")
    assert file_content_hash(f) != h1


def test_perception_cache_hit(tmp_path: Path) -> None:
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
    inner = _CountingExtractor()
    cache = PerceptionCache(root=tmp_path / "cache", max_entries=10)
    wrapped = CachingExtractor(inner, cache, config_fp="abc")

    a = wrapped.extract(f)
    b = wrapped.extract(f)
    assert inner.calls == 1
    assert a["cascade"]["category"] == "captura_pantalla"
    assert b["cascade"].get("cache_hit") is True


def test_cache_invalidated_by_config_fp(tmp_path: Path) -> None:
    f = tmp_path / "img.png"
    f.write_bytes(b"data")
    inner = _CountingExtractor()
    cache = PerceptionCache(root=tmp_path / "cache2")
    CachingExtractor(inner, cache, config_fp="fp1").extract(f)
    CachingExtractor(inner, cache, config_fp="fp2").extract(f)
    assert inner.calls == 2


def test_compact_cache_features_keeps_ocr_text_capped() -> None:
    from filewizard.perception.snapshot import (
        MAX_CACHE_OCR_CHARS,
        compact_cache_features,
    )

    features = {
        "cascade": {
            "category": "factura",
            "stages": {"2": {"text": "x" * 8000, "provider": "ocr", "raw": "dump"}},
        },
        "ocr": {"text": "NIF " + "9" * 5000, "provider": "llama_http"},
        "vision": {"invoice": 0.9, "raw": "huge"},
    }
    compact = compact_cache_features(features)
    assert "text" not in compact["cascade"]["stages"]["2"]
    assert compact["cascade"]["stages"]["2"]["provider"] == "ocr"
    assert compact["ocr"]["text"].startswith("NIF ")
    assert len(compact["ocr"]["text"]) == MAX_CACHE_OCR_CHARS
    assert compact["ocr"]["text_truncated"] is True
    assert "raw" not in compact["vision"]
    assert compact["vision"]["invoice"] == 0.9


def test_cache_evicts_by_max_bytes(tmp_path: Path) -> None:
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)

    class Fat:
        name = "fat"
        n = 0

        def extract(self, path):
            self.n += 1
            return {"ocr": {"text": "A" * 200, "provider": "t"}}

    cache = PerceptionCache(
        root=tmp_path / "c", max_entries=50, max_bytes=400
    )
    wrapped = CachingExtractor(Fat(), cache, config_fp="fp")
    wrapped.extract(f)
    # Second file: new key, may evict the first under tiny max_bytes.
    f2 = tmp_path / "b.png"
    f2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 40)
    wrapped.extract(f2)
    assert cache._payload_bytes() <= 400 or cache._payload_bytes() < 2000


def test_perception_snapshot_compact() -> None:
    features = {
        "cascade": {
            "stage_used": 2,
            "category": "factura",
            "confidence": 0.88,
            "status": "confirmed",
            "reasoning": "ok",
            "stages": {
                "2": {
                    "provider": "llama_http",
                    "text": "x" * 5000,
                    "scores": {"a": 0.9, "b": 0.1, "c": 0.05, "d": 0.01},
                }
            },
        },
        "ocr": {"text": "Factura total 100", "provider": "cascade"},
        "vision": {"invoice": 0.88, "provider": "cascade", "raw": "huge"},
        "filename_patterns": ["invoice"],
    }
    snap = perception_snapshot(features)
    assert snap is not None
    assert snap["cascade"]["category"] == "factura"
    assert "text" not in (snap["cascade"]["stages"]["2"] or {})
    assert snap["ocr"]["text_preview"].startswith("Factura")
    assert snap["ocr"]["text_len"] == len("Factura total 100")
    assert "raw" not in snap["vision"]
    assert snap["vision"]["scores"]["invoice"] == 0.88


def test_journal_stores_perception(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst_dir = tmp_path / "out"
    src.write_text("hi", encoding="utf-8")
    dst_dir.mkdir()

    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=False)
    from filewizard.facts import FileFacts
    from filewizard.engine import Engine

    facts = collect_facts(src)
    # inject cascade features as if perception ran
    facts = FileFacts(
        path=facts.path,
        size=facts.size,
        mime=facts.mime,
        extension=facts.extension,
        filename=facts.filename,
        stem=facts.stem,
        mtime=facts.mtime,
        is_image=False,
        features={
            "cascade": {
                "stage_used": 0,
                "category": "unknown",
                "confidence": 0.0,
                "status": "unknown",
            }
        },
    )
    rule = Rule(
        id="t",
        name="txt",
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(dst_dir)),
    )
    match = next(Engine([rule]).evaluate(facts))
    op = executor.plan(facts=facts, rule=match.rule, explanations=match.explanations)
    assert op is not None
    op.perception = perception_snapshot(facts.features)
    results = executor.execute([op])
    assert results[0].status == "done"

    rows = journal.recent_operations(1)
    assert len(rows) == 1
    perc = Journal.parse_perception(rows[0])
    assert perc is not None
    assert perc["cascade"]["status"] == "unknown"
    journal.close()


def test_pipeline_attaches_perception(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.txt").write_text("x", encoding="utf-8")
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
        )
    assert n == 1
    # no perception features → snapshot None
    assert ops[0].perception is None


def test_config_fingerprint_changes() -> None:
    a = PerceptionConfig()
    b = a.model_copy(
        update={"ocr": a.ocr.model_copy(update={"model": "other"})}
    )
    assert config_fingerprint(a) != config_fingerprint(b)
    # recommended profile has cascade
    rec = config_from_profile("recommended")
    assert rec.cache.enabled is True
