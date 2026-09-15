"""WP-0.11.2: resolved review labels inject into the next plan."""

from pathlib import Path

from filewizard.executor import Executor
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.pipeline import default_extractors, plan_operations
from filewizard.presets import ensure_builtin_presets, load_preset
from filewizard.review_queue import ReviewItem, ReviewQueue


def test_resolve_writes_labels_and_next_plan_uses_them(tmp_path: Path) -> None:
    img = tmp_path / "scan.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    queue = ReviewQueue(state_dir=tmp_path)
    item = ReviewItem.from_cascade(
        img,
        {
            "category": "unknown",
            "status": "unknown",
            "confidence": 0.1,
            "stage_used": 3,
        },
    )
    queue.add(item)
    assert queue.resolve(item.id, "factura") is True

    labels = tmp_path / "review_labels.json"
    assert labels.is_file()

    extractors = default_extractors(state_dir=tmp_path)
    facts = collect_facts(img, extractors=extractors)
    assert facts.features.get("cascade", {}).get("category") == "factura"
    assert facts.features["cascade"]["status"] == "confirmed"

    ensure_builtin_presets(tmp_path)
    ruleset = load_preset("images-cascade-ml", tmp_path)
    src = tmp_path / "in"
    src.mkdir()
    dest = src / "scan.jpg"
    dest.write_bytes(b"\xff\xd8\xff")
    # Labels key is the original path; copy mapping for dest.
    queue2 = ReviewQueue(state_dir=tmp_path)
    item2 = ReviewItem.from_cascade(
        dest,
        {"category": "unknown", "status": "unknown", "confidence": 0.1},
    )
    queue2.add(item2)
    queue2.resolve(item2.id, "factura")

    with Journal(tmp_path / "j.db") as journal:
        executor = Executor(journal=journal, dry_run=True)
        ops, _ = plan_operations(
            source=src,
            rules=ruleset,
            executor=executor,
            extractors=default_extractors(state_dir=tmp_path),
        )
    invoice_ops = [o for o in ops if o.source.name == "scan.jpg"]
    assert invoice_ops
    assert invoice_ops[0].destination is not None
    assert "Invoices" in str(invoice_ops[0].destination)
