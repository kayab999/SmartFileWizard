"""A1: batched stage-1 inference — same scores as single-image path."""

from __future__ import annotations

from pathlib import Path

import pytest

# Fixtures open/save real PNGs; skip cleanly where Pillow is absent.
pytest.importorskip("PIL")

from filewizard.perception.zeroshot import (
    LABEL_PROMPTS,
    Stage1BatchQueue,
)


class _FakeTensor:
    """Carries shape data [n_images, n_labels]; math is identity."""

    def __init__(
        self, n_images: int, n_labels: int, winners: list[int] | None = None
    ) -> None:
        self.n_images = n_images
        self.n_labels = n_labels
        self.winners = winners or []

    def norm(self, *, dim, keepdim):  # noqa: ARG002
        return self

    def to(self, device):  # noqa: ARG002
        return self

    def __matmul__(self, other):  # noqa: ARG002
        return self

    def __mul__(self, factor):  # noqa: ARG002
        return self

    def __truediv__(self, other):  # noqa: ARG002
        return self

    @property
    def T(self):  # noqa: N802
        return self

    def softmax(self, *, dim):  # noqa: ARG002
        rows = []
        for r in range(self.n_images):
            scores = [0.01] * self.n_labels
            # Winner depends on the image identity (pixel colour), not the
            # batch row — mirroring a real model, where batching must not
            # change per-image scores.
            winner = (
                self.winners[r] if r < len(self.winners) else r
            ) % self.n_labels
            scores[winner] = 0.9
            rows.append(scores)
        return _FakeProbs(rows)


class _FakeProbs:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows

    def __getitem__(self, key):
        if isinstance(key, tuple):
            r, i = key
            return _FakeItem(self.rows[r][i])
        return _FakeRowView(self.rows[key])


class _FakeRowView:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def __getitem__(self, i: int) -> "_FakeItem":
        return _FakeItem(self.scores[i])


class _FakeItem:
    def __init__(self, value: float) -> None:
        self.value = value

    def item(self):
        return self.value


class _FakeInputs(dict):
    def __init__(self, n_images: int, n_labels: int) -> None:
        super().__init__()
        self["pixel_values"] = _FakeTensor(n_images, n_labels)
        self["input_ids"] = _FakeTensor(n_images, n_labels)
        self["attention_mask"] = _FakeTensor(n_images, n_labels)

    def to(self, device):  # noqa: ARG002
        return self


class _FakeProcessor:
    """Counts images per processor call (forward-pass batching evidence)."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, *, text, images, return_tensors, padding):  # noqa: ARG002
        image_list = images if isinstance(images, list) else [images]
        n_labels = len(text)
        self.calls.append(len(image_list))
        inputs = _FakeInputs(len(image_list), n_labels)
        # Winner per image derived from its pixel colour: stable regardless
        # of which batch the image lands in.
        inputs["pixel_values"] = _FakeTensor(
            len(image_list),
            n_labels,
            winners=[sum(img.getpixel((0, 0))) % n_labels for img in image_list],
        )
        return inputs


class _FakeModel:
    def get_image_features(self, **kw):
        return kw["pixel_values"]

    def get_text_features(self, **kw):  # noqa: ARG002
        return _FakeTensor(1, 1)

    def eval(self):
        return self

    def to(self, device):  # noqa: ARG002
        return self


class _FakeNoGrad:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def fake_classifier(monkeypatch, tmp_path: Path):
    from filewizard.perception.zeroshot import ZeroShotClassifier

    clf = ZeroShotClassifier(batch_size=4)
    processor = _FakeProcessor()

    monkeypatch.setattr(clf, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(clf, "_model", _FakeModel(), raising=False)
    monkeypatch.setattr(clf, "_processor", processor, raising=False)
    # predict / predict_batch use self._torch.no_grad(); provide a fake.
    fake_torch = type("T", (), {"no_grad": staticmethod(lambda: _FakeNoGrad())})
    monkeypatch.setattr(clf, "_torch", fake_torch, raising=False)

    from PIL import Image

    paths = []
    for i in range(6):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (8, 8), color=(i * 40, 0, 0)).save(p)
        paths.append(p)
    return clf, processor, paths


def test_predict_batch_fewer_forward_calls(fake_classifier) -> None:
    clf, processor, paths = fake_classifier
    labels = list(LABEL_PROMPTS)[:3]
    results = clf.predict_batch(paths, labels)
    # 6 images, batch_size 4 → 2 processor/forward calls (4 + 2).
    assert processor.calls == [4, 2]
    assert len(results) == len(paths)
    for p in paths:
        scored = results[p]
        assert {s["label"] for s in scored} == set(labels)
        assert all(0.0 <= s["score"] <= 1.0 for s in scored)


def test_predict_batch_matches_single_path_scores(fake_classifier) -> None:
    clf, _processor, paths = fake_classifier
    labels = list(LABEL_PROMPTS)[:3]
    batch = clf.predict_batch(paths, labels)
    single = {p: clf.predict(p, labels) for p in paths}
    assert batch == single


def test_stage1_batch_queue_flush_on_full(fake_classifier) -> None:
    clf, _processor, paths = fake_classifier
    labels = list(LABEL_PROMPTS)[:3]
    queue = Stage1BatchQueue(clf, labels, batch_size=3)
    # First two requests buffer (no result yet).
    assert queue.request(paths[0]) is None
    assert queue.request(paths[1]) is None
    # Third request triggers a flush of the full batch.
    r3 = queue.request(paths[2])
    assert r3 is not None
    assert queue.result(paths[0]) is not None
    assert queue.result(paths[1]) is not None


def test_stage1_batch_queue_manual_flush(fake_classifier) -> None:
    clf, _processor, paths = fake_classifier
    labels = list(LABEL_PROMPTS)[:3]
    queue = Stage1BatchQueue(clf, labels, batch_size=64)
    queue.request(paths[0])
    assert queue.result(paths[0]) is None
    queue.flush()
    assert queue.result(paths[0]) is not None
    # Re-request after evaluation returns the cached result immediately.
    assert queue.request(paths[0]) is not None


def test_make_zeroshot_batch_fn_none_without_deps(monkeypatch) -> None:
    from filewizard.perception import zeroshot as zs

    monkeypatch.setattr(zs, "zeroshot_available", lambda: False)
    assert zs.make_zeroshot_batch_fn() is None
    assert zs.make_zeroshot_fn() is None


def test_stage1_batch_size_config_validation() -> None:
    from pydantic import ValidationError

    from filewizard.perception.config import CascadeSettings

    cfg = CascadeSettings()
    assert cfg.stage1_batch_size >= 1
    with pytest.raises(ValidationError):
        CascadeSettings(stage1_batch_size=0)
    with pytest.raises(ValidationError):
        CascadeSettings(stage1_batch_size=100)
