from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .engine import ConditionCheck
from .facts import FileFacts
from .journal import Journal
from .models import Rule
from .template import (
    TemplateError,
    render_filename_template,
    render_path_template,
)


def append_unique(path: Path) -> Path:
    """
    If /foo/bar.txt exists, try:
      /foo/bar_1.txt
      /foo/bar_2.txt
      ...
    """

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix

    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"Could not find a unique destination for {path}")


@dataclass
class PlannedOperation:
    source: Path
    rule_id: str
    rule_name: str
    destination: Path | None

    explanations: list[str] = field(default_factory=list)
    conditions: list[ConditionCheck] = field(default_factory=list)

    create_target_dir: bool = True
    on_collision: str = "append"

    status: str = "planned"
    error: str | None = None

    # Compact cascade/ocr/vision evidence (journal snapshot, 0.4.4+)
    perception: dict[str, Any] | None = None


class Executor:
    """
    Execute planned operations.

    Design:

      1. Build a plan first.
      2. Inspect the plan in dry-run.
      3. Real execution is journaled per operation.
      4. Mid-batch failure does not roll back prior successes
         (caller uses undo for that).
      5. Undo refuses to destroy unexpected user data.
    """

    def __init__(
        self,
        journal: Journal,
        dry_run: bool = True,
    ):
        self.journal = journal
        self.dry_run = dry_run

    def plan(
        self,
        facts: FileFacts,
        rule: Rule,
        explanations: list[str] | None = None,
        conditions: list[ConditionCheck] | None = None,
    ) -> PlannedOperation | None:
        action = rule.then
        explanations = list(explanations or [])
        conditions = list(conditions or [])

        if not action.move_to and not action.rename:
            return None

        if not facts.path.exists():
            return PlannedOperation(
                source=facts.path,
                rule_id=rule.id,
                rule_name=rule.name,
                destination=None,
                explanations=explanations,
                conditions=conditions,
                create_target_dir=action.create_target_dir,
                on_collision=action.on_collision,
                status="error",
                error=f"Source no longer exists: {facts.path}",
            )

        if not facts.path.is_file() or facts.path.is_symlink():
            return PlannedOperation(
                source=facts.path,
                rule_id=rule.id,
                rule_name=rule.name,
                destination=None,
                explanations=explanations,
                conditions=conditions,
                create_target_dir=action.create_target_dir,
                on_collision=action.on_collision,
                status="error",
                error=f"Source is not a regular file: {facts.path}",
            )

        try:
            target_dir = facts.path.parent

            if action.move_to:
                target_dir = render_path_template(action.move_to, facts)

                if not target_dir.is_absolute():
                    target_dir = Path.cwd() / target_dir

                target_dir = target_dir.resolve()

            target_name = facts.filename

            if action.rename:
                target_name = render_filename_template(action.rename, facts)

            destination = target_dir / target_name

            if target_dir.exists() and not target_dir.is_dir():
                return PlannedOperation(
                    source=facts.path,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    destination=destination,
                    explanations=explanations,
                    conditions=conditions,
                    create_target_dir=action.create_target_dir,
                    on_collision=action.on_collision,
                    status="error",
                    error=f"Target directory exists and is not a directory: {target_dir}",
                )

            if destination.resolve() == facts.path.resolve():
                return PlannedOperation(
                    source=facts.path,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    destination=destination,
                    explanations=explanations,
                    conditions=conditions,
                    create_target_dir=action.create_target_dir,
                    on_collision=action.on_collision,
                    status="noop",
                )

            if not action.create_target_dir and not target_dir.exists():
                return PlannedOperation(
                    source=facts.path,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    destination=destination,
                    explanations=explanations,
                    conditions=conditions,
                    create_target_dir=action.create_target_dir,
                    on_collision=action.on_collision,
                    status="error",
                    error=(
                        "Target directory does not exist and "
                        "create_target_dir is false"
                    ),
                )

            if destination.exists() and destination.resolve() != facts.path.resolve():
                if action.on_collision == "skip":
                    return PlannedOperation(
                        source=facts.path,
                        rule_id=rule.id,
                        rule_name=rule.name,
                        destination=destination,
                        explanations=explanations,
                        conditions=conditions,
                        create_target_dir=action.create_target_dir,
                        on_collision=action.on_collision,
                        status="skipped",
                    )

                if action.on_collision == "append":
                    destination = append_unique(destination)

                # replace: keep destination; replace on execute.

            return PlannedOperation(
                source=facts.path,
                rule_id=rule.id,
                rule_name=rule.name,
                destination=destination,
                explanations=explanations,
                conditions=conditions,
                create_target_dir=action.create_target_dir,
                on_collision=action.on_collision,
                status="planned",
            )

        except TemplateError as exc:
            return PlannedOperation(
                source=facts.path,
                rule_id=rule.id,
                rule_name=rule.name,
                destination=None,
                explanations=explanations,
                conditions=conditions,
                create_target_dir=action.create_target_dir,
                on_collision=action.on_collision,
                status="error",
                error=str(exc),
            )

    def execute(
        self,
        operations: list[PlannedOperation],
        *,
        cancel=None,
        on_progress=None,
    ) -> list[PlannedOperation]:
        """
        Execute operations in order.

        Failures are isolated: a failed op does not stop the batch.
        Already-done operations remain journaled for undo.
        cancel: CancelToken checked between operations (not mid-move).
        on_progress(done_count, total)
        """
        from .cancel import CancelToken, CancelledError

        batch_id = uuid.uuid4().hex
        total = len(operations)
        finished = 0

        for op in operations:
            if cancel is not None and isinstance(cancel, CancelToken):
                if cancel.is_cancelled():
                    raise CancelledError("Execute cancelled by user")

            if self.dry_run:
                if op.status == "planned":
                    op.status = "dry-run"
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            if op.status != "planned":
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            if op.destination is None:
                op.status = "skipped"
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            if op.source.resolve() == op.destination.resolve():
                op.status = "noop"
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            # Re-validate at execute time (TOCTOU / mid-batch races).
            if not op.source.exists():
                op.status = "error"
                op.error = f"Source no longer exists: {op.source}"
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            if not op.source.is_file() or op.source.is_symlink():
                op.status = "error"
                op.error = f"Source is not a regular file: {op.source}"
                finished += 1
                if on_progress is not None:
                    on_progress(finished, total)
                continue

            byte_size: int | None
            try:
                byte_size = op.source.stat().st_size
            except OSError:
                byte_size = None

            op_id = self.journal.start_operation(
                batch_id=batch_id,
                rule_id=op.rule_id,
                rule_name=op.rule_name,
                op="move",
                source=op.source,
                destination=op.destination,
                byte_size=byte_size,
                perception=op.perception,
            )

            try:
                if op.create_target_dir:
                    op.destination.parent.mkdir(parents=True, exist_ok=True)

                if not op.destination.parent.exists():
                    raise FileNotFoundError(
                        f"Destination directory does not exist: "
                        f"{op.destination.parent}"
                    )

                if not op.destination.parent.is_dir():
                    raise NotADirectoryError(
                        f"Destination parent is not a directory: "
                        f"{op.destination.parent}"
                    )

                final_destination = op.destination

                if (
                    final_destination.exists()
                    and final_destination.resolve() != op.source.resolve()
                ):
                    if op.on_collision == "skip":
                        self.journal.finish_operation(
                            op_id=op_id,
                            status="skipped",
                            destination=final_destination,
                        )
                        op.status = "skipped"
                        finished += 1
                        if on_progress is not None:
                            on_progress(finished, total)
                        continue

                    if op.on_collision == "append":
                        final_destination = append_unique(final_destination)

                    elif op.on_collision == "replace":
                        if final_destination.is_dir():
                            raise IsADirectoryError(
                                "Cannot replace an existing directory"
                            )
                        final_destination.unlink()

                shutil.move(str(op.source), str(final_destination))

                self.journal.finish_operation(
                    op_id=op_id,
                    status="done",
                    destination=final_destination,
                    byte_size=byte_size,
                )

                op.destination = final_destination
                op.status = "done"

            except Exception as exc:
                self.journal.finish_operation(
                    op_id=op_id,
                    status="failed",
                    error=str(exc),
                )
                op.status = "error"
                op.error = str(exc)

            finished += 1
            if on_progress is not None:
                on_progress(finished, total)

        return operations


