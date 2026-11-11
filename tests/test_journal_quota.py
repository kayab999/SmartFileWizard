"""F-16 (E2): journal size quota keeps recoverable rows forever."""

from __future__ import annotations

from pathlib import Path

import pytest

from filewizard.journal import Journal


def _add_row(journal: Journal, source: str, status: str) -> int:
    """Insert a minimal move row with the given status."""
    row_id = journal.start_operation(
        batch_id="b1",
        rule_id="r1",
        op="move",
        source=Path(f"/src/{source}"),
        destination=Path(f"/dst/{source}"),
    )
    journal.finish_operation(row_id, status)
    return row_id


def test_enforce_quota_noop_when_under_limit(tmp_path: Path) -> None:
    with Journal(tmp_path / "journal.db") as journal:
        _add_row(journal, "a.txt", "done")
        assert journal.enforce_quota(max_rows=100) == 0
        assert journal.count_rows() == 1


def test_enforce_quota_trims_oldest_purgeable(tmp_path: Path) -> None:
    with Journal(tmp_path / "journal.db") as journal:
        # 5 failed rows, then 2 done rows (protected).
        failed_ids = [_add_row(journal, f"f{i}.txt", "failed") for i in range(5)]
        done_ids = [_add_row(journal, f"d{i}.txt", "done") for i in range(2)]
        # Quota of 4: evict the 3 oldest failed rows, keep the newest
        # failed row plus both done rows.
        removed = journal.enforce_quota(max_rows=4)
        assert removed == 3
        assert journal.count_rows() == 4
        surviving = {
            row["id"] for row in journal.recent_operations(100)
        }
        # Oldest failed rows evicted; newest failed + both done survive.
        assert surviving == {failed_ids[-2], failed_ids[-1], *done_ids}


def test_enforce_quota_never_touches_protected_statuses(
    tmp_path: Path,
) -> None:
    with Journal(tmp_path / "journal.db") as journal:
        for i in range(6):
            _add_row(journal, f"done{i}.txt", "done")
        for i in range(4):
            _add_row(journal, "p", "pending")
        # No purgeable rows at all → nothing can be removed.
        assert journal.enforce_quota(max_rows=2) == 0
        assert journal.count_rows() == 10


def test_enforce_quota_negative_raises(tmp_path: Path) -> None:
    with Journal(tmp_path / "journal.db") as journal:
        with pytest.raises(ValueError):
            journal.enforce_quota(max_rows=-1)


def test_cli_purge_max_rows(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from filewizard.cli import purge

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    with Journal(state_dir / "journal.db") as journal:
        for i in range(5):
            _add_row(journal, f"f{i}.txt", "failed")
    runner = CliRunner()
    result = runner.invoke(
        purge,
        ["--state-dir", str(state_dir), "--max-rows", "2", "--execute", "--yes"],
    )
    assert result.exit_code == 0, result.output
    with Journal(state_dir / "journal.db") as journal:
        assert journal.count_rows() == 2
