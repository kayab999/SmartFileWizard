from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..cancel import CancelToken, CancelledError
from ..executor import Executor, undo_operations
from ..journal import Journal
from ..models import RuleSet
from ..pipeline import (
    RulesLoadError,
    default_extractors,
    load_ruleset,
    plan_operations,
    resolve_rules_path,
)
from .options import build_rule

logger = logging.getLogger(__name__)


def ruleset_from_options(options: dict[str, Any]) -> RuleSet:
    """
    Build a RuleSet for preview/execute.

    - preset_name → load from presets library
    - rules_file / rules_path → multi-rule cascade from YAML
    - else → single rule from wizard options (build_rule)
    """
    preset_name = options.get("preset_name")
    if preset_name:
        from ..presets import load_preset

        state = options.get("state_dir")
        state_dir = Path(state) if state else None
        return load_preset(str(preset_name), state_dir)

    rules_ref = options.get("rules_file") or options.get("rules_path")
    if rules_ref:
        path = resolve_rules_path(str(rules_ref))
        return load_ruleset(path)

    rule = build_rule(options)
    return RuleSet(version=1, rules=[rule])


class PreviewWorker(QThread):
    """Build a dry-run plan without applying changes."""

    done = Signal(object, int, str)
    progress = Signal(int, object)  # scanned, limit_or_None

    def __init__(
        self,
        options: dict[str, Any],
        state_dir: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.options = options
        self.state_dir = state_dir
        self.cancel_token = CancelToken()

    def request_cancel(self) -> None:
        self.cancel_token.cancel()

    def run(self) -> None:
        try:
            ruleset = ruleset_from_options(self.options)
            state = Path(str(self.options.get("state_dir") or self.state_dir))
            extractors = default_extractors(
                ocr=bool(self.options.get("enable_ocr")),
                vision=bool(self.options.get("enable_vision")),
                profile=self.options.get("perception_profile"),
                state_dir=state,
            )

            source = Path(str(self.options.get("source"))).expanduser().resolve()
            include_hidden = bool(self.options.get("include_hidden", False))

            limit_value = int(self.options.get("limit", 0) or 0)
            limit = None if limit_value <= 0 else limit_value

            def _progress(scanned: int, lim: int | None) -> None:
                self.progress.emit(scanned, lim)

            # Enqueue uncertain cascade outcomes for manual review.
            from ..review_queue import ReviewQueue

            review_queue = ReviewQueue(state_dir=state)

            def _on_facts(facts) -> None:
                try:
                    # I6: batch the queue write; single save() after planning.
                    review_queue.add_from_features(
                        facts.path, facts.features, save=False
                    )
                except Exception as exc:
                    logger.debug("review enqueue skipped: %s", exc)

            with Journal(self.state_dir / "journal.db") as journal:
                executor = Executor(
                    journal=journal,
                    dry_run=True,
                )
                operations, scanned = plan_operations(
                    source=source,
                    rules=ruleset,
                    executor=executor,
                    extractors=extractors,
                    limit=limit,
                    include_hidden=include_hidden,
                    on_progress=_progress,
                    on_facts=_on_facts,
                    cancel=self.cancel_token,
                )

            try:
                review_queue.save()
            except Exception as exc:
                logger.debug("review queue save skipped: %s", exc)

            self.done.emit(operations, scanned, "")

        except CancelledError:
            try:
                review_queue.save()
            except Exception as exc:
                logger.debug("review queue save skipped: %s", exc)
            self.done.emit([], 0, "cancelado")
        except RulesLoadError as exc:
            self.done.emit([], 0, str(exc))
        except Exception as exc:
            self.done.emit([], 0, str(exc))


class ExecuteWorker(QThread):
    """Execute previously planned operations."""

    done = Signal(object, str)
    progress = Signal(int, int)  # finished, total

    def __init__(
        self,
        operations: list[Any],
        state_dir: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.operations = operations
        self.state_dir = state_dir
        self.cancel_token = CancelToken()

    def request_cancel(self) -> None:
        self.cancel_token.cancel()

    def run(self) -> None:
        try:
            def _progress(done: int, total: int) -> None:
                self.progress.emit(done, total)

            with Journal(self.state_dir / "journal.db") as journal:
                executor = Executor(
                    journal=journal,
                    dry_run=False,
                )
                results = executor.execute(
                    self.operations,
                    cancel=self.cancel_token,
                    on_progress=_progress,
                )

            self.done.emit(results, "")

        except CancelledError:
            self.done.emit([], "cancelado")
        except Exception as exc:
            self.done.emit([], str(exc))


class WatchTickWorker(QThread):
    """Run one watch_once off the GUI thread (H1 / WP-0.9.2)."""

    done = Signal(object, int, str)  # ops, scanned, error

    def __init__(self, watch_config, parent=None):
        super().__init__(parent)
        self.watch_config = watch_config

    def run(self) -> None:
        from ..watch import WatchError, watch_once

        try:
            ops, scanned = watch_once(self.watch_config)
            self.done.emit(ops, scanned, "")
        except WatchError as exc:
            self.done.emit([], 0, str(exc))
        except Exception as exc:
            self.done.emit([], 0, str(exc))


class UndoWorker(QThread):
    """Undo selected journal rows (R5, R12)."""

    done = Signal(object, str)

    def __init__(self, rows, state_dir: Path, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.state_dir = state_dir

    def run(self) -> None:
        try:
            with Journal(self.state_dir / "journal.db") as journal:
                results = undo_operations(journal, self.rows, dry_run=False)
            self.done.emit(results, "")
        except Exception as exc:
            self.done.emit([], str(exc))
