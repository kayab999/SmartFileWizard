"""WP-0.7.3: mutation MCP tools — plan/execute/undo with confirm gate."""

from pathlib import Path

import pytest

from filewizard.journal import Journal
from filewizard.mcp.tools import filewizard_execute
from filewizard.mcp.tools import filewizard_plan
from filewizard.mcp.tools import filewizard_undo_batch


def write_rules(path: Path, out: Path) -> None:
    path.write_text(
        f"name: test\nrules:\n"
        f"  - id: mvtxt\n    name: Move txt\n"
        f"    when: {{extensions: [txt]}}\n"
        f"    then: {{move_to: '{out}'}}\n",
        encoding="utf-8",
    )


@pytest.fixture
def state_dir(tmp_path) -> Path:
    return tmp_path / "state"


def test_plan_never_moves(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    payload = filewizard_plan(src, state_dir, rules=rules)

    assert payload["ok"] is True
    assert payload["tool"] == "filewizard_plan"
    assert payload["scanned"] == 1
    assert len(payload["operations"]) == 1
    assert payload["operations"][0]["status"] == "planned"
    assert (src / "a.txt").is_file()          # still there: plan moved nothing
    assert not out.exists()                    # no dir side effect


def test_plan_requires_exactly_one_rules_source(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    src.mkdir()
    payload = filewizard_plan(src, state_dir)
    assert payload["ok"] is False
    assert payload["tool"] == "filewizard_plan"
    assert "exactly one" in payload["error"]


def test_plan_uses_optional_preset(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.txt").write_text("x", encoding="utf-8")
    presets = state_dir / "presets"
    presets.mkdir(parents=True)
    write_rules(presets / "demo.yaml", tmp_path / "out")

    payload = filewizard_plan(src, state_dir, preset="demo")
    assert payload["ok"] is True
    assert len(payload["operations"]) == 1


def test_execute_without_confirm_fails(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    payload = filewizard_execute(src, state_dir, rules=rules)
    assert payload["ok"] is False
    assert payload["tool"] == "filewizard_execute"
    assert "confirm" in payload["error"].lower()
    assert (src / "a.txt").is_file()           # nothing moved


def test_execute_confirm_moves_and_journals(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("xyz", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    payload = filewizard_execute(src, state_dir, rules=rules, confirm=True)

    assert payload["ok"] is True
    assert payload["batch_id"]
    assert payload["summary"].get("done") == 1
    assert not (src / "a.txt").exists()
    assert (out / "a.txt").read_text(encoding="utf-8") == "xyz"

    # Journal row recorded for undo.
    with Journal(state_dir / "journal.db") as journal:
        rows = journal.done_moves_for_batch(payload["batch_id"])
        assert len(rows) == 1
        assert rows[0]["op"] == "move"


def test_undo_batch_dry_run_default(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("xyz", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    executed = filewizard_execute(src, state_dir, rules=rules, confirm=True)
    batch_id = executed["batch_id"]

    payload = filewizard_undo_batch(batch_id, state_dir)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert (out / "a.txt").is_file()           # dry-run: not restored yet


def test_undo_batch_with_confirm_restores(tmp_path, state_dir) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("xyz", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    executed = filewizard_execute(src, state_dir, rules=rules, confirm=True)
    batch_id = executed["batch_id"]

    payload = filewizard_undo_batch(batch_id, state_dir, confirm=True)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    restored = [r for r in payload["results"] if r["status"] == "done"]
    assert len(restored) == 1
    assert (src / "a.txt").read_text(encoding="utf-8") == "xyz"
    assert not (out / "a.txt").exists()


def test_undo_batch_requires_id(state_dir) -> None:
    payload = filewizard_undo_batch(None, state_dir)
    assert payload["ok"] is False
    assert "batch_id" in payload["error"]


def test_undo_batch_rejects_truthy_non_bool_confirm(tmp_path, state_dir) -> None:
    """String/int confirm must not apply undo (same gate as execute)."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("xyz", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    executed = filewizard_execute(src, state_dir, rules=rules, confirm=True)
    batch_id = executed["batch_id"]

    payload = filewizard_undo_batch(batch_id, state_dir, confirm="true")  # type: ignore[arg-type]
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert (out / "a.txt").is_file()  # still at destination
    assert not (src / "a.txt").exists()


def test_build_server_registers_mutation_tools() -> None:
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
        "filewizard_plan",
        "filewizard_execute",
        "filewizard_undo_batch",
    ):
        assert expected in names