def _paths_same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def undo_operations(
    journal: Journal,
    rows: Iterable[Any],
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """
    Undo previous moves using the journal.

    Safety rules:
      - Never overwrite an unexpected file at the original path
        (uses append_unique and reports conflict).
      - If the moved file is missing, report missing (do not invent data).
      - If size recorded in journal does not match, refuse (state drift).
      - Double-undo is a no-op for already-undone rows (they leave last_successful_moves).
    """

    results: list[dict[str, Any]] = []
    batch_id = uuid.uuid4().hex

    for row in rows:
        original_op_id = int(row["id"])
        rule_id = str(row["rule_id"])

        # Always re-read status from the journal (caller may hold stale rows).
        live = journal.get_operation(original_op_id)
        if live is None:
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "skipped",
                    "source": None,
                    "destination": None,
                    "error": "Operation not found in journal",
                }
            )
            continue

        status = str(live["status"])
        current = Path(str(live["destination"])) if live["destination"] else Path()
        original = Path(str(live["source"]))
        recorded_size = live["byte_size"] if "byte_size" in live.keys() else None

        if status != "done":
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "skipped",
                    "source": current,
                    "destination": original,
                    "error": f"Operation status is {status!r}, not eligible for undo",
                }
            )
            continue

        if not current.exists():
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "missing",
                    "source": current,
                    "destination": original,
                    "error": (
                        "File expected at journal destination is missing; "
                        "refusing to invent or destroy data"
                    ),
                }
            )
            continue

        try:
            if not current.is_file() or current.is_symlink():
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "state_mismatch",
                        "source": current,
                        "destination": original,
                        "error": "Journal destination is not a regular file",
                    }
                )
                continue
        except OSError as exc:
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "state_mismatch",
                    "source": current,
                    "destination": original,
                    "error": f"Cannot inspect journal destination: {exc}",
                }
            )
            continue

        if recorded_size is not None:
            try:
                actual_size = current.stat().st_size
            except OSError as exc:
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "state_mismatch",
                        "source": current,
                        "destination": original,
                        "error": f"Cannot stat journal destination: {exc}",
                    }
                )
                continue

            if actual_size != int(recorded_size):
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "state_mismatch",
                        "source": current,
                        "destination": original,
                        "error": (
                            f"Size mismatch at destination "
                            f"(journal={recorded_size}, actual={actual_size}); "
                            f"file may have been modified; refusing undo"
                        ),
                    }
                )
                continue

        # File already restored to original path (manual undo).
        if _paths_same_file(current, original):
            journal.mark_undone(original_op_id)
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "already_restored",
                    "source": current,
                    "destination": original,
                }
            )
            continue

        if dry_run:
            conflict = original.exists() and not _paths_same_file(current, original)
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "dry-run",
                    "source": current,
                    "destination": original,
                    "conflict": conflict,
                }
            )
            continue

        live_name = None
        if live is not None and "rule_name" in live.keys():
            live_name = live["rule_name"]

        undo_op_id = journal.start_operation(
            batch_id=batch_id,
            rule_id=rule_id,
            rule_name=f"Undo · {live_name or rule_id}",
            op="undo",
            source=current,
            destination=original,
            byte_size=int(recorded_size) if recorded_size is not None else None,
        )

        try:
            original.parent.mkdir(parents=True, exist_ok=True)

            final_destination = original
            conflict = False

            # Never overwrite an unexpected file at the original path.
            if final_destination.exists() and not _paths_same_file(
                current, final_destination
            ):
                final_destination = append_unique(final_destination)
                conflict = True

            shutil.move(str(current), str(final_destination))

            journal.finish_operation(
                op_id=undo_op_id,
                status="done",
                destination=final_destination,
            )

            journal.mark_undone(original_op_id)

            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "done_with_conflict" if conflict else "done",
                    "source": current,
                    "destination": final_destination,
                    "conflict": conflict,
                }
            )

        except Exception as exc:
            journal.finish_operation(
                op_id=undo_op_id,
                status="failed",
                error=str(exc),
            )

            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": "failed",
                    "source": current,
                    "destination": original,
                    "error": str(exc),
                }
            )

    return results
