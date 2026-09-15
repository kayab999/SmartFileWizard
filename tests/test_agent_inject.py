import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from filewizard.cli import cli
from filewizard.executor import Executor
from filewizard.facts import collect_facts
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.perception.inject import (
    AgentFeaturesError,
    AgentFeaturesExtractor,
    load_agent_features,
)
from filewizard.pipeline import default_extractors, plan_operations


def _png(path: Path) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def test_load_agent_features_json(tmp_path: Path) -> None:
    features = {
        "/abs/invoice.jpg": {
            "vision": {"invoice": 0.91, "provider": "agent"},
            "cascade": {
                "stage_used": 0,
                "category": "factura",
                "confidence": 0.91,
                "status": "confirmed",
            },
        }
    }
    p = tmp_path / "agent.json"
    p.write_text(json.dumps(features), encoding="utf-8")
    loaded = load_agent_features(p)
    assert loaded["/abs/invoice.jpg"]["cascade"]["category"] == "factura"
    assert loaded["/abs/invoice.jpg"]["vision"]["provider"] == "agent"


def test_load_agent_features_relative_key_resolved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "agent.json"
    p.write_text(
        json.dumps({"sub/in.jpg": {"vision": {"invoice": 0.9, "provider": "agent"}}}),
        encoding="utf-8",
    )
    loaded = load_agent_features(p)
    expected = str((tmp_path / "sub/in.jpg").resolve())
    assert expected in loaded


def test_invalid_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentFeaturesError):
        load_agent_features(p)


def test_non_dict_value_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"/a.jpg": ["not", "a", "dict"]}), encoding="utf-8")
    with pytest.raises(AgentFeaturesError):
        load_agent_features(p)


def test_injector_known_and_unknown_path(tmp_path: Path) -> None:
    target = tmp_path / "invoice.jpg"
    target.write_bytes(b"fake")
    key = str(target.resolve())
    ext = AgentFeaturesExtractor({key: {"vision": {"invoice": 0.9}}})
    assert ext.name == "agent_inject"
    assert ext.extract(target) == {"vision": {"invoice": 0.9}}
    assert ext.extract(tmp_path / "other.jpg") == {}


def test_plan_with_agent_cascade_matches_without_http(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    img = src / "invoice.png"
    _png(img)

    rules = RuleSet(
        rules=[
            Rule(
                id="invoice-agent",
                name="Invoice agent",
                priority=1,
                when=Condition(
                    cascade_category_any=["factura"],
                    cascade_status_any=["confirmed"],
                ),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ]
    )

    agent_file = tmp_path / "agent.json"
    agent_file.write_text(
        json.dumps(
            {
                str(img.resolve()): {
                    "cascade": {
                        "stage_used": 0,
                        "category": "factura",
                        "confidence": 0.91,
                        "status": "confirmed",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=True)
    ops, scanned = plan_operations(
        source=src,
        rules=rules,
        executor=executor,
        extractors=default_extractors(agent_features=agent_file),
    )
    journal.close()
    assert scanned == 1
    assert len(ops) == 1
    assert ops[0].rule_id == "invoice-agent"


def test_plan_with_agent_vision_label_matches_without_http(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    img = src / "doc.png"
    _png(img)

    rules = RuleSet(
        rules=[
            Rule(
                id="invoice-vision",
                name="Invoice vision",
                priority=1,
                when=Condition(vision_label_gt={"invoice": 0.85}),
                then=Action(move_to=str(tmp_path / "out")),
            )
        ]
    )

    agent_file = tmp_path / "agent.json"
    agent_file.write_text(
        json.dumps(
            {str(img.resolve()): {"vision": {"invoice": 0.91, "provider": "agent"}}}
        ),
        encoding="utf-8",
    )

    journal = Journal(tmp_path / "j.db")
    executor = Executor(journal=journal, dry_run=True)
    ops, _ = plan_operations(
        source=src,
        rules=rules,
        executor=executor,
        extractors=default_extractors(agent_features=agent_file),
    )
    journal.close()
    assert len(ops) == 1


def test_agent_overrides_cascade_last_wins(tmp_path: Path) -> None:
    class FakeCascade:
        name = "cascade"

        def extract(self, path: Path) -> dict:
            return {
                "cascade": {
                    "stage_used": 2,
                    "category": "foto",
                    "confidence": 0.5,
                    "status": "probable",
                },
                "vision": {"screenshot": 0.99, "provider": "cascade"},
            }

    img = tmp_path / "x.png"
    _png(img)
    ext = AgentFeaturesExtractor(
        {str(img.resolve()): {"vision": {"invoice": 0.9, "provider": "agent"}}}
    )
    facts = collect_facts(img, extractors=[FakeCascade(), ext])
    # Agent runs after cascade -> vision overridden, cascade untouched.
    assert facts.features["vision"]["provider"] == "agent"
    assert facts.features["vision"]["invoice"] == 0.9
    assert facts.features["cascade"]["category"] == "foto"


def test_cli_run_agent_features_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    img = src / "invoice.png"
    _png(img)

    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\n"
        "rules:\n"
        "  - id: inv\n"
        "    name: inv\n"
        "    when:\n"
        "      cascade_category_any: [factura]\n"
        "    then:\n"
        f"      move_to: {str(tmp_path / 'out')}\n",
        encoding="utf-8",
    )

    agent = tmp_path / "agent.json"
    agent.write_text(
        json.dumps(
            {
                str(img.resolve()): {
                    "cascade": {
                        "stage_used": 0,
                        "category": "factura",
                        "status": "confirmed",
                        "confidence": 0.9,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--source",
            str(src),
            "--rules",
            str(rules),
            "--agent-features",
            str(agent),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "inv" in result.output
    assert "Dry run only" in result.output


def test_cli_agent_features_bad_json_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    src = tmp_path / "in"
    src.mkdir()
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\n"
        "rules:\n"
        "  - id: a\n"
        "    name: a\n"
        "    when:\n"
        "      always: true\n"
        "    then:\n"
        f"      move_to: {str(tmp_path / 'out')}\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--source",
            str(src),
            "--rules",
            str(rules),
            "--agent-features",
            str(bad),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert result.exit_code != 0
    assert "Cannot load agent features" in result.output
