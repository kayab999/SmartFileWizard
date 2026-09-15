"""WP-0.11.1: downloads-docs preset does not swallow images."""

from pathlib import Path

from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.pipeline import plan_operations
from filewizard.presets import ensure_builtin_presets, load_preset


def test_downloads_docs_builtin_and_pdf_not_jpg(tmp_path: Path) -> None:
    created = ensure_builtin_presets(tmp_path)
    names = {p.name for p in created}
    assert "downloads-docs.yaml" in names or (
        tmp_path / "presets" / "downloads-docs.yaml"
    ).is_file()

    ruleset = load_preset("downloads-docs", tmp_path)
    ids = {r.id for r in ruleset.rules}
    assert "pdfs" in ids
    assert "office" in ids

    src = tmp_path / "in"
    src.mkdir()
    (src / "report.pdf").write_bytes(b"%PDF-1.4")
    (src / "photo.jpg").write_bytes(b"\xff\xd8\xff")

    with Journal(tmp_path / "j.db") as journal:
        executor = Executor(journal=journal, dry_run=True)
        ops, scanned = plan_operations(
            source=src,
            rules=ruleset,
            executor=executor,
            extractors=(),
        )
    assert scanned == 2
    pdf_ops = [o for o in ops if o.source.name == "report.pdf"]
    jpg_ops = [o for o in ops if o.source.name == "photo.jpg"]
    assert len(pdf_ops) == 1
    assert pdf_ops[0].destination is not None
    assert "PDF" in str(pdf_ops[0].destination)
    assert jpg_ops == []
