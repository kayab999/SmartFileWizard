"""Pending-row recovery, model-only holds, MCP write jail, HTTP cancel."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from filewizard.cancel import CancelledError
from filewizard.executor import Executor, undo_operations
from filewizard.facts import FileFacts
from filewizard.journal import Journal
from filewizard.model_gate import model_match_may_apply
from filewizard.models import Action, Condition, Rule
from filewizard.pipeline import plan_operations


def _facts(path: Path, **features) -> FileFacts:
    path.write_bytes(path.read_bytes() if path.exists() else b"x")
    return FileFacts(
        path=path,
        size=path.stat().st_size,
        mime="image/jpeg",
        extension="jpg",
        filename=path.name,
        stem=path.stem,
        mtime=datetime.now(timezone.utc),
        is_image=True,
        features=features,
    )


def test_reconcile_pending_promotes_landed_move(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    dest = tmp_path / "out" / "a.txt"
    source.write_text("hello", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    op_id = journal.start_operation(
        batch_id="b",
        rule_id="r",
        op="move",
        source=source,
        destination=dest,
        byte_size=source.stat().st_size,
    )
    dest.parent.mkdir()
    dest.write_text("hello", encoding="utf-8")
    source.unlink()
    promoted, remaining = journal.reconcile_pending()
    journal.close()
    assert promoted == 1
    assert remaining == 0
    row = Journal(tmp_path / "j.db").get_operation(op_id)
    assert row["status"] == "done"


def test_reconcile_pending_keeps_size_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    dest = tmp_path / "out" / "a.txt"
    source.write_text("hello", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    journal.start_operation(
        batch_id="b",
        rule_id="r",
        op="move",
        source=source,
        destination=dest,
        byte_size=5,
    )
    dest.parent.mkdir()
    dest.write_text("hello!", encoding="utf-8")
    source.unlink()
    promoted, remaining = journal.reconcile_pending()
    journal.close()
    assert promoted == 0
    assert remaining == 1


def test_undo_cancel_stops_between_rows(tmp_path: Path) -> None:
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "b.txt").write_text("b", encoding="utf-8")
    journal = Journal(tmp_path / "j.db")
    rule = Rule(
        id="mv",
        name="mv",
        when=Condition(extensions=["txt"]),
        then=Action(move_to=str(out)),
    )
    from filewizard.engine import Engine
    from filewizard.facts import collect_facts

    engine = Engine([rule])
    executor = Executor(journal=journal, dry_run=False)
    ops = []
    for path in sorted(src.glob("*.txt")):
        facts = collect_facts(path)
        match = next(engine.evaluate(facts))
        ops.append(executor.plan(facts=facts, rule=match.rule))
    executor.execute(ops)
    rows = list(reversed(journal.done_moves_for_batch(journal.recent_batches(1)[0]["batch_id"])))

    class StopAfterFirst:
        def __init__(self) -> None:
            self.calls = 0

        def is_cancelled(self) -> bool:
            self.calls += 1
            return self.calls > 1

    with pytest.raises(CancelledError):
        undo_operations(journal, rows, dry_run=False, cancel=StopAfterFirst())
    journal.close()
    restored = list(src.glob("*.txt"))
    assert len(restored) == 1


def test_model_only_match_is_held_until_override_or_agreement(tmp_path: Path) -> None:
    img = tmp_path / "a.jpg"
    img.write_bytes(b"img")
    model_rule = Rule(
        id="model",
        name="Model",
        when=Condition(cascade_category_any=["factura"]),
        then=Action(move_to=str(tmp_path / "invoices")),
    )
    same_place = Rule(
        id="name",
        name="Name",
        priority=1,
        when=Condition(filename_regex=r".*"),
        then=Action(move_to=str(tmp_path / "invoices")),
    )
    other_place = Rule(
        id="other",
        name="Other",
        when=Condition(extensions=["jpg"]),
        then=Action(move_to=str(tmp_path / "photos")),
    )
    facts = _facts(
        img,
        cascade={"category": "factura", "status": "confirmed", "confidence": 0.99},
    )
    assert model_match_may_apply([model_rule], facts, model_rule, allow_model_only=False) is False
    assert model_match_may_apply([model_rule], facts, model_rule, allow_model_only=True) is True
    assert (
        model_match_may_apply(
            [model_rule, same_place], facts, model_rule, allow_model_only=False
        )
        is True
    )
    assert (
        model_match_may_apply(
            [model_rule, other_place], facts, model_rule, allow_model_only=False
        )
        is False
    )
    reviewed = _facts(
        img,
        cascade={"category": "factura", "status": "confirmed"},
        vision={"invoice": 1.0, "provider": "review"},
    )
    assert model_match_may_apply([model_rule], reviewed, model_rule, allow_model_only=False)

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"img")
    journal = Journal(tmp_path / "j.db")
    ops, _ = plan_operations(
        source=src,
        rules=[model_rule],
        executor=Executor(journal=journal, dry_run=True),
        extractors=[],
    )
    journal.close()
    # No cascade features on a raw jpeg, so the model rule does not match.
    assert ops == []


def test_mcp_execute_without_jail_does_not_move(tmp_path: Path, monkeypatch) -> None:
    from filewizard.mcp.tools import JAIL_UNCONFIGURED, filewizard_execute

    monkeypatch.delenv("FILEWIZARD_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(
        "filewizard.mcp.tools.mcp_jail_config_dir",
        lambda: tmp_path / "empty-state",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "name: t\nrules:\n"
        "  - id: r\n    name: R\n"
        "    when: {extensions: [txt]}\n"
        f"    then: {{move_to: '{tmp_path / 'out'}'}}\n",
        encoding="utf-8",
    )
    payload = filewizard_execute(src, tmp_path / "state", rules=rules, confirm=True)
    assert payload["ok"] is False
    assert payload["error"] == JAIL_UNCONFIGURED
    assert (src / "a.txt").is_file()


def test_cancel_inflight_http_closes_the_client(tmp_path: Path) -> None:
    from filewizard.perception import http_openai

    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    started = threading.Event()

    def blocking_post(*args, **kwargs):
        started.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            client = http_openai._ACTIVE_CLIENT
            if client is None or client.is_closed:
                request = httpx.Request("POST", "http://127.0.0.1:9/v1")
                raise httpx.RequestError("closed", request=request)
            time.sleep(0.01)
        raise AssertionError("request was not cancelled")

    with (
        pytest.MonkeyPatch.context() as patch,
    ):
        patch.setattr(http_openai, "_resize_image_bytes", lambda path, edge: (b"img", "image/png"))
        patch.setattr(http_openai.httpx.Client, "post", blocking_post)
        error: list[BaseException] = []

        def call() -> None:
            try:
                http_openai.chat_completion_with_image(
                    base_url="http://127.0.0.1:9/v1",
                    model="m",
                    prompt="p",
                    image_path=img,
                    timeout_s=5,
                )
            except CancelledError as exc:
                error.append(exc)

        thread = threading.Thread(target=call)
        thread.start()
        assert started.wait(2)
        http_openai.cancel_inflight_http()
        thread.join(2)
    assert not thread.is_alive()
    assert error and isinstance(error[0], CancelledError)


def test_single_instance_second_launch_signals_the_first() -> None:
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from filewizard.ui.single_instance import claim_primary

    app = QApplication.instance() or QApplication([])
    name = "filewizard-gui-test-lifecycle"
    first = claim_primary(name)
    assert first is not None
    first.setParent(app)
    second = claim_primary(name)
    assert second is None
    first.close()
