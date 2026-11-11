"""A2: concurrent fact collection in plan_operations (workers > 1)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from filewizard.cancel import CancelToken
from filewizard.executor import Executor
from filewizard.journal import Journal
from filewizard.models import Rule, RuleSet
from filewizard.pipeline import plan_operations


def _ruleset_with_one_rule(tmp_path: Path) -> RuleSet:
    dest = tmp_path / "out"
    return RuleSet(
        rules=[
            Rule(
                id="r1",
                name="move-all",
                when={"extensions": [".txt"]},
                then={"move_to": str(dest)},
                priority=1,
            )
        ]
    )


def _make_files(tmp_path: Path, n: int) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(n):
        (src / f"f{i}.txt").write_text(f"content {i}")
    return src


def test_parallel_matches_sequential_results(tmp_path: Path) -> None:
    src = _make_files(tmp_path, 12)
    rules = _ruleset_with_one_rule(tmp_path)

    with Journal(tmp_path / "j1.db") as journal:
        seq_ops, seq_scanned = plan_operations(
            src, rules, Executor(journal=journal, dry_run=True)
        )
    with Journal(tmp_path / "j2.db") as journal:
        par_ops, par_scanned = plan_operations(
            src, rules, Executor(journal=journal, dry_run=True), workers=4
        )

    assert par_scanned == seq_scanned == 12
    assert [(op.source, op.destination) for op in par_ops] == [
        (op.source, op.destination) for op in seq_ops
    ]


def test_parallel_prefetch_overlaps_facts(tmp_path: Path) -> None:
    """Workers actually collect facts concurrently."""
    src = _make_files(tmp_path, 6)

    class SlowExtractor:
        name = "slow"

        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def extract(self, path: Path):  # noqa: ARG002
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.05)
            with self.lock:
                self.active -= 1
            return {}

    rules = _ruleset_with_one_rule(tmp_path)
    ext = SlowExtractor()
    with Journal(tmp_path / "j.db") as journal:
        plan_operations(
            src,
            rules,
            Executor(journal=journal, dry_run=True),
            extractors=[ext],
            workers=3,
        )
    assert ext.max_active > 1


def test_parallel_respects_limit_and_order(tmp_path: Path) -> None:
    src = _make_files(tmp_path, 10)
    rules = _ruleset_with_one_rule(tmp_path)
    seen: list[str] = []

    with Journal(tmp_path / "j.db") as journal:
        ops, scanned = plan_operations(
            src,
            rules,
            Executor(journal=journal, dry_run=True),
            extractors=None,
            workers=4,
            limit=4,
            on_progress=lambda done, _total: seen.append(f"{done}"),
        )
    assert scanned == 4
    assert len(ops) == 4
    # Progress counts 1..4 strictly increasing.
    assert seen == ["1", "2", "3", "4"]


def test_parallel_cancellation_stops(tmp_path: Path) -> None:
    src = _make_files(tmp_path, 8)
    rules = _ruleset_with_one_rule(tmp_path)
    cancel = CancelToken()

    class CancelAfterThree:
        name = "cancel3"

        def extract(self, path: Path):  # noqa: ARG002
            pass

    with Journal(tmp_path / "j.db") as journal:
        def on_progress(done, _total):
            if done == 3:
                cancel.cancel()

        with pytest.raises(Exception):
            plan_operations(
                src,
                rules,
                Executor(journal=journal, dry_run=True),
                workers=2,
                on_progress=on_progress,
                cancel=cancel,
            )


def test_parallel_fact_error_does_not_abort(tmp_path: Path) -> None:
    src = _make_files(tmp_path, 4)
    rules = _ruleset_with_one_rule(tmp_path)

    class BoomExtractor:
        name = "boom"

        def extract(self, path: Path):
            if "f2" in path.name:
                raise RuntimeError("boom")
            return {}

    # collect_facts records extractor failures in features["errors"]
    # (same as the sequential path); the batch must not abort and must
    # report all files scanned.
    error_files: list[str] = []

    def on_facts(facts):
        errs = facts.features.get("errors") or []
        if errs:
            error_files.append(facts.path.name)

    with Journal(tmp_path / "j.db") as journal:
        ops, scanned = plan_operations(
            src,
            rules,
            Executor(journal=journal, dry_run=True),
            extractors=[BoomExtractor()],
            workers=2,
            on_facts=on_facts,
        )
    assert scanned == 4
    assert error_files == ["f2.txt"]
