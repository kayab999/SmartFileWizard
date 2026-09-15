"""WP-0.9.4: HTTP 1-inflight, GUI log, WAL, cache cap, close guards."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch


def test_http_lock_serializes_calls(tmp_path: Path) -> None:
    from filewizard.perception import http_openai

    assert hasattr(http_openai, "_HTTP_LOCK")
    order: list[str] = []
    real_lock = http_openai._HTTP_LOCK

    def fake_urlopen(req, timeout=None):
        order.append("enter")
        time.sleep(0.05)
        order.append("exit")

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"choices": [{"message": {"content": "ok"}}]}'

        return Resp()

    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    with (
        patch.object(
            http_openai, "_resize_image_bytes", return_value=(b"img", "image/png")
        ),
        patch.object(http_openai.urllib.request, "urlopen", side_effect=fake_urlopen),
    ):
        threads = [
            threading.Thread(
                target=http_openai.chat_completion_with_image,
                kwargs={
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "m",
                    "prompt": "p",
                    "image_path": img,
                    "timeout_s": 5,
                },
            )
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    assert order == ["enter", "exit", "enter", "exit"]
    assert isinstance(real_lock, type(threading.Lock()))


def test_gui_logging_setup(tmp_path: Path) -> None:
    from filewizard.ui.app import setup_gui_logging

    log_path = setup_gui_logging(tmp_path)
    assert log_path == tmp_path / "filewizard.log"
    logger = logging.getLogger("filewizard")
    logger.info("probe-094")
    found = (tmp_path / "filewizard.log").read_text(encoding="utf-8")
    assert "probe-094" in found
    assert "base64" not in found.lower()
    # Idempotent: no duplicate file handlers.
    setup_gui_logging(tmp_path)
    from logging.handlers import RotatingFileHandler

    assert (
        sum(isinstance(h, RotatingFileHandler) for h in logger.handlers) == 1
    )


def test_journal_wal_mode(tmp_path: Path) -> None:
    from filewizard.journal import Journal

    db = tmp_path / "j.db"
    with Journal(db):
        pass
    conn = sqlite3.connect(db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).lower() == "wal"


def test_cache_skips_huge_files(tmp_path: Path, monkeypatch) -> None:
    from filewizard.perception import cache as cache_mod

    monkeypatch.setattr(cache_mod, "MAX_CACHE_FILE_BYTES", 10)
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 64)

    calls = {"n": 0}

    class Inner:
        name = "inner"

        def extract(self, path):
            calls["n"] += 1
            return {"k": "v"}

    c = cache_mod.PerceptionCache(state_dir=tmp_path)
    ext = cache_mod.CachingExtractor(Inner(), c, config_fp="fp")
    assert ext.extract(big) == {"k": "v"}
    assert calls["n"] == 1
    # Second call still bypasses cache (no put happened).
    assert ext.extract(big) == {"k": "v"}
    assert calls["n"] == 2


def test_reset_runtime_paths_skips_journal(tmp_path: Path) -> None:
    from filewizard.persist import reset_runtime_paths

    (tmp_path / "perception_cache").mkdir()
    (tmp_path / "journal.db").write_bytes(b"x")
    (tmp_path / "filewizard.log").write_text("log", encoding="utf-8")
    paths = reset_runtime_paths(tmp_path)
    names = {p.name for p in paths}
    assert "perception_cache" in names
    assert "filewizard.log" in names
    assert "journal.db" not in names
    assert reset_runtime_paths(tmp_path, wipe_all=True) == [tmp_path]


def test_cli_reset_removes_cache(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import cli

    cache = tmp_path / "perception_cache"
    cache.mkdir()
    (cache / "x.json").write_text("{}", encoding="utf-8")
    (tmp_path / "journal.db").write_bytes(b"db")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["reset", "--state-dir", str(tmp_path), "--yes"],
    )
    assert result.exit_code == 0
    assert not cache.exists()
    assert (tmp_path / "journal.db").is_file()


def test_atomic_write_replaces_and_leaves_no_tmp(tmp_path: Path) -> None:
    from filewizard.persist import atomic_write_text

    path = tmp_path / "state.json"
    atomic_write_text(path, '{"a": 1}')
    assert path.read_text(encoding="utf-8") == '{"a": 1}'
    atomic_write_text(path, '{"a": 2}')
    assert path.read_text(encoding="utf-8") == '{"a": 2}'
    assert not path.with_name(path.name + ".tmp").exists()


def test_close_guards_present() -> None:
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "src" / "filewizard" / "ui"
    watch = (ui / "watch_dialog.py").read_text(encoding="utf-8")
    preview = (ui / "preview_dialog.py").read_text(encoding="utf-8")
    wizard = (ui / "wizard.py").read_text(encoding="utf-8")
    assert "def closeEvent" in watch
    assert "def closeEvent" in preview
    assert "abandon_busy_close" in watch
    assert "abandon_busy_close" in wizard
    assert "Salir de todos modos" in (ui / "util.py").read_text(encoding="utf-8")
