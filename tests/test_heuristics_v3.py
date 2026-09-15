from pathlib import Path

from filewizard.engine import Engine
from filewizard.facts import FileFacts, collect_facts
from filewizard.models import Action, Condition, Rule
from filewizard.plugins.heuristics import ImageHeuristics
from filewizard.template import render_path_template
from filewizard.scanner import iter_files


def test_filename_pattern_screenshot(tmp_path: Path) -> None:
    f = tmp_path / "Screenshot_2025-01-01.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    facts = collect_facts(f, extractors=[ImageHeuristics()])
    assert "screenshot" in facts.features.get("filename_patterns", [])
    assert facts.features.get("date_source") in {"filename", "mtime", "exif"}
    if facts.features.get("date_source") == "filename":
        assert "2025-01-01" in facts.features["date_taken"]


def test_template_uses_date_taken(tmp_path: Path) -> None:
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    facts = collect_facts(f)
    # inject true capture date different from mtime bucket
    facts = FileFacts(
        path=facts.path,
        size=facts.size,
        mime=facts.mime,
        extension=facts.extension,
        filename=facts.filename,
        stem=facts.stem,
        mtime=facts.mtime,
        is_image=True,
        features={"date_taken": "2022-03-15T12:00:00", "date_source": "filename"},
    )
    rendered = render_path_template("/tmp/out/{year}/{month}", facts)
    assert rendered == Path("/tmp/out/2022/03")


def test_negation_not_filename(tmp_path: Path) -> None:
    shot = tmp_path / "Screenshot_1.png"
    shot.write_bytes(b"x")
    cam = tmp_path / "photo.png"
    cam.write_bytes(b"x")

    rule = Rule(
        id="cam",
        name="Cam",
        priority=10,
        when=Condition(
            mime_prefixes=["image/"],
            not_filename_regex="(?i)screenshot",
        ),
        then=Action(move_to=str(tmp_path / "out")),
    )
    engine = Engine([rule])

    facts_shot = collect_facts(shot)
    facts_cam = collect_facts(cam)
    assert list(engine.evaluate(facts_shot)) == []
    assert len(list(engine.evaluate(facts_cam))) == 1


def test_invalid_regex_fails_at_load() -> None:
    try:
        Condition(filename_regex="[unclosed")
        assert False, "expected validation error"
    except Exception:
        pass


def test_rules_sharp_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "rules_sharp.yaml"
    import yaml
    from filewizard.models import RuleSet

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rs = RuleSet.model_validate(data)
    assert len(rs.rules) >= 5


def test_chaos_scanner_skips_fifo_and_symlink(tmp_path: Path) -> None:
    (tmp_path / "ñoño.JPG").write_text("a", encoding="utf-8")
    (tmp_path / "日本語.png").write_bytes(b"x")
    (tmp_path / "Screenshot_2025-01-01.png").write_bytes(b"x")
    try:
        import os

        fifo = tmp_path / "pipe.fifo"
        os.mkfifo(fifo)
    except OSError:
        fifo = None

    link = tmp_path / "link.png"
    try:
        link.symlink_to("/etc/passwd")
    except OSError:
        link = None

    found = list(iter_files(tmp_path))
    names = {p.name for p in found}
    assert "ñoño.JPG" in names
    assert "日本語.png" in names
    assert "Screenshot_2025-01-01.png" in names
    if fifo is not None:
        assert fifo not in found
    if link is not None:
        assert link not in found


def test_pattern_rule_match(tmp_path: Path) -> None:
    f = tmp_path / "captura_x.png"
    f.write_bytes(b"x")
    facts = collect_facts(f, extractors=[ImageHeuristics()])
    rule = Rule(
        id="s",
        name="S",
        priority=1,
        when=Condition(
            mime_prefixes=["image/"],
            filename_pattern_any=["screenshot"],
        ),
        then=Action(move_to=str(tmp_path / "out")),
    )
    matches = list(Engine([rule]).evaluate(facts))
    assert len(matches) == 1
    assert any(c.key == "filename_pattern" for c in matches[0].conditions)
