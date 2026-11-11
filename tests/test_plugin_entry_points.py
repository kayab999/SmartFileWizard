"""D3: plugin boundary — filewizard.extractors entry points."""

from __future__ import annotations

from pathlib import Path

from filewizard.perception import factory


class _FakeEP:
    def __init__(self, name: str, obj) -> None:
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


class _FakeExtractor:
    name = "plugin_fake"

    def extract(self, path: Path):  # noqa: ARG002
        return {"plugin": {"hit": True}}


class _BadExtractor:
    name = "plugin_bad"


def test_load_plugin_extractors_instantiates(monkeypatch) -> None:
    monkeypatch.setattr(
        factory,
        "entry_points",
        lambda group=None: [_FakeEP("fake", _FakeExtractor)],
    )
    loaded = factory.load_plugin_extractors("filewizard.extractors")
    assert len(loaded) == 1
    assert loaded[0].extract(Path("/x")) == {"plugin": {"hit": True}}


def test_load_plugin_extractors_factory_function(monkeypatch) -> None:
    monkeypatch.setattr(
        factory,
        "entry_points",
        lambda group=None: [_FakeEP("fake", _FakeExtractor)],
    )
    # A callable without .extract is treated as a zero-arg factory.
    monkeypatch.setattr(
        factory,
        "entry_points",
        lambda group=None: [_FakeEP("fake", lambda: _FakeExtractor())],
    )
    loaded = factory.load_plugin_extractors()
    assert loaded[0].name == "plugin_fake"


def test_load_plugin_extractors_skips_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        factory,
        "entry_points",
        lambda group=None: [_FakeEP("bad", _BadExtractor)],
    )
    assert factory.load_plugin_extractors() == []


def test_load_plugin_extractors_survives_load_error(monkeypatch) -> None:
    def boom():
        raise RuntimeError("import error")

    monkeypatch.setattr(
        factory,
        "entry_points",
        lambda group=None: [_FakeEP("boom", boom)],
    )
    assert factory.load_plugin_extractors() == []


def test_build_extractors_appends_plugins(monkeypatch, tmp_path) -> None:
    from filewizard.perception.config import config_from_profile

    monkeypatch.setattr(
        factory,
        "load_plugin_extractors",
        lambda: [_FakeExtractor()],
    )
    cfg = config_from_profile("lite")
    xs = factory.build_extractors(cfg, state_dir=tmp_path)
    assert any(getattr(x, "name", "") == "plugin_fake" for x in xs)
