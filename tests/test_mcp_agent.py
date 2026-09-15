"""WP-0.7.4: apply_agent_labels MCP tool + inject normalization reuse."""

from pathlib import Path

import pytest

from filewizard.mcp.tools import filewizard_apply_agent_labels
from filewizard.perception.inject import (
    AgentFeaturesError,
    normalize_agent_features,
)


def write_rules(path: Path, out: Path) -> None:
    path.write_text(
        f"name: test\nrules:\n"
        f"  - id: inv\n    name: Invoice\n"
        f"    when: {{cascade_category_any: [invoice]}}\n"
        f"    then: {{move_to: '{out}'}}\n",
        encoding="utf-8",
    )


def test_normalize_agent_features_canonical() -> None:
    mapping = normalize_agent_features(
        {"/tmp/x.jpg": {"vision": {"invoice": 0.9, "provider": "agent"}}}
    )
    assert mapping["/tmp/x.jpg"] == {"vision": {"invoice": 0.9, "provider": "agent"}}


def test_normalize_rejects_non_dict_value() -> None:
    with pytest.raises(AgentFeaturesError):
        normalize_agent_features({"/tmp/x.jpg": "nope"})


def test_normalize_rejects_non_mapping() -> None:
    with pytest.raises(AgentFeaturesError):
        normalize_agent_features(["not", "a", "mapping"])


def test_apply_labels_normalizes_and_counts(tmp_path) -> None:
    target = tmp_path / "in.jpg"
    target.write_bytes(b"x")
    payload = filewizard_apply_agent_labels(
        {str(target): {"cascade": {"category": "invoice", "confidence": 0.9}}}
    )
    assert payload["ok"] is True
    assert payload["tool"] == "filewizard_apply_agent_labels"
    assert payload["label_count"] == 1
    assert payload["plan"] is None


def test_apply_labels_invalid_shape() -> None:
    payload = filewizard_apply_agent_labels({"bad-entry": "not-a-dict"})
    assert payload["ok"] is False
    assert "error" in payload


def test_apply_labels_optional_plan(tmp_path) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"x")
    rules = tmp_path / "rules.yaml"
    write_rules(rules, out)

    payload = filewizard_apply_agent_labels(
        {str(src / "a.jpg"): {"cascade": {"category": "invoice", "confidence": 0.9}}},
        source=src,
        rules=rules,
    )

    assert payload["ok"] is True
    assert payload["label_count"] == 1
    assert payload["plan"] is not None
    assert payload["plan"]["scanned"] == 1
    assert len(payload["plan"]["operations"]) == 1
    assert payload["plan"]["operations"][0]["status"] == "planned"
    assert str(payload["plan"]["operations"][0]["source"]).endswith("a.jpg")
    # No side effects: source file still present.
    assert (src / "a.jpg").is_file()


def test_apply_labels_plan_uses_preset_rules(tmp_path) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "b.jpg").write_bytes(b"x")
    state = tmp_path / "state"
    presets = state / "presets"
    presets.mkdir(parents=True)
    write_rules(presets / "invoices.yaml", out)

    payload = filewizard_apply_agent_labels(
        {str((src / "b.jpg").resolve()): {"cascade": {"category": "invoice"}}},
        source=src,
        state_dir=state,
        preset="invoices",
    )
    assert payload["ok"] is True
    assert len(payload["plan"]["operations"]) == 1


def test_build_server_registers_apply_labels() -> None:
    """Optional-mcp: exercise server build when the SDK is installed."""
    from filewizard.mcp.server import _require_sdk

    try:
        _require_sdk()
    except ImportError:
        return

    from filewizard.mcp.server import build_server

    server = build_server()
    names = [t.name for t in server._tool_manager.list_tools()]
    assert "filewizard_apply_agent_labels" in names