"""WP-0.7.2: read-only MCP tools — handlers testable without stdio."""

import pytest

from filewizard.journal import Journal
from filewizard.mcp.tools import filewizard_collect_facts
from filewizard.mcp.tools import filewizard_journal_batches
from filewizard.mcp.tools import filewizard_list_presets


@pytest.fixture
def state_dir(tmp_path) -> "object":
    return tmp_path


def test_list_presets_empty_when_dir_missing(state_dir) -> None:
    payload = filewizard_list_presets(state_dir)
    assert payload["ok"] is True
    assert payload["tool"] == "filewizard_list_presets"
    assert payload["presets"] == []


def test_list_presets_lists_yaml_with_abs_path(state_dir) -> None:
    presets_dir = state_dir / "presets"
    presets_dir.mkdir(parents=True)
    (presets_dir / "images.yaml").write_text(
        "name: images\nrules:\n"
        "  - id: match-jpg\n    name: Match JPG\n"
        "    when: {extension: jpg}\n    then: {move_to: './fotos'}\n",
        encoding="utf-8",
    )

    payload = filewizard_list_presets(state_dir)
    assert payload["ok"] is True
    assert len(payload["presets"]) == 1
    entry = payload["presets"][0]
    assert entry["name"] == "images"
    assert entry["path"].startswith(str(state_dir.resolve()))
    assert entry["rule_count"] == 1


def test_journal_batches_empty_when_no_db(state_dir) -> None:
    payload = filewizard_journal_batches(state_dir)
    assert payload["ok"] is True
    assert payload["batches"] == []
    assert payload["journal_path"] == str((state_dir / "journal.db").resolve())


def test_journal_batches_aggregates_operations(state_dir) -> None:
    db = state_dir / "journal.db"
    with Journal(db) as journal:
        op_id = journal.start_operation(
            "batch-1",
            "rule-a",
            "move",
            state_dir / "src.txt",
            state_dir / "dst.txt",
            byte_size=10,
            rule_name="Move photos",
        )
        journal.finish_operation(op_id, "done", destination=state_dir / "dst.txt")
        op2 = journal.start_operation(
            "batch-1",
            "rule-b",
            "move",
            state_dir / "src2.txt",
            None,
            byte_size=5,
            rule_name="Move docs",
        )
        journal.finish_operation(op2, "failed", error="boom")

    payload = filewizard_journal_batches(state_dir)
    assert payload["ok"] is True
    assert len(payload["batches"]) == 1
    batch = payload["batches"][0]
    assert batch["batch_id"] == "batch-1"
    assert batch["counts"]["done"] == 1
    assert batch["counts"]["failed"] == 1
    assert batch["total"] == 2
    assert "Move photos" in batch["rule_names"]


def test_collect_facts_single_file(state_dir) -> None:
    f = state_dir / "photo.jpg"
    f.write_bytes(b"fake-jpeg-bytes")

    payload = filewizard_collect_facts(f)
    assert payload["ok"] is True
    facts = payload["facts"]
    assert facts["path"] == str(f.resolve())
    assert facts["filename"] == "photo.jpg"
    assert facts["extension"] == "jpg"
    assert facts["size"] == len(b"fake-jpeg-bytes")
    assert facts["is_image"] is True  # .jpg suffix marks it as image candidate


def test_collect_facts_missing_file(state_dir) -> None:
    payload = filewizard_collect_facts(state_dir / "nope.txt")
    assert payload["ok"] is False
    assert payload["tool"] == "filewizard_collect_facts"
    assert "error" in payload


def test_build_server_registers_read_tools() -> None:
    """Optional-mcp: exercise server build when the SDK is installed."""
    from filewizard.mcp.server import _require_sdk

    try:
        _require_sdk()
    except ImportError:
        return

    from filewizard.mcp.server import build_server

    server = build_server()
    names = [t.name for t in server._tool_manager.list_tools()]
    for expected in (
        "ping",
        "filewizard_version",
        "filewizard_list_presets",
        "filewizard_journal_batches",
        "filewizard_collect_facts",
    ):
        assert expected in names