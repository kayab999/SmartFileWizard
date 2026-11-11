"""A4/B5 CLI helpers: benchmark + update check."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner


def test_benchmark_directory_reports(tmp_path: Path) -> None:
    from filewizard.benchmark import benchmark_directory

    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        (src / f"f{i}.txt").write_text("x" * 100)
    report = benchmark_directory(src, iterations=2, limit=10)
    assert report["files"] == 5
    assert report["iterations"] == 2
    assert report["files_per_second"] > 0


def test_benchmark_cli(tmp_path: Path) -> None:
    from filewizard.cli import benchmark_cmd

    runner = CliRunner()
    result = runner.invoke(
        benchmark_cmd,
        ["--source", str(tmp_path), "--iterations", "1", "--limit", "5"],
    )
    assert result.exit_code == 0, result.output
    assert "Files/s" in result.output


def test_update_notice_no_release(monkeypatch) -> None:
    from filewizard.update import update_notice

    monkeypatch.setattr(
        "filewizard.update.latest_release", lambda: None
    )
    assert update_notice("0.11.1") is None


def test_update_notice_same_version(monkeypatch) -> None:
    from filewizard.update import update_notice

    monkeypatch.setattr(
        "filewizard.update.latest_release",
        lambda: {"tag_name": "v0.11.1"},
    )
    assert update_notice("0.11.1") is None


def test_update_notice_new_version(monkeypatch) -> None:
    from filewizard.update import update_notice

    monkeypatch.setattr(
        "filewizard.update.latest_release",
        lambda: {"tag_name": "v9.9.9"},
    )
    notice = update_notice("0.11.1")
    assert notice is not None
    assert "9.9.9" in notice


def test_latest_release_offline_is_none(monkeypatch) -> None:
    import filewizard.update as upd

    def boom(url, timeout):  # noqa: ARG002
        raise OSError("offline")

    monkeypatch.setattr(upd.urllib.request, "urlopen", boom)
    assert upd.latest_release() is None


def test_update_cli(monkeypatch) -> None:
    from filewizard.cli import update_cmd

    monkeypatch.setattr(
        "filewizard.update.update_notice",
        lambda current: "New version 9.9 (current 0.11.1).",
    )
    runner = CliRunner()
    result = runner.invoke(update_cmd)
    assert result.exit_code == 0, result.output
    assert "New version 9.9" in result.output
