from pathlib import Path

from filewizard.review_queue import ReviewItem, ReviewQueue


def test_review_queue_persist_and_resolve(tmp_path: Path) -> None:
    path = tmp_path / "review_queue.json"
    q = ReviewQueue(path=path)
    assert q.pending() == []

    item = ReviewItem.from_cascade(
        Path("/tmp/photo.jpg"),
        {
            "category": "unknown",
            "confidence": 0.2,
            "status": "unknown",
            "stage_used": 3,
            "reasoning": "no match",
        },
    )
    q.add(item)
    assert len(q.pending()) == 1

    # Dedupe same path
    item2 = ReviewItem.from_cascade(
        Path("/tmp/photo.jpg"),
        {
            "category": "foto_persona",
            "confidence": 0.4,
            "status": "probable",
            "stage_used": 1,
        },
    )
    q.add(item2)
    assert len(q.pending()) == 1
    assert q.pending()[0].category_hint == "foto_persona"

    # Reload from disk
    q2 = ReviewQueue(path=path)
    assert len(q2.pending()) == 1
    assert q2.resolve(q2.pending()[0].id, "foto_persona") is True
    assert q2.pending() == []
    assert q2.clear_resolved() == 1


def test_add_from_features_filters(tmp_path: Path) -> None:
    q = ReviewQueue(path=tmp_path / "q.json")
    # confirmed high conf → skip
    assert (
        q.add_from_features(
            Path("/a.jpg"),
            {
                "cascade": {
                    "category": "factura",
                    "status": "confirmed",
                    "confidence": 0.9,
                }
            },
        )
        is None
    )
    # unknown → enqueue
    item = q.add_from_features(
        Path("/b.jpg"),
        {
            "cascade": {
                "category": "unknown",
                "status": "unknown",
                "confidence": 0.1,
            },
            "ocr": {"text": "hola"},
        },
    )
    assert item is not None
    assert item.ocr_preview == "hola"
    assert len(q.pending()) == 1
    # I5: unresolved unknown is skipped (injecting it matches nothing).
    assert q.export_agent_labels() == {}
    # After human resolve: exported confirmed with confidence 1.0 + vision.
    assert q.resolve(item.id, "factura") is True
    labels = q.export_agent_labels()
    assert labels["/b.jpg"]["cascade"]["category"] == "factura"
    assert labels["/b.jpg"]["cascade"]["status"] == "confirmed"
    assert labels["/b.jpg"]["cascade"]["confidence"] == 1.0
    assert labels["/b.jpg"]["vision"]["invoice"] == 1.0


def test_review_badge_label_corrupt_and_pending(tmp_path: Path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue, review_badge_label

    q = ReviewQueue(path=tmp_path / "empty.json")
    assert review_badge_label(q) == "Cola de revisión…"

    q.add(
        ReviewItem.from_cascade(
            Path("/tmp/x.jpg"),
            {"category": "unknown", "status": "unknown", "confidence": 0.1},
        )
    )
    assert "1" in review_badge_label(q)

    bad = tmp_path / "review_queue.json"
    bad.write_text("{not-json", encoding="utf-8")
    q2 = ReviewQueue(path=bad)
    assert review_badge_label(q2) == "Cola de revisión (corrupta)…"


def test_review_queue_save_is_atomic(tmp_path: Path) -> None:
    from filewizard.review_queue import ReviewItem, ReviewQueue

    path = tmp_path / "review_queue.json"
    q = ReviewQueue(path=path)
    q.add(
        ReviewItem.from_cascade(
            Path("/tmp/y.jpg"),
            {"category": "unknown", "status": "unknown", "confidence": 0.2},
        )
    )
    assert path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()
    raw = path.read_text(encoding="utf-8")
    assert '"items"' in raw


def test_corrupt_queue_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "review_queue.json"
    path.write_text("{not-json", encoding="utf-8")
    q = ReviewQueue(path=path)
    assert q.pending() == []
    assert q.load_error
    bak = path.with_name(path.name + ".bak")
    assert bak.is_file()
    assert not path.is_file()
