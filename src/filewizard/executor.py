from __future__ import annotations

import errno
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .engine import ConditionCheck
from .facts import FileFacts
from .fsmove import DestinationExistsError
from .fsmove import move_noreplace, move_noreplace_unique
from .persist import ensure_private_dir
from .identity import FileIdentity
from .journal import Journal
from .models import Rule
from .template import (
    TemplateError,
    render_filename_template,
    render_path_template,
)


def suggest_unique(path: Path) -> Path:
    """Next free name for a dry-run preview. Does not create a file."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find a unique destination for {path}")


def append_unique(path: Path) -> Path:
    """Reserve a destination name with an exclusive create.

    The returned path exists as an empty file owned by this call. A later
    move replaces that placeholder. Two processes cannot receive the same name.
    """

    def _reserve(candidate: Path) -> bool:
        try:
            fd = os.open(
                candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        except FileExistsError:
            return False
        os.close(fd)
        return True

    if _reserve(path):
        return path

    stem = path.stem
    suffix = path.suffix
    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if _reserve(candidate):
            return candidate

    raise FileExistsError(f"Could not find a unique destination for {path}")


def _status_from_identity(
    destination: Path,
    *,
    size: int | None,
    sha256: str | None,
    device: int | None,
    inode: int | None,
) -> str:
    """R8.1: ``done`` is E1-only, including undo and EXDEV paths.

    A matching expected and observed SHA-256 is the sole path to
    ``done``. Without a hash, compatible fs identity is only E2 and is
    journaled as ``needs_verify``. Missing, divergent or unverifiable
    evidence is never upgraded to ``done``.
    """
    try:
        if destination.is_symlink() or not destination.is_file():
            return "needs_verify"
        st = destination.stat()
        if sha256 is not None:
            from .perception.cache import file_content_hash

            return (
                "done"
                if file_content_hash(destination) == sha256
                else "needs_verify"
            )
        if size is None or device is None or inode is None:
            return "needs_verify"
        if int(st.st_size) == int(size) and int(st.st_dev) == int(device) and int(st.st_ino) == int(inode):
            return "needs_verify"  # E2 only (same-file metadata).
    except OSError:
        return "needs_verify"
    return "needs_verify"


def _post_move_status(op: PlannedOperation, final_destination: Path) -> str:
    return _status_from_identity(
        final_destination,
        size=op.identity_size,
        sha256=op.identity_sha256,
        device=op.identity_dev,
        inode=op.identity_ino,
    )


def _planned_backup_path(
    journal: Journal, op_id: int, destination: Path
) -> Path:
    """Deterministic backup path for a replace displacement.

    Persisted as the displacement intent BEFORE the physical move
    (ADR-0005 WP-A2), so a crash in any window leaves the backup either
    present at a known path or absent with the destination untouched.
    """
    journal_path = Path(journal.path)
    parent = (
        Path.cwd()
        if journal_path.name == ":memory:"
        else journal_path.expanduser().parent
    )
    return parent / "displaced" / f"{op_id}{destination.suffix}"


def _ensure_displace_capacity(
    backup: Path, op: PlannedOperation, destination: Path
) -> None:
    """R8.5: fail replace before displacement when EXDEV staging cannot fit.

    Same-filesystem renames need no duplicate payload. For EXDEV, reserve
    the displaced size (plus the moved source when its publication also
    crosses devices) and a fixed 1 MiB journal/staging margin.
    """
    from .fsmove import _same_fs

    required = 0
    try:
        if not _same_fs(destination, backup.parent):
            required += destination.stat().st_size
        if op.identity_size is not None and not _same_fs(
            op.source, destination.parent
        ):
            required += int(op.identity_size)
    except OSError:
        raise
    probe = backup.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        available = os.statvfs(probe).f_bavail * os.statvfs(probe).f_frsize
    except OSError as exc:
        raise OSError(
            errno.EIO,
            f"cannot inspect free space for displaced backup: {exc}",
            str(probe),
        ) from exc
    if required and available < required + 1024 * 1024:
        raise OSError(
            errno.ENOSPC,
            "insufficient free space for replace backup: "
            f"required={required + 1024 * 1024}, available={available}",
            str(destination),
        )


def _displace(
    journal: Journal, op_id: int, destination: Path, backup: Path
) -> Path:
    """Move an occupied destination aside so replace can be undone.

    The caller persists the intent (``set_displaced``) before calling
    this. Same filesystem: atomic ``rename``. EXDEV: verified copy first
    (size ± hash, fsynced) and the destination is removed only after the
    copy verifies — a failed copy leaves the original untouched.
    """
    if backup.exists():  # op ids are unique; this must never happen
        raise FileExistsError(f"Backup path already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    # E2 (F-05b): backups are copies of user files — owner-only dir.
    ensure_private_dir(backup.parent)
    # R8.6/R8.7: EXDEV uses pre-copy evidence, copy2 metadata
    # preservation and atomic no-replace publication, like normal moves.
    move_noreplace(destination, backup)
    return backup


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

    # Source identity captured at plan time. None on legacy plans.
    identity_size: int | None = None
    identity_mtime_ns: int | None = None
    identity_dev: int | None = None
    identity_ino: int | None = None
    identity_sha256: str | None = None


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
        identity_pre: FileIdentity | None = None,
    ) -> PlannedOperation | None:
        action = rule.then
        explanations = list(explanations or [])
        conditions = list(conditions or [])

        if not action.move_to and not action.rename:
            return None

        if identity_pre is not None:
            # WP-B1 (F-07): the identity captured BEFORE perception
            # must describe the same file object as the one captured
            # at plan time. A substitution during OCR/vision/HTTP
            # extraction would otherwise let a decision built on the
            # original's evidence move the substitute.
            from .identity import capture_identity as _capture_identity

            try:
                identity_now = _capture_identity(facts.path)
            except OSError:
                identity_now = None
            if identity_now is None or identity_now != identity_pre:
                return PlannedOperation(
                    source=facts.path,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    destination=None,
                    explanations=explanations,
                    conditions=conditions,
                    create_target_dir=action.create_target_dir,
                    on_collision=action.on_collision,
                    status="stale",
                    error=(
                        "Source changed during perception; the rule "
                        "decision may describe a different file object"
                    ),
                )

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
                    destination = suggest_unique(destination)

                # replace: keep destination; replace on execute.

            from .identity import capture_identity

            identity = capture_identity(facts.path)
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
                identity_size=identity.size if identity else None,
                identity_mtime_ns=identity.mtime_ns if identity else None,
                identity_dev=identity.device if identity else None,
                identity_ino=identity.inode if identity else None,
                identity_sha256=identity.sha256 if identity else None,
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
        batch_id: str | None = None,
    ) -> list[PlannedOperation]:
        """
        Execute operations in order.

        Failures are isolated: a failed op does not stop the batch.
        Already-done operations remain journaled for undo.
        cancel: CancelToken checked between operations (not mid-move).
        on_progress(done_count, total)
        batch_id: request-scoped batch identifier (ADR-0005). The caller
        that owns the request generates it and receives the same value
        back; the executor never attributes results by global lookup.
        """
        from .cancel import CancelToken, CancelledError

        batch_id = batch_id or uuid.uuid4().hex
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

            if op.identity_mtime_ns is not None:
                from .identity import FileIdentity, identity_matches

                planned_identity = FileIdentity(
                    size=int(op.identity_size or 0),
                    mtime_ns=int(op.identity_mtime_ns),
                    device=int(op.identity_dev or 0),
                    inode=int(op.identity_ino or 0),
                    sha256=op.identity_sha256,
                )
                if not identity_matches(op.source, planned_identity):
                    op.status = "stale"
                    op.error = (
                        "Source changed after the plan was built; not moved"
                    )
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
                byte_size=op.identity_size
                if op.identity_size is not None
                else byte_size,
                perception=op.perception,
                content_sha256=op.identity_sha256,
                source_mtime_ns=op.identity_mtime_ns,
                source_dev=op.identity_dev,
                source_ino=op.identity_ino,
            )

            backup_path: Path | None = None
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
                occupied = (
                    final_destination.exists()
                    and final_destination.resolve() != op.source.resolve()
                )

                if occupied and op.on_collision == "skip":
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

                if occupied and op.on_collision == "replace":
                    if final_destination.is_dir():
                        raise IsADirectoryError(
                            "Cannot replace an existing directory"
                        )
                    # ADR-0005 WP-A2: persist the displacement intent
                    # (deterministic path) BEFORE the physical move so a
                    # crash in any window leaves a recoverable state.
                    planned_backup = _planned_backup_path(
                        self.journal, op_id, final_destination
                    )
                    _ensure_displace_capacity(
                        planned_backup, op, final_destination
                    )
                    from .identity import capture_identity

                    displaced_identity = capture_identity(final_destination)
                    self.journal.set_displaced(
                        op_id,
                        planned_backup,
                        size=displaced_identity.size if displaced_identity else final_destination.stat().st_size,
                        sha256=displaced_identity.sha256 if displaced_identity else None,
                        mtime_ns=displaced_identity.mtime_ns if displaced_identity else None,
                        device=displaced_identity.device if displaced_identity else None,
                        inode=displaced_identity.inode if displaced_identity else None,
                    )
                    backup_path = _displace(
                        self.journal,
                        op_id,
                        final_destination,
                        planned_backup,
                    )

                if op.on_collision == "append" or backup_path is not None:
                    # R8.2: atomic no-replace publication for each candidate;
                    # no placeholder and no unchecked shutil.move overwrite.
                    final_destination = move_noreplace_unique(
                        op.source, final_destination
                    )
                else:
                    # ADR-0005 invariant 9: never overwrite a concurrent
                    # destination. No-replace move; a racer that created
                    # the destination after our check surfaces here.
                    try:
                        move_noreplace(op.source, final_destination)
                    except DestinationExistsError as exc:
                        raise FileExistsError(
                            "Destination appeared concurrently; nothing "
                            f"was overwritten: {final_destination}"
                            + (
                                f" (previous occupant kept aside at "
                                f"{backup_path})"
                                if backup_path is not None
                                else ""
                            )
                        ) from exc

                move_status = _post_move_status(op, final_destination)
                self.journal.finish_operation(
                    op_id=op_id,
                    status=move_status,
                    destination=final_destination,
                    byte_size=byte_size,
                )

                op.destination = final_destination
                op.status = move_status

            except Exception as exc:
                if (
                    backup_path is not None
                    and backup_path.is_file()
                    and not op.destination.exists()
                ):
                    try:
                        move_noreplace(backup_path, op.destination)
                        self.journal.clear_displaced(op_id)
                    except (OSError, DestinationExistsError):
                        pass
                elif backup_path is not None and not backup_path.is_file():
                    # Displacement intent with no backup: nothing was
                    # displaced — drop the intent (ADR-0005 I4/I5).
                    self.journal.clear_displaced(op_id)
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


def _identity_evidence_matches(
    path: Path, live: Any, recorded_size: Any
) -> str | None:
    """Evidence level for "the row's file is at ``path``", or None.

    Returns ``content`` (E1: recorded hash matches) or ``fs`` (E2:
    recorded dev/ino/size match). Size alone (E3) is insufficient.
    """
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if recorded_size is None or path.stat().st_size != int(recorded_size):
            return None
    except OSError:
        return None
    digest = live["content_sha256"] if "content_sha256" in live.keys() else None
    if digest:
        from .perception.cache import file_content_hash

        try:
            return "content" if file_content_hash(path) == digest else None
        except OSError:
            return None
    from .identity import fs_identity_matches

    src_dev = live["source_dev"] if "source_dev" in live.keys() else None
    src_ino = live["source_ino"] if "source_ino" in live.keys() else None
    if fs_identity_matches(
        path,
        size=int(recorded_size),
        source_dev=src_dev,
        source_ino=src_ino,
    ):
        return "fs"
    return None


def _displaced_evidence_matches(path: Path, live: Any) -> str | None:
    """Evidence that ``path`` is the displaced occupant recorded on the row.

    R8.4: ``displaced_absent`` never proves restoration. Only a content
    hash (E1) or same-file fs identity plus size/mtime (E2) identifies
    the restored occupant. An EXDEV copy changes inode; without a hash it
    deliberately remains unverified rather than closing the undo.
    """
    keys = set(live.keys())
    if "displaced_size" not in keys:
        return None
    size_raw = live["displaced_size"]
    if size_raw is None:
        return None
    try:
        if path.is_symlink() or not path.is_file():
            return None
        st = path.stat()
        if int(st.st_size) != int(size_raw):
            return None
    except OSError:
        return None
    digest = live["displaced_sha256"]
    if digest:
        from .perception.cache import file_content_hash

        try:
            return "content" if file_content_hash(path) == digest else None
        except OSError:
            return None
    dev, ino = live["displaced_dev"], live["displaced_ino"]
    if dev is None or ino is None:
        return None
    if int(st.st_dev) == int(dev) and int(st.st_ino) == int(ino):
        mtime = live["displaced_mtime_ns"]
        if mtime is None or int(st.st_mtime_ns) == int(mtime):
            return "fs"
    return None


def _restore_displaced(
    live: Any,
    current: Path,
    journal: Journal,
    original_op_id: int,
) -> dict[str, Any]:
    """Restore the displaced backup of a replace to its original place.

    Reportable outcomes (never silent):
      - ``no_displaced``      — the operation displaced nothing.
      - ``displaced_restored``— backup moved back; intent cleared.
      - ``displaced_absent``  — recorded backup no longer exists.
      - ``displaced_occupied``— something appeared at the restore path.
      - ``displaced_error``   — the move failed (IO/state), source kept.
    """
    raw = live["displaced_path"] if "displaced_path" in live.keys() else None
    if not raw:
        return {"status": "no_displaced"}
    backup = Path(str(raw))
    try:
        if not backup.is_file():
            # R8.4: the occupant may already be home, but only recorded
            # displaced evidence (not the backup's absence) proves it.
            evidence = _displaced_evidence_matches(current, live)
            if evidence == "content":
                return {
                    "status": "displaced_already_restored",
                    "evidence": evidence,
                }
            return {
                "status": "displaced_absent",
                "detail": (
                    f"recorded backup missing and restored occupant not "
                    f"verified at {current}: {backup}"
                ),
            }
        if _displaced_evidence_matches(backup, live) is None:
            return {
                "status": "displaced_mismatch",
                "detail": f"displaced backup does not match its recorded identity: {backup}",
            }
    except OSError as exc:
        return {
            "status": "displaced_error",
            "detail": f"cannot inspect backup {backup}: {exc}",
        }
    try:
        move_noreplace(backup, current)
    except DestinationExistsError:
        return {
            "status": "displaced_occupied",
            "detail": (
                f"restore path already occupied: {current}; "
                "backup kept aside"
            ),
        }
    except OSError as exc:
        return {
            "status": "displaced_error",
            "detail": f"backup restore failed: {exc}",
        }
    evidence = _displaced_evidence_matches(current, live)
    if evidence is None:
        return {
            "status": "displaced_error",
            "detail": "restored occupant failed identity verification",
        }
    journal.clear_displaced(original_op_id)
    return {"status": "displaced_restored", "evidence": evidence}


def undo_operations(
    journal: Journal,
    rows: Iterable[Any],
    dry_run: bool = True,
    cancel=None,
) -> list[dict[str, Any]]:
    """
    Undo previous moves using the journal (recoverable saga, ADR-0005).

    Safety rules:
      - Never overwrite an unexpected file at the original path
        (no-replace move; a concurrent occupant falls through to
        append_unique and the result reports the conflict).
      - If the moved file is missing, report missing (do not invent data).
      - If size or hash recorded in journal does not match, refuse
        (state drift).
      - Replace displacements: the displaced backup is restored BEFORE
        the original row leaves ``undone``-eligibility. Restore failure
        yields ``undo_partial`` + explicit report, never a silent skip.
      - ``undo_partial`` rows resume: only the outstanding restore runs.
      - Double-undo is a no-op for already-undone rows (they leave
        last_successful_moves).
      - ``cancel`` is checked between rows, not during a move.
    """

    from .cancel import CancelledError

    results: list[dict[str, Any]] = []
    batch_id = uuid.uuid4().hex

    for row in rows:
        if cancel is not None and cancel.is_cancelled():
            raise CancelledError("Undo cancelled by user")
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

        # ADR-0005 undo_partial: the reverse move (A) already succeeded;
        # only the displaced backup restore (B) is outstanding. Re-running
        # undo completes the restore; it must not repeat the reverse move.
        if status == "undo_partial":
            if dry_run:
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "dry-run",
                        "source": current,
                        "destination": original,
                        "pending_restore": True,
                    }
                )
                continue
            restore = _restore_displaced(live, current, journal, original_op_id)
            if restore["status"] in {
                "displaced_restored",
                "displaced_already_restored",
            } and _identity_evidence_matches(original, live, recorded_size) is not None:
                journal.clear_displaced(original_op_id)
                journal.mark_undone(original_op_id)
            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": restore["status"],
                    "source": current,
                    "destination": original,
                    "detail": restore.get("detail"),
                }
            )
            continue

        if status not in {"done", "needs_verify"}:
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
            # Crash window (ADR-0005 I3/I10): the reverse move landed but
            # the journal update was lost — the file is back at the
            # original path. Claim it only with verified identity
            # evidence (E1 hash or E2 dev/ino/size); size alone never
            # qualifies.
            evidence = _identity_evidence_matches(original, live, recorded_size)
            if evidence is not None:
                restore = _restore_displaced(
                    live, current, journal, original_op_id
                )
                if restore["status"] in {"no_displaced", "displaced_restored"}:
                    journal.mark_undone(original_op_id)
                else:
                    journal.mark_undo_partial(original_op_id)
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "already_restored",
                        "source": current,
                        "destination": original,
                        "evidence": evidence,
                        "displaced": restore["status"],
                        "detail": restore.get("detail"),
                    }
                )
                continue
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

        # R8.4 U-D: converge only when BOTH effects have evidence. The
        # displaced occupant must match its persisted identity (never
        # inferred from backup absence) and the moved file must be home.
        displaced_raw = (
            live["displaced_path"] if "displaced_path" in live.keys() else None
        )
        if displaced_raw:
            home_evidence = _identity_evidence_matches(
                original, live, recorded_size
            )
            occupant_evidence = _displaced_evidence_matches(current, live)
            if (
                not Path(str(displaced_raw)).is_file()
                and home_evidence is not None
                and occupant_evidence == "content"
            ):
                journal.clear_displaced(original_op_id)
                journal.mark_undone(original_op_id)
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "already_restored",
                        "source": current,
                        "destination": original,
                        "evidence": home_evidence,
                        "displaced": "displaced_already_restored",
                        "displaced_evidence": occupant_evidence,
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

        digest = live["content_sha256"] if "content_sha256" in live.keys() else None
        if digest:
            from .perception.cache import file_content_hash

            try:
                actual_hash = file_content_hash(current)
            except OSError as exc:
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "state_mismatch",
                        "source": current,
                        "destination": original,
                        "error": f"Cannot hash journal destination: {exc}",
                    }
                )
                continue
            if actual_hash != digest:
                results.append(
                    {
                        "operation_id": original_op_id,
                        "rule_id": rule_id,
                        "status": "state_mismatch",
                        "source": current,
                        "destination": original,
                        "error": (
                            "Content hash mismatch at destination; "
                            "file may have been modified; refusing undo"
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

        # A-01: the undo row carries the identity of the file that is
        # actually being moved back (captured now, before the reverse
        # move), so reconcile_pending can verify it after a crash. A
        # historical hash of different bytes is never reused here.
        from .identity import capture_identity

        undo_identity = capture_identity(current)
        undo_op_id = journal.start_operation(
            batch_id=batch_id,
            rule_id=rule_id,
            rule_name=f"Undo · {live_name or rule_id}",
            op="undo",
            source=current,
            destination=original,
            byte_size=(
                undo_identity.size if undo_identity else recorded_size
            ),
            content_sha256=(
                undo_identity.sha256 if undo_identity else None
            ),
            source_mtime_ns=(
                undo_identity.mtime_ns if undo_identity else None
            ),
            source_dev=(undo_identity.device if undo_identity else None),
            source_ino=(undo_identity.inode if undo_identity else None),
            original_operation_id=original_op_id,
        )

        try:
            original.parent.mkdir(parents=True, exist_ok=True)

            final_destination = original
            conflict = False

            # ADR-0005 invariant 9: the reverse move never overwrites a
            # file that appeared at the original path. A concurrent
            # occupant falls through to append_unique (conflict).
            try:
                move_noreplace(current, original)
            except DestinationExistsError:
                final_destination = move_noreplace_unique(current, original)
                conflict = True

            undo_status = _status_from_identity(
                final_destination,
                size=undo_identity.size if undo_identity else recorded_size,
                sha256=undo_identity.sha256 if undo_identity else None,
                device=undo_identity.device if undo_identity else None,
                inode=undo_identity.inode if undo_identity else None,
            )
            journal.finish_operation(
                op_id=undo_op_id,
                status=undo_status,
                destination=final_destination,
            )

            # ADR-0005 WP-A3: the displaced backup restore (B) is a
            # separate effect. It is attempted BEFORE the final status so
            # the original operation never reads `undone` while its
            # restore is still outstanding. Success → undone; failure →
            # undo_partial (retryable), never a silent skip.
            displaced = (
                live["displaced_path"]
                if "displaced_path" in live.keys()
                else None
            )
            restore = {"status": "no_displaced"}
            if displaced:
                restore = _restore_displaced(
                    live, current, journal, original_op_id
                )

            if restore["status"] in {
                "no_displaced",
                "displaced_restored",
            }:
                journal.mark_undone(original_op_id)
                final_status = (
                    "needs_verify"
                    if undo_status != "done"
                    else ("done_with_conflict" if conflict else "done")
                )
            else:
                # displaced_error (occupied/IO) or displaced_absent:
                # the undo is NOT complete (invariant 6) — the row
                # stays visible and non-purgeable as undo_partial.
                journal.mark_undo_partial(original_op_id)
                final_status = "undo_partial"

            results.append(
                {
                    "operation_id": original_op_id,
                    "rule_id": rule_id,
                    "status": final_status,
                    "source": current,
                    "destination": final_destination,
                    "conflict": conflict,
                    "displaced": restore["status"],
                    "detail": restore.get("detail"),
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
