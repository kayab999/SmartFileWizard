"""MCP tool payload builders (pure functions, no SDK dependency).

These are plain functions so tests can exercise the payloads without starting
stdio or importing the optional `mcp` SDK.  The MCP layer only wraps them.

WP-0.7.2 scope: read-only tools only. None of these mutate the filesystem
(core helpers that would mkdir state paths are guarded first).
"""

import logging
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

from filewizard import __version__

from ..executor import Executor, PlannedOperation, undo_operations
from ..facts import FeatureExtractor, collect_facts
from ..journal import Journal
from ..perception.inject import AgentFeaturesError, AgentFeaturesExtractor
from ..perception.inject import normalize_agent_features
from ..pipeline import load_ruleset, plan_operations
from ..presets import default_state_dir as presets_default_state_dir
from ..presets import ensure_builtin_presets, load_preset

logger = logging.getLogger(__name__)


def filewizard_version() -> dict:
    """Return the tool's response payload for `filewizard_version`."""
    return {
        "ok": True,
        "tool": "filewizard_version",
        "version": __version__,
    }


def ping() -> dict:
    """Return the tool's response payload for `ping` (liveness)."""
    return {"ok": True, "tool": "ping", "pong": "pong"}


def result_error(tool: str, error: str) -> dict:
    """Uniform `{ok:false, error:…}` payload for structured errors."""
    return {"ok": False, "tool": tool, "error": error}


def _state_root(state_dir: Path | str | None) -> Path:
    return Path(state_dir or presets_default_state_dir()).expanduser()


class McpJailError(Exception):
    """mcp.yaml exists but cannot be read as a jail config (fail closed)."""


def mcp_jail_config_dir() -> Path:
    """Canonical jail policy directory.

    Tool-call ``state_dir`` must not choose this path: otherwise an agent
    pointing journal/presets at ``/tmp`` silently skips the user's mcp.yaml.
    """
    return presets_default_state_dir()


