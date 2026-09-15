"""WP-0.9.5: MCP allowed_roots jail + CLI pending warning."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def jail_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plan/execute read mcp.yaml from here, not from the tool's state_dir."""
    monkeypatch.setattr(
        "filewizard.mcp.tools.mcp_jail_config_dir",
        lambda: tmp_path,
    )
    return tmp_path


def _rules(path: Path, dest: Path) -> None:
    path.write_text(
        "name: t\nrules:\n"
        "  - id: r1\n    name: R1\n"
        "    when: {extensions: [txt]}\n"
        f"    then: {{move_to: '{dest}'}}\n",
        encoding="utf-8",
    )


def test_no_roots_by_default(tmp_path: Path) -> None:
    from filewizard.mcp.tools import mcp_allowed_roots

    assert mcp_allowed_roots(tmp_path) == []


def test_env_root_blocks_outside_source(tmp_path: Path, monkeypatch) -> None:
    from filewizard.mcp.tools import filewizard_execute, filewizard_plan

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (outside / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    _rules(rules, allowed)
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(allowed))

    plan = filewizard_plan(outside, tmp_path, rules=rules)
    assert plan["ok"] is False
    assert "allowed_roots" in plan["error"]

    # confirm=true does NOT bypass the jail.
    executed = filewizard_execute(outside, tmp_path, rules=rules, confirm=True)
    assert executed["ok"] is False
    assert "allowed_roots" in executed["error"]
    assert (outside / "a.txt").is_file()


def test_config_roots_and_inside_source_ok(jail_home: Path, monkeypatch) -> None:
    tmp_path = jail_home
    from filewizard.mcp.tools import filewizard_execute, mcp_allowed_roots

    monkeypatch.delenv("FILEWIZARD_SOURCE_ROOT", raising=False)
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    _rules(rules, out)
    (tmp_path / "mcp.yaml").write_text(
        yaml.safe_dump({"allowed_roots": [str(src), str(out)]}),
        encoding="utf-8",
    )
    assert len(mcp_allowed_roots(tmp_path)) == 2

    res = filewizard_execute(src, tmp_path, rules=rules, confirm=True)
    assert res["ok"] is True
    assert (out / "a.txt").is_file()


def test_destination_jail_blocks_escape(jail_home: Path, monkeypatch) -> None:
    tmp_path = jail_home
    from filewizard.mcp.tools import filewizard_execute, filewizard_plan

    monkeypatch.delenv("FILEWIZARD_SOURCE_ROOT", raising=False)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    jail = tmp_path / "jail"
    jail.mkdir()
    outside = tmp_path / "escape"
    outside.mkdir()
    rules = tmp_path / "rules.yaml"
    _rules(rules, outside)  # destination outside the jail
    (tmp_path / "mcp.yaml").write_text(
        yaml.safe_dump({"mcp": {"allowed_roots": [str(jail)]}}),
        encoding="utf-8",
    )
    # source itself must be inside to reach the destination check
    (tmp_path / "mcp.yaml").write_text(
        yaml.safe_dump({"allowed_roots": [str(src), str(jail)]}),
        encoding="utf-8",
    )

    plan = filewizard_plan(src, tmp_path, rules=rules)
    assert plan["ok"] is True
    assert plan["operations"]
    assert plan["operations"][0]["status"] == "error"
    assert "allowed_roots" in (plan["operations"][0]["error"] or "")

    res = filewizard_execute(src, tmp_path, rules=rules, confirm=True)
    assert res["ok"] is True
    assert (src / "a.txt").is_file()  # nothing moved
    assert not (outside / "a.txt").exists()


def test_env_overrides_yaml_roots(tmp_path: Path, monkeypatch) -> None:
    from filewizard.mcp.tools import mcp_allowed_roots

    env_root = tmp_path / "envroot"
    yaml_root = tmp_path / "yamlroot"
    env_root.mkdir()
    yaml_root.mkdir()
    (tmp_path / "mcp.yaml").write_text(
        yaml.safe_dump({"allowed_roots": [str(yaml_root)]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(env_root))
    roots = mcp_allowed_roots(tmp_path)
    assert roots == [env_root.resolve()]


def test_collect_facts_honors_source_jail(tmp_path: Path, monkeypatch) -> None:
    # C3 (0.9.8): collect_facts is jailed like plan/execute (fail-closed).
    from filewizard.mcp.tools import filewizard_collect_facts

    monkeypatch.setenv("FILEWIZARD_SOURCE_ROOT", str(tmp_path / "jail"))
    f = tmp_path / "outside.txt"
    f.write_text("hi", encoding="utf-8")
    payload = filewizard_collect_facts(f)
    assert payload["ok"] is False
    assert "allowed_roots" in payload["error"]


def test_cli_warns_on_pending(tmp_path: Path) -> None:
    from filewizard.cli import cli
    from filewizard.journal import Journal

    state = tmp_path / "state"
    state.mkdir()
    with Journal(state / "journal.db") as journal:
        journal.start_operation(
            batch_id="b1",
            rule_id="r",
            op="move",
            source=tmp_path / "a.txt",
            destination=tmp_path / "b.txt",
        )
    runner = CliRunner()
    src = tmp_path / "src"
    src.mkdir()
    result = runner.invoke(
        cli,
        ["undo", "--state-dir", str(state)],
    )
    assert "pending" in result.output.lower()


def test_tool_state_dir_does_not_bypass_yaml_jail(
    jail_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """Agent-supplied state_dir must not skip ~/.local/.../mcp.yaml."""
    from filewizard.mcp.tools import filewizard_plan

    monkeypatch.delenv("FILEWIZARD_SOURCE_ROOT", raising=False)
    allowed = jail_home / "allowed"
    allowed.mkdir()
    (jail_home / "mcp.yaml").write_text(
        yaml.safe_dump({"allowed_roots": [str(allowed)]}),
        encoding="utf-8",
    )
    other_state = tmp_path / "agent_state"
    other_state.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    _rules(rules, allowed)

    plan = filewizard_plan(outside, other_state, rules=rules)
    assert plan["ok"] is False
    assert "allowed_roots" in plan["error"]


def test_corrupt_mcp_yaml_fails_closed(jail_home: Path, monkeypatch) -> None:
    from filewizard.mcp.tools import McpJailError, filewizard_plan, mcp_allowed_roots

    monkeypatch.delenv("FILEWIZARD_SOURCE_ROOT", raising=False)
    (jail_home / "mcp.yaml").write_text("{not-yaml", encoding="utf-8")
    with pytest.raises(McpJailError):
        mcp_allowed_roots(jail_home)

    src = jail_home / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = jail_home / "rules.yaml"
    _rules(rules, jail_home / "out")
    plan = filewizard_plan(src, jail_home, rules=rules)
    assert plan["ok"] is False
    assert "mcp.yaml" in plan["error"]
