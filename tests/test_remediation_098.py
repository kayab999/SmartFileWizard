"""Fase 1 (0.9.8): C1 invoice-spoof, C2 reverse map, C3 jail gaps, I1 QSS."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_c1_invoice_filename_no_longer_confirms(tmp_path: Path) -> None:
    """Renaming photo.jpg → factura_photo.jpg must not auto-confirm."""
    from filewizard.perception.cascade import map_heuristic_category
    from filewizard.plugins.heuristics import ImageHeuristics

    target = tmp_path / "factura_photo.jpg"
    target.write_bytes(b"\xff\xd8fake")
    h = ImageHeuristics().extract(target)
    assert "invoice" in (h.get("filename_patterns") or [])
    result = map_heuristic_category(h)
    assert result is not None
    assert result.category == "factura"
    assert result.status != "confirmed"


def test_c2_reverse_map_canonical() -> None:
    from filewizard.perception.cascade import VISION_KEY_TO_LABEL

    assert VISION_KEY_TO_LABEL["invoice"] == "factura"
    assert VISION_KEY_TO_LABEL["photo"] == "foto_persona"
    assert VISION_KEY_TO_LABEL["document"] == "documento_escaneado"
    assert VISION_KEY_TO_LABEL["screenshot"] == "captura_pantalla"
    # Every forward value resolves back to a category that maps to it.
    from filewizard.perception.cascade import LABEL_TO_VISION_KEY

    for vision_key, category in VISION_KEY_TO_LABEL.items():
        if vision_key == "unknown":
            continue
        assert LABEL_TO_VISION_KEY[category] == vision_key


def test_c3_collect_facts_honors_jail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from filewizard.mcp.tools import filewizard_collect_facts

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(allowed))

    blocked = filewizard_collect_facts(secret)
    assert blocked["ok"] is False
    assert "allowed_roots" in blocked["error"]

    inside = allowed / "ok.txt"
    inside.write_text("x", encoding="utf-8")
    payload = filewizard_collect_facts(inside)
    assert payload["ok"] is True


def test_c3_undo_batch_honors_jail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from filewizard.journal import Journal
    from filewizard.mcp.tools import filewizard_undo_batch

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(allowed))

    state = tmp_path / "state"
    state.mkdir()
    moved = tmp_path / "outside_moved.txt"
    moved.write_text("data", encoding="utf-8")
    with Journal(state / "journal.db") as journal:
        op_id = journal.start_operation(
            batch_id="b-out",
            rule_id="r",
            op="move",
            source=tmp_path / "orig.txt",
            destination=moved,
            byte_size=4,
        )
        journal.finish_operation(op_id, "done", destination=moved)

    # Even dry-run is refused: fail-closed, no path oracle.
    payload = filewizard_undo_batch("b-out", state)
    assert payload["ok"] is False
    assert "allowed_roots" in payload["error"]
    assert moved.is_file()


def test_i4_single_total_rejected() -> None:
    from filewizard.perception.cascade import invoice_confidence, validate_invoice_ocr

    assert validate_invoice_ocr("total 10") == "rejected"
    assert validate_invoice_ocr("Factura NIF x TOTAL 1, 01/02/2026") == "confirmed"
    # Proportional, bounded; probable stays below high_confidence (0.75).
    assert invoice_confidence("confirmed", 5) == 0.95
    assert invoice_confidence("probable", 2) == 0.65
    assert invoice_confidence("probable", 20) == 0.70


def test_i5_pipeline_dict_branch_normalizes(tmp_path: Path) -> None:
    from filewizard.pipeline import default_extractors

    xs = default_extractors(agent_features={"sub/in.jpg": {"vision": {"a": 1.0}}})
    names = [getattr(x, "name", "") for x in xs]
    assert "agent_inject" in names
    injector = next(x for x in xs if getattr(x, "name", "") == "agent_inject")
    key = next(iter(injector.mapping))
    assert Path(key).is_absolute()


def test_i9_remote_endpoints_helper() -> None:
    from filewizard.perception.config import PerceptionConfig
    from filewizard.perception.http_openai import remote_perception_endpoints

    cfg = PerceptionConfig()
    assert remote_perception_endpoints(cfg) == []
    cfg.ocr.provider = "llama_http"
    cfg.ocr.base_url = "http://example.com:8080/v1"
    eps = remote_perception_endpoints(cfg)
    assert len(eps) == 1 and "example.com" in eps[0]


def test_i9_cli_warns_remote(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: t\n    name: T\n"
        "    when: {extensions: [txt]}\n"
        f"    then: {{move_to: '{tmp_path / 'out'}'}}\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    (state / "perception.yaml").write_text(
        "ocr:\n  provider: llama_http\n  base_url: http://example.com:8080/v1\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli, ["run", "--source", str(src), "--rules", str(rules),
              "--state-dir", str(state)]
    )
    assert result.exit_code == 0, result.output
    assert "outside this machine" in result.output


def test_i9_mcp_warnings_key(tmp_path: Path) -> None:
    from filewizard.mcp.tools import filewizard_plan

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: t\n    name: T\n"
        "    when: {extensions: [txt]}\n"
        f"    then: {{move_to: '{tmp_path / 'out'}'}}\n",
        encoding="utf-8",
    )
    payload = filewizard_plan(src, tmp_path / "state", rules=rules)
    assert payload["ok"] is True
    assert payload["warnings"] == []


def test_i6_memo_skips_rehash(tmp_path: Path) -> None:
    from filewizard.perception import cache as cache_mod

    target = tmp_path / "a.bin"
    target.write_bytes(b"y" * 4096)

    class Inner:
        name = "inner"

        def extract(self, path):
            return {"k": "v"}

    cache = cache_mod.PerceptionCache(state_dir=tmp_path)
    ext = cache_mod.CachingExtractor(Inner(), cache, config_fp="fp")
    calls = {"n": 0}
    real_hash = cache_mod.file_content_hash

    def counting(path):
        calls["n"] += 1
        return real_hash(path)

    import filewizard.perception.cache as mod

    original = mod.file_content_hash
    mod.file_content_hash = counting
    try:
        assert ext.extract(target) == {"k": "v"}
        second = ext.extract(target)
        assert second["k"] == "v" and second.get("_cache_hit") is True
    finally:
        mod.file_content_hash = original
    assert calls["n"] == 1


def test_i6_review_batch_save(tmp_path: Path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue

    q = ReviewQueue(path=tmp_path / "q.json")
    for i in range(3):
        q.add(
            ReviewItem.from_cascade(
                tmp_path / f"{i}.jpg",
                {"category": "unknown", "status": "unknown", "confidence": 0.1},
            ),
            save=False,
        )
    assert not (tmp_path / "q.json").is_file()
    q.save()
    assert (tmp_path / "q.json").is_file()
    assert len(ReviewQueue(path=tmp_path / "q.json").items) == 3


def test_retention_journal_purge(tmp_path: Path) -> None:
    from filewizard.journal import Journal

    db = tmp_path / "j.db"
    with Journal(db) as journal:
        keep = journal.start_operation(
            "b", "r", op="move", source=tmp_path / "a",
            destination=tmp_path / "b",
        )
        journal.finish_operation(keep, "done", destination=tmp_path / "b")
        drop = journal.start_operation(
            "b", "r", op="move", source=tmp_path / "c",
            destination=tmp_path / "d",
        )
        journal.finish_operation(drop, "failed", error="x")
        assert journal.count_purgeable(older_than_days=0) == 1
        assert journal.purge(older_than_days=0) == 1
        assert journal.get_operation(keep) is not None
        assert journal.get_operation(drop) is None
        with pytest.raises(ValueError):
            journal.purge(older_than_days=-1)


def test_retention_review_delete_and_purge(tmp_path: Path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue

    q = ReviewQueue(path=tmp_path / "q.json")
    item = ReviewItem.from_cascade(
        tmp_path / "a.jpg",
        {"category": "unknown", "status": "unknown", "confidence": 0.1},
    )
    q.add(item)
    assert q.delete("missing") is False
    assert q.delete(item.id) is True
    assert q.pending() == []

    item2 = ReviewItem.from_cascade(
        tmp_path / "b.jpg",
        {"category": "factura", "status": "probable", "confidence": 0.6},
    )
    q.add(item2)
    assert q.resolve(item2.id, "factura") is True
    assert q.purge_resolved(older_than_days=36500) == 0
    # Backdate the resolution, then purge.
    q.items[0].resolved_at = "2000-01-01T00:00:00+00:00"
    assert q.purge_resolved(older_than_days=30) == 1
    with pytest.raises(ValueError):
        q.purge_resolved(older_than_days=-1)


def test_retention_cli_purge_dry_run(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli
    from filewizard.journal import Journal

    state = tmp_path / "state"
    state.mkdir()
    with Journal(state / "journal.db") as journal:
        op_id = journal.start_operation(
            "b", "r", op="move", source=state / "a",
            destination=state / "b",
        )
        journal.finish_operation(op_id, "failed", error="x")

    result = CliRunner().invoke(
        cli, ["purge", "--state-dir", str(state), "--older-than-days", "0"]
    )
    assert result.exit_code == 0, result.output
    assert "Purgeable rows: 1" in result.output
    assert "Dry purge only" in result.output
    with Journal(state / "journal.db") as journal:
        assert journal.get_operation(op_id) is not None


def test_version_single_source() -> None:
    import tomllib
    from pathlib import Path

    import filewizard

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"]
    assert "version" in data["project"].get("dynamic", [])
    assert (
        data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        == "filewizard.__version__"
    )
    assert filewizard.__version__


def test_i3_save_preset_atomic_no_tmp(tmp_path: Path) -> None:
    from filewizard.models import Action, Condition, Rule, RuleSet
    from filewizard.presets import load_preset, save_preset

    ruleset = RuleSet(
        rules=[
            Rule(
                id="a",
                name="A",
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ]
    )
    path = save_preset("atomic", ruleset, tmp_path)
    assert path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()
    assert len(load_preset("atomic", tmp_path).rules) == 1


def test_i1_limit_capped() -> None:
    from filewizard.mcp.tools import MCP_LIMIT_MAX, _coerce_limit

    assert _coerce_limit(10**9) == MCP_LIMIT_MAX
    assert _coerce_limit(50) == 50
    assert _coerce_limit(0) == 100
    assert _coerce_limit("bad") == 100


def test_c1_screenshot_filename_no_longer_confirms(tmp_path: Path) -> None:
    from filewizard.perception.cascade import map_heuristic_category
    from filewizard.plugins.heuristics import ImageHeuristics

    target = tmp_path / "screenshot_meme.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    h = ImageHeuristics().extract(target)
    assert "screenshot" in (h.get("filename_patterns") or [])
    result = map_heuristic_category(h)
    assert result is not None
    assert result.status != "confirmed"


def test_i1_load_qss_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from filewizard.ui import theme

    monkeypatch.setattr(theme, "_QSS", tmp_path / "missing.qss")
    assert theme.load_qss() == ""


def test_i12_server_wrappers_forward_agent_features() -> None:
    import inspect

    from filewizard.mcp import server

    src = inspect.getsource(server.build_server)
    assert "agent_features" in src
    # Both wrappers expose and forward it.
    assert src.count("agent_features=agent_features") >= 2


def test_i12_op_dict_carries_perception(tmp_path: Path) -> None:
    from filewizard.mcp.tools import filewizard_plan

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: t\n    name: T\n"
        "    when: {extensions: [txt]}\n"
        f"    then: {{move_to: '{tmp_path / 'out'}'}}\n",
        encoding="utf-8",
    )
    payload = filewizard_plan(src, tmp_path / "state", rules=rules)
    assert payload["ok"] is True
    op = payload["operations"][0]
    assert "perception" in op


def test_i12_plan_accepts_agent_features_dict(tmp_path: Path) -> None:
    from filewizard.mcp.tools import filewizard_plan

    src = tmp_path / "src"
    src.mkdir()
    target = src / "a.jpg"
    target.write_bytes(b"\xff\xd8fake")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: c\n    name: C\n"
        "    when: {cascade_category_any: [factura]}\n"
        f"    then: {{move_to: '{tmp_path / 'out'}'}}\n",
        encoding="utf-8",
    )
    payload = filewizard_plan(
        src,
        tmp_path / "state",
        rules=rules,
        agent_features={str(target.resolve()): {"cascade": {"category": "factura"}}},
    )
    assert payload["ok"] is True
    assert len(payload["operations"]) == 1