def mcp_allowed_roots(state_dir: Path | str | None = None) -> list[Path]:
    """Opt-in jail for MCP mutate tools (H8, WP-0.9.5).

    Order (first non-empty wins, no merge):
      1. env FILEWIZARD_SOURCE_ROOT (one path, or os.pathsep-separated)
      2. <yaml_root>/mcp.yaml ``allowed_roots`` or ``mcp.allowed_roots``
      3. [] → no jail (same power as CLI)

    ``state_dir`` selects yaml_root only when this function is called
    directly (tests). Plan/execute/apply_labels use ``mcp_jail_config_dir()``.

    If mcp.yaml exists but is unreadable, raises ``McpJailError`` (not []).
    """
    raw_paths: list[str] = []
    env = os.environ.get("FILEWIZARD_SOURCE_ROOT", "").strip()
    if env:
        raw_paths = [p.strip() for p in env.split(os.pathsep) if p.strip()]
    else:
        yaml_root = _state_root(state_dir)
        cfg_path = yaml_root / "mcp.yaml"
        if cfg_path.is_file():
            try:
                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                logger.warning("mcp.yaml unreadable at %s: %s", cfg_path, exc)
                raise McpJailError(
                    f"mcp.yaml unreadable ({cfg_path}): {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise McpJailError(f"mcp.yaml must be a mapping: {cfg_path}")
            items: Any = raw.get("allowed_roots", [])
            if not items and isinstance(raw.get("mcp"), dict):
                items = raw["mcp"].get("allowed_roots", [])
            raw_paths = [str(e).strip() for e in (items or []) if str(e).strip()]
    seen: set[str] = set()
    out: list[Path] = []
    for part in raw_paths:
        try:
            resolved = Path(part).expanduser().resolve()
        except OSError:
            continue
        if str(resolved) not in seen:
            seen.add(str(resolved))
            out.append(resolved)
    return out


def _path_within(path: Path, roots: list[Path]) -> bool:
    if not roots:
        return True
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _check_source_root(tool: str, src: Path, roots: list[Path]) -> dict | None:
    if roots and not _path_within(src, roots):
        return result_error(tool, "source outside allowed_roots")
    return None


def _apply_destination_jail(
    operations: list[PlannedOperation], roots: list[Path]
) -> None:
    """Mark out-of-jail destinations as errors (in place).

    Plan: agent sees the op as failed. Execute: Executor skips non-planned
    ops, so marked ops never move. Only applies when roots are configured.
    """
    if not roots:
        return
    for op in operations:
        if op.destination is None or op.status == "error":
            continue
        try:
            dest = op.destination.expanduser().resolve()
        except OSError:
            continue
        if not _path_within(dest, roots):
            op.status = "error"
            op.error = "destination outside allowed_roots"


def filewizard_list_presets(state_dir: Path | str | None = None) -> dict:
    """Read-only: list presets from the presets library (absolute paths)."""
    from ..presets import list_presets

    root = _state_root(state_dir) / "presets"
    try:
        if not root.is_dir():
            items = []
        else:
            items = list_presets(state_dir)
    except Exception as exc:
        return result_error("filewizard_list_presets", str(exc))

    return {
        "ok": True,
        "tool": "filewizard_list_presets",
        "presets": [
            {
                "name": item.name,
                "path": str(item.path.expanduser().resolve()),
                "rule_count": item.rule_count,
                "description": item.description,
            }
            for item in items
        ],
    }


def filewizard_journal_batches(
    state_dir: Path | str | None = None,
    limit: int = 20,
) -> dict:
    """Read-only: aggregate journal operations into batches.

    Guarded so an absent journal DB is reported as empty without creating it.
    """
    root = _state_root(state_dir).resolve()
    db_path = root / "journal.db"

    try:
        if not db_path.is_file():
            return {
                "ok": True,
                "tool": "filewizard_journal_batches",
                "journal_path": str(db_path),
                "batches": [],
            }
        with Journal(db_path) as journal:
            rows = journal.recent_batches(limit=int(limit))
    except Exception as exc:
        return result_error("filewizard_journal_batches", str(exc))

    batches = []
    for row in rows:
        rule_names = (row["rule_names"] or "").split(",")
        ops = (row["ops"] or "").split(",")
        batches.append(
            {
                "batch_id": row["batch_id"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "rule_names": [s for s in rule_names if s],
                "ops": [s for s in ops if s],
                "counts": {
                    "done": row["done"] or 0,
                    "failed": row["failed"] or 0,
                    "skipped": row["skipped"] or 0,
                    "undone": row["undone"] or 0,
                    "errors": row["errors"] or 0,
                },
                "total": row["total"] or 0,
                "last_id": row["last_id"],
            }
        )

    return {
        "ok": True,
        "tool": "filewizard_journal_batches",
        "journal_path": str(db_path),
        "batches": batches,
    }


def filewizard_collect_facts(
    path: Path | str,
    extractors: Iterable[FeatureExtractor] = (),
) -> dict:
    """Read-only: collect facts (metadata + optional extractors) for one file.

    Returns the resolved absolute path in the payload.
    Honors the MCP jail (C3): outside allowed_roots → structured error.
    """
    try:
        target = Path(path).expanduser().resolve()
        try:
            roots = mcp_allowed_roots(mcp_jail_config_dir())
        except McpJailError as exc:
            return result_error("filewizard_collect_facts", str(exc))
        blocked = _check_source_root("filewizard_collect_facts", target, roots)
        if blocked is not None:
            return blocked
        if not target.is_file():
            return result_error("filewizard_collect_facts", f"Not a file: {path}")
        facts = collect_facts(target, extractors)
    except Exception as exc:
        return result_error("filewizard_collect_facts", str(exc))

    return {
        "ok": True,
        "tool": "filewizard_collect_facts",
        "facts": {
            "path": str(facts.path),
            "size": facts.size,
            "mime": facts.mime,
            "extension": facts.extension,
            "filename": facts.filename,
            "stem": facts.stem,
            "mtime": facts.mtime.isoformat(),
            "is_image": facts.is_image,
            "width": facts.width,
            "height": facts.height,
            "features": facts.features,
        },
    }


_PAYLOADS: dict[str, Any] = {
    "filewizard_version": filewizard_version,
    "ping": ping,
    "filewizard_list_presets": filewizard_list_presets,
    "filewizard_journal_batches": filewizard_journal_batches,
    "filewizard_collect_facts": filewizard_collect_facts,
}


# ---------------------------------------------------------------------------
# WP-0.7.3: mutation tools (dry-run default; execute/undo need confirm=true)
# ---------------------------------------------------------------------------


def _resolve_ruleset(
    preset: str | None,
    rules: str | None,
    state_dir: Path,
):
    """Exactly one of preset|rules (mirrors CLI run contract)."""
    if bool(preset) == bool(rules):
        raise ValueError("Specify exactly one of 'preset' or 'rules'.")
    if preset:
        return load_preset(str(preset), state_dir)
    return load_ruleset(Path(str(rules)).expanduser())


# I1 (0.10.1): upper bound so one agent call cannot scan the whole disk
# into a giant JSON payload (scan + HTTP perception + response size).
MCP_LIMIT_MAX = 1000


def _coerce_limit(limit: Any, default: int = 100) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    if value < 1:
        value = default
    return min(value, MCP_LIMIT_MAX)


def _op_to_dict(op: PlannedOperation) -> dict:
    return {
        "source": str(op.source),
        "destination": str(op.destination) if op.destination else None,
        "rule_id": op.rule_id,
        "rule_name": op.rule_name,
        "status": op.status,
        "error": op.error,
        "explanations": list(op.explanations),
        "conditions": [
            {"key": c.key, "passed": c.passed, "detail": c.detail}
            for c in op.conditions
        ],
        # Compact journal-safe evidence (may be None without perception).
        "perception": op.perception,
    }


def _undo_result_to_dict(result: dict) -> dict:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in result.items()
    }


def _plan_extractors(
    state: Path,
    *,
    perception_profile: str | None = None,
    enable_ocr: bool = False,
    enable_vision: bool = False,
    agent_features: Path | dict[str, dict] | None = None,
):
    """Same perception stack as CLI (WP-0.8.1 / F1)."""
    from ..pipeline import default_extractors

    return default_extractors(
        ocr=enable_ocr,
        vision=enable_vision,
        profile=perception_profile,
        state_dir=state,
        agent_features=agent_features,
    )


def _remote_warnings(
    state: Path, perception_profile: str | None
) -> list[str]:
    """I9: non-loopback OCR/VLM endpoints as structured warnings (MCP)."""
    from ..perception.config import config_from_profile, load_perception_config
    from ..perception.http_openai import remote_perception_endpoints

    try:
        cfg = (
            config_from_profile(perception_profile)
            if perception_profile
            else load_perception_config(state_dir=state)
        )
    except Exception:
        return []
    return [
        f"images will be sent (base64) outside this machine: {ep}"
        for ep in remote_perception_endpoints(cfg)
    ]


def filewizard_plan(
    source: Path | str,
    state_dir: Path | str | None = None,
    preset: str | None = None,
    rules: Path | str | None = None,
    limit: int = 100,
    perception_profile: str | None = None,
    enable_ocr: bool = False,
    enable_vision: bool = False,
    agent_features: Path | dict[str, dict] | None = None,
) -> dict:
    """Dry-run only: build a plan; never moves files.

    Journal writes go to an in-memory DB (no journal.db side effect).
    Like CLI run, missing builtin presets are seeded (I1, ADR-0004).
    Perception follows state_dir/perception.yaml (or profile), not empty extractors.
    """
    try:
        src = Path(source).expanduser().resolve()
        state = _state_root(state_dir).resolve()
        ensure_builtin_presets(state)  # same seeding as CLI run
        try:
            roots = mcp_allowed_roots(mcp_jail_config_dir())
        except McpJailError as exc:
            return result_error("filewizard_plan", str(exc))
        blocked = _check_source_root("filewizard_plan", src, roots)
        if blocked is not None:
            return blocked
        ruleset = _resolve_ruleset(preset, rules, state)
        lim = _coerce_limit(limit)
        extractors = _plan_extractors(
            state,
            perception_profile=perception_profile,
            enable_ocr=enable_ocr,
            enable_vision=enable_vision,
            agent_features=agent_features,
        )

        with Journal(Path(":memory:")) as journal:  # plan writes nothing
            executor = Executor(journal=journal, dry_run=True)
            operations, scanned = plan_operations(
                source=src,
                rules=ruleset,
                executor=executor,
                extractors=extractors,
                limit=lim,
            )
        _apply_destination_jail(operations, roots)
    except Exception as exc:
        return result_error("filewizard_plan", str(exc))

    return {
        "ok": True,
        "tool": "filewizard_plan",
        "source": str(src),
        "preset": preset,
        "rules": str(rules) if rules else None,
        "limit": lim,
        "perception_profile": perception_profile,
        "scanned": scanned,
        "warnings": _remote_warnings(state, perception_profile),
        "operations": [_op_to_dict(op) for op in operations],
    }


def filewizard_execute(
    source: Path | str,
    state_dir: Path | str | None = None,
    preset: str | None = None,
    rules: Path | str | None = None,
    limit: int = 100,
    confirm: bool = False,
    perception_profile: str | None = None,
    enable_ocr: bool = False,
    enable_vision: bool = False,
    agent_features: Path | dict[str, dict] | None = None,
) -> dict:
    """Execute a plan. Requires confirm=True; otherwise a structured error.

    Reuses Executor + Journal (same journal as CLI). Returns batch_id for undo.
    """
    if confirm is not True:
        return result_error(
            "filewizard_execute",
            "Execution requires explicit confirm=True to mutate files.",
        )

    try:
        src = Path(source).expanduser().resolve()
        state = _state_root(state_dir).resolve()
        ensure_builtin_presets(state)  # same seeding as CLI run
        try:
            roots = mcp_allowed_roots(mcp_jail_config_dir())
        except McpJailError as exc:
            return result_error("filewizard_execute", str(exc))
        blocked = _check_source_root("filewizard_execute", src, roots)
        if blocked is not None:
            return blocked
        db = state / "journal.db"
        ruleset = _resolve_ruleset(preset, rules, state)
        lim = _coerce_limit(limit)
        extractors = _plan_extractors(
            state,
            perception_profile=perception_profile,
            enable_ocr=enable_ocr,
            enable_vision=enable_vision,
            agent_features=agent_features,
        )

        with Journal(db) as journal:
            executor = Executor(journal=journal, dry_run=False)
            operations, scanned = plan_operations(
                source=src,
                rules=ruleset,
                executor=executor,
                extractors=extractors,
                limit=lim,
            )
            # Jail destinations before any move; marked ops are skipped.
            _apply_destination_jail(operations, roots)
            results = executor.execute(operations)
            latest = journal.recent_batches(limit=1)
            batch_id = latest[0]["batch_id"] if latest else None
    except Exception as exc:
        return result_error("filewizard_execute", str(exc))

    summary: dict[str, int] = {}
    for op in results:
        summary[op.status] = summary.get(op.status, 0) + 1

    return {
        "ok": True,
        "tool": "filewizard_execute",
        "source": str(src),
        "preset": preset,
        "rules": str(rules) if rules else None,
        "limit": lim,
        "scanned": scanned,
        "batch_id": batch_id,
        "journal_path": str(db),
        "summary": summary,
        "warnings": _remote_warnings(state, perception_profile),
        "operations": [_op_to_dict(op) for op in results],
    }


def filewizard_undo_batch(
    batch_id: str | None,
    state_dir: Path | str | None = None,
    confirm: bool = False,
) -> dict:
    """Undo a journal batch. Dry-run by default; apply only with confirm=True.

    Same strict gate as execute: only the boolean True mutates (not "true"/1).
    Honors the MCP jail (C3): batches touching paths outside allowed_roots
    are refused before any move, including dry-run (fail-closed, no oracle).
    """
    if not batch_id:
        return result_error("filewizard_undo_batch", "batch_id is required.")

    # Strict identity check — mirrors filewizard_execute (I1 / ADR-0004).
    apply = confirm is True

    try:
        state = _state_root(state_dir).resolve()
        db = state / "journal.db"
        if not db.is_file():
            return result_error("filewizard_undo_batch", f"Journal not found: {db}")
        try:
            roots = mcp_allowed_roots(mcp_jail_config_dir())
        except McpJailError as exc:
            return result_error("filewizard_undo_batch", str(exc))

        with Journal(db) as journal:
            rows = journal.done_moves_for_batch(batch_id)
            if roots:
                for row in rows:
                    for key in ("source", "destination"):
                        value = row[key] if key in row.keys() else None
                        if value and not _path_within(Path(str(value)), roots):
                            return result_error(
                                "filewizard_undo_batch",
                                "batch touches paths outside allowed_roots",
                            )
            results = undo_operations(
                journal=journal,
                rows=rows,
                dry_run=not apply,
            )
    except Exception as exc:
        return result_error("filewizard_undo_batch", str(exc))

    return {
        "ok": True,
        "tool": "filewizard_undo_batch",
        "batch_id": batch_id,
        "journal_path": str(db),
        "dry_run": not apply,
        "results": [_undo_result_to_dict(r) for r in results],
    }


def filewizard_apply_agent_labels(
    labels: dict[str, dict],
    source: Path | str | None = None,
    state_dir: Path | str | None = None,
    preset: str | None = None,
    rules: Path | str | None = None,
    limit: int = 100,
) -> dict:
    """Apply agent labels (feature dict per absolute path) to a dry-run plan.

    Labels re-use the WP-0.5.3 cascade feature shape via perception/inject.
    This tool never mutates the filesystem: it normalizes the mapping in
    memory and (optionally) runs a dry-run plan using the agent extractor.
    """
    try:
        mapping = normalize_agent_features(labels)
    except AgentFeaturesError as exc:
        return result_error("filewizard_apply_agent_labels", str(exc))

    plan: dict | None = None
    if source is not None:
        try:
            src = Path(source).expanduser().resolve()
            state = _state_root(state_dir).resolve()
            ensure_builtin_presets(state)  # same seeding as CLI run
            try:
                roots = mcp_allowed_roots(mcp_jail_config_dir())
            except McpJailError as exc:
                return result_error("filewizard_apply_agent_labels", str(exc))
            blocked = _check_source_root(
                "filewizard_apply_agent_labels", src, roots
            )
            if blocked is not None:
                return blocked
            ruleset = _resolve_ruleset(preset, rules, state)
            lim = _coerce_limit(limit)

            with Journal(Path(":memory:")) as journal:
                executor = Executor(journal=journal, dry_run=True)
                operations, scanned = plan_operations(
                    source=src,
                    rules=ruleset,
                    executor=executor,
                    extractors=(AgentFeaturesExtractor(mapping),),
                    limit=lim,
                )
            _apply_destination_jail(operations, roots)
        except Exception as exc:
            return result_error("filewizard_apply_agent_labels", str(exc))

        plan = {
            "source": str(src),
            "scanned": scanned,
            "limit": lim,
            "operations": [_op_to_dict(op) for op in operations],
        }

    return {
        "ok": True,
        "tool": "filewizard_apply_agent_labels",
        "label_count": len(mapping),
        "labels": mapping,
        "plan": plan,
    }


_PAYLOADS.update(
    {
        "filewizard_plan": filewizard_plan,
        "filewizard_execute": filewizard_execute,
        "filewizard_undo_batch": filewizard_undo_batch,
        "filewizard_apply_agent_labels": filewizard_apply_agent_labels,
    }
)