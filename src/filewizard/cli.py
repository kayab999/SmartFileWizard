from __future__ import annotations

import logging
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path

import click

from .executor import Executor, PlannedOperation, undo_operations
from .journal import Journal
from .pipeline import RulesLoadError, default_extractors, load_ruleset, plan_operations
from .presets import (
    PresetError,
    delete_preset,
    ensure_builtin_presets,
    import_rules_file,
    list_presets,
    load_preset,
    presets_dir,
)
from .perception.catalog import list_known_models
from .perception.config import (
    PROFILES,
    config_from_profile,
    load_perception_config,
    save_perception_config,
)
from .perception.factory import build_extractors, perception_status
from . import __version__
from .watch import WatchConfig, WatchError, WatcherLockError, watch_once


def load_rules(path: Path):
    try:
        return load_ruleset(path)
    except RulesLoadError as exc:
        raise click.ClickException(str(exc)) from exc


def warn_remote_perception(profile: str | None, state_dir: Path) -> None:
    """I9: warn when configured OCR/VLM endpoints are not loopback."""
    from .perception.http_openai import remote_perception_endpoints

    try:
        cfg = (
            config_from_profile(profile)
            if profile
            else load_perception_config(state_dir=state_dir)
        )
    except Exception:
        return
    for endpoint in remote_perception_endpoints(cfg):
        click.echo(
            "warning: images will be sent (base64) outside this machine: "
            f"{endpoint}",
            err=True,
        )


def warn_pending_journal(journal: Journal) -> None:
    """H14 (0.9.5): surface interrupted batches; GUI already warns (R4)."""
    try:
        pending = journal.pending_operations()
    except Exception:
        return
    if pending:
        click.echo(
            f"warning: journal has {len(pending)} 'pending' operation(s) "
            f"from an interrupted run; review history before executing.",
            err=True,
        )


def echo_operation(op: PlannedOperation, verbose: bool) -> None:
    destination = str(op.destination) if op.destination else "-"

    click.echo(
        f"[{op.status.upper():8}] {op.rule_id}: {op.source} -> {destination}"
    )

    if op.error:
        click.echo(f"           error: {op.error}")

    if verbose:
        if op.conditions:
            for check in op.conditions:
                mark = "✓" if check.passed else "✗"
                click.echo(f"           {mark} [{check.key}] {check.detail}")
        else:
            for explanation in op.explanations:
                click.echo(f"           - {explanation}")


@click.group()
@click.version_option(version=__version__, prog_name="filewizard")
def cli() -> None:
    """
    FileWizard: rule-based file classification and organization engine.
    """


@cli.command("run")
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory to scan.",
)
@click.option(
    "--rules",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML rules file.",
)
@click.option(
    "--preset",
    "preset_name",
    type=str,
    default=None,
    help="Named preset from ~/.local/share/filewizard/presets/.",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Apply changes. Without this flag, only dry-run.",
)
@click.option(
    "--ocr",
    is_flag=True,
    default=False,
    help="Enable OCR (tesseract if no llama_http in config).",
)
@click.option(
    "--vision",
    is_flag=True,
    default=False,
    help="Enable vision provider from perception config.",
)
@click.option(
    "--perception-profile",
    type=click.Choice(sorted(PROFILES.keys())),
    default=None,
    help="Built-in perception profile (lite|recommended|ocr_only|vision_only).",
)
@click.option(
    "--agent-features",
    "agent_features",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "JSON file with precomputed agent evidence "
        "(absolute path -> vision/ocr/cascade features)."
    ),
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Limit number of files scanned.",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Show detailed match explanations.",
)
def run(
    source: Path,
    rules: Path | None,
    preset_name: str | None,
    execute: bool,
    ocr: bool,
    vision: bool,
    perception_profile: str | None,
    agent_features: Path | None,
    limit: int | None,
    state_dir: Path,
    yes: bool,
    verbose: bool,
) -> None:
    """Scan a directory and apply organization rules."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    if bool(rules) == bool(preset_name):
        raise click.ClickException(
            "Specify exactly one of --rules PATH or --preset NAME."
        )

    source = source.expanduser().resolve()
    state_dir = state_dir.expanduser().resolve()
    ensure_builtin_presets(state_dir)
    warn_remote_perception(perception_profile, state_dir)

    try:
        if preset_name:
            ruleset = load_preset(preset_name, state_dir)
        else:
            ruleset = load_rules(rules)  # type: ignore[arg-type]
    except (RulesLoadError, PresetError) as exc:
        raise click.ClickException(str(exc)) from exc

    agent_mapping = None
    if agent_features is not None:
        from .perception.inject import AgentFeaturesError, load_agent_features

        try:
            agent_mapping = load_agent_features(agent_features)
        except AgentFeaturesError as exc:
            raise click.ClickException(str(exc)) from exc

    extractors = default_extractors(
        ocr=ocr,
        vision=vision,
        profile=perception_profile,
        state_dir=state_dir,
        agent_features=agent_mapping,
    )

    def _on_fact_error(path: Path, exc: Exception) -> None:
        click.echo(
            f"warning: cannot collect facts for {path}: {exc}",
            err=True,
        )

    with Journal(state_dir / "journal.db") as journal:
        warn_pending_journal(journal)
        executor = Executor(
            journal=journal,
            dry_run=not execute,
        )

        operations, scanned = plan_operations(
            source=source,
            rules=ruleset,
            executor=executor,
            extractors=extractors,
            limit=limit,
            on_fact_error=_on_fact_error,
        )

        click.echo(f"Scanned files: {scanned}")
        click.echo(f"Planned operations: {len(operations)}")
        click.echo("")

        for op in operations:
            echo_operation(op, verbose=verbose)

        if not execute:
            click.echo("")
            click.echo("Dry run only. Re-run with --execute to apply changes.")
            return

        if not operations:
            click.echo("Nothing to do.")
            return

        if not yes:
            click.confirm(
                f"Execute {len(operations)} operations?",
                abort=True,
            )

        results = executor.execute(operations)

        counts = Counter(op.status for op in results)

        click.echo("")
        click.echo("Execution summary:")

        for status, count in counts.items():
            click.echo(f"  {status}: {count}")

        click.echo("")
        click.echo("Done. Use `filewizard undo` to revert executed moves.")


@cli.command("undo")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    help="Maximum number of operations to undo.",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Apply undo. Without this flag, only show what would be undone.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
def undo(
    state_dir: Path,
    limit: int,
    execute: bool,
    yes: bool,
) -> None:
    """Undo moves recorded in the journal."""

    state_dir = state_dir.expanduser().resolve()

    with Journal(state_dir / "journal.db") as journal:
        warn_pending_journal(journal)
        rows = journal.last_successful_moves(limit=limit)

        if not rows:
            click.echo("No completed move operations found.")
            return

        click.echo(f"Found {len(rows)} completed move operations.")

        for row in rows:
            click.echo(
                f"[{row['id']}] {row['source']} -> {row['destination']}"
            )

        if not execute:
            click.echo("")
            click.echo("Dry undo only. Re-run with --execute to revert changes.")
            return

        if not yes:
            click.confirm(
                f"Undo {len(rows)} operations?",
                abort=True,
            )

        results = undo_operations(
            journal=journal,
            rows=rows,
            dry_run=False,
        )

        counts = Counter(result["status"] for result in results)

        click.echo("")
        click.echo("Undo summary:")

        for status, count in counts.items():
            click.echo(f"  {status}: {count}")


@cli.command("purge")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option(
    "--older-than-days",
    type=int,
    default=90,
    show_default=True,
    help="Delete purgeable rows older than N days.",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Apply purge. Without this flag, only show what would be deleted.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
def purge(
    state_dir: Path,
    older_than_days: int,
    execute: bool,
    yes: bool,
) -> None:
    """Delete old journal rows that can never back an undo.

    Only failed/skipped/error/interrupted/undone rows older than the cutoff
    are removed. Done moves (undo evidence) and pending rows are kept.
    """

    state_dir = state_dir.expanduser().resolve()

    with Journal(state_dir / "journal.db") as journal:
        warn_pending_journal(journal)
        if older_than_days < 0:
            raise click.ClickException("--older-than-days must be >= 0.")
        preview = journal.count_purgeable(older_than_days=older_than_days)
        click.echo(
            f"Purgeable rows: {preview} "
            f"(failed/skipped/error/interrupted/undone older than "
            f"{older_than_days} days; done/pending kept)."
        )

        if not execute:
            click.echo("")
            click.echo("Dry purge only. Re-run with --execute to delete.")
            return

        if not yes:
            click.confirm(
                f"Purge journal rows older than {older_than_days} days?",
                abort=True,
            )

        removed = journal.purge(older_than_days=older_than_days)
        click.echo(f"Purged {removed} journal rows.")


def _run_watch_loop(
    *,
    source: Path,
    rules: Path | None,
    preset_name: str | None,
    interval: float,
    execute: bool,
    perception_profile: str | None,
    agent_features: Path | None,
    limit: int | None,
    state_dir: Path,
    verbose: bool,
) -> None:
    """Poll `source` every `interval` seconds; debounce by signature."""
    from .watch import watch_loop

    cfg = WatchConfig(
        source=source.expanduser().resolve(),
        preset=preset_name,
        rules=rules.expanduser() if rules else None,
        dry_run=not execute,
        state_dir=state_dir.expanduser().resolve(),
        limit=limit,
        profile=perception_profile,
        agent_features=agent_features,
    )

    def _on_tick(
        tick: int, ops: list, changed: int
    ) -> None:
        click.echo(f"[watch] tick {tick}: {changed} file(s) changed, "
                   f"{len(ops)} planned")
        for op in ops:
            echo_operation(op, verbose=verbose)

    try:
        click.echo(
            f"[watch] polling {cfg.source} every {interval}s "
            f"({'dry-run' if not execute else 'execute'}) — Ctrl-C to stop"
        )
        watch_loop(cfg, interval=interval, on_tick=_on_tick)
    except KeyboardInterrupt:
        click.echo("")
        click.echo("[watch] stopped by Ctrl-C.")
    except WatcherLockError as exc:
        raise click.ClickException(str(exc)) from exc
    except WatchError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.group("watch")
def watch_cmd() -> None:
    """Watch folders: single tick, polling loop, or active watches."""


@watch_cmd.command("once")
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory to scan.",
)
@click.option(
    "--rules",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML rules file.",
)
@click.option(
    "--preset",
    "preset_name",
    type=str,
    default=None,
    help="Named preset from ~/.local/share/filewizard/presets/.",
)
@click.option(
    "--once",
    is_flag=True,
    default=False,
    help="Run a single tick (default).",
)
@click.option(
    "--interval",
    "interval_seconds",
    type=float,
    default=None,
    help="Poll every N seconds instead of running a single tick.",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Apply changes. Without this flag, only dry-run.",
)
@click.option(
    "--perception-profile",
    type=click.Choice(sorted(PROFILES.keys())),
    default=None,
    help="Built-in perception profile (lite|recommended|ocr_only|vision_only).",
)
@click.option(
    "--agent-features",
    "agent_features",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="JSON file with precomputed agent evidence (path -> features).",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Limit number of files scanned.",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Show detailed match explanations.",
)
def watch_once_cmd(
    source: Path,
    rules: Path | None,
    preset_name: str | None,
    once: bool,
    execute: bool,
    perception_profile: str | None,
    agent_features: Path | None,
    limit: int | None,
    state_dir: Path,
    yes: bool,
    verbose: bool,
    interval_seconds: float | None,
) -> None:
    """Run rules on a folder once (or poll with --interval)."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    if interval_seconds is not None:
        _run_watch_loop(
            source=source,
            rules=rules,
            preset_name=preset_name,
            interval=interval_seconds,
            execute=execute,
            perception_profile=perception_profile,
            agent_features=agent_features,
            limit=limit,
            state_dir=state_dir,
            verbose=verbose,
        )
        return

    def _cfg(dry: bool) -> WatchConfig:
        return WatchConfig(
            source=source.expanduser().resolve(),
            preset=preset_name,
            rules=rules.expanduser() if rules else None,
            dry_run=dry,
            state_dir=state_dir.expanduser().resolve(),
            limit=limit,
            profile=perception_profile,
            agent_features=agent_features,
        )

    warn_remote_perception(
        perception_profile, state_dir.expanduser().resolve()
    )
    try:
        plans, scanned = watch_once(_cfg(dry=True))
    except WatchError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Watch: {'dry-run' if not execute else 'execute'} (once)")
    click.echo(f"Scanned files: {scanned}")
    click.echo(f"Planned operations: {len(plans)}")
    click.echo("")

    for op in plans:
        echo_operation(op, verbose=verbose)

    if not execute:
        click.echo("")
        click.echo("Dry run only. Re-run with --execute to apply changes.")
        return

    if not plans:
        click.echo("Nothing to do.")
        return

    if not yes:
        click.confirm(
            f"Execute {len(plans)} operations?",
            abort=True,
        )

    try:
        results, _ = watch_once(_cfg(dry=False))
    except WatchError as exc:
        raise click.ClickException(str(exc)) from exc

    counts = Counter(op.status for op in results)
    click.echo("")
    click.echo("Execution summary:")
    for status, count in counts.items():
        click.echo(f"  {status}: {count}")


@watch_cmd.command("list")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
def watch_list(state_dir: Path) -> None:
    """List active watches (enable list)."""
    from .watch import _active_watches_path, load_active_watches

    state_dir = state_dir.expanduser().resolve()
    watches = load_active_watches(state_dir)
    if not watches:
        click.echo(
            "No active watches. Add one with: "
            "filewizard watch add --source DIR --preset NAME"
        )
        return
    click.echo(f"Active watches ({_active_watches_path(state_dir)}):\n")
    for w in watches:
        spec = w.preset if w.preset else str(w.rules)
        mode = "dry-run" if w.dry_run else "execute"
        click.echo(f"  - {w.name}: {w.source} [{spec}] "
                   f"({mode}, every {w.interval_s}s)")


@watch_cmd.command("add")
@click.option("--name", default=None, help="Watch name (default: derive from path).")
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory to watch.",
)
@click.option("--preset", "preset_name", default=None, help="Preset name.")
@click.option(
    "--rules",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML rules file.",
)
@click.option(
    "--interval",
    "interval_s",
    type=float,
    default=60.0,
    help="Poll interval in seconds (default 60).",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Run with real file moves (default: dry-run).",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option("--overwrite/--no-overwrite", default=False)
def watch_add(
    name: str | None,
    source: Path,
    preset_name: str | None,
    rules: Path | None,
    interval_s: float,
    execute: bool,
    state_dir: Path,
    overwrite: bool,
) -> None:
    """Add a watch to the enable list."""
    from .watch import ActiveWatch, add_active_watch

    state_dir = state_dir.expanduser().resolve()

    if bool(preset_name) == bool(rules):
        raise click.ClickException("Specify exactly one of --preset or --rules.")

    watch = ActiveWatch(
        name=name or source.name,
        source=source.expanduser().resolve(),
        preset=preset_name,
        rules=rules.expanduser().resolve() if rules else None,
        dry_run=not execute,
        interval_s=interval_s,
    )
    path = add_active_watch(state_dir, watch, overwrite=overwrite)
    click.echo(f"Saved watch {watch.name!r} to {path}")


@watch_cmd.command("remove")
@click.argument("name")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
def watch_remove(name: str, state_dir: Path) -> None:
    """Remove a watch from the enable list."""
    from .watch import WatchError, remove_active_watch

    state_dir = state_dir.expanduser().resolve()
    try:
        removed = remove_active_watch(state_dir, name)
    except WatchError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Removed watch {removed.name!r}.")


@watch_cmd.command("run")
@click.argument("name", required=False)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="Override: apply changes even if the watch is dry-run.",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State and journal directory.",
)
@click.option("--verbose", is_flag=True, default=False)
def watch_run(
    name: str | None,
    execute: bool,
    state_dir: Path,
    verbose: bool,
) -> None:
    """Run one active watch once (single tick)."""
    from .watch import (
        ActiveWatch,
        load_active_watches,
        watch_once,
    )

    state_dir = state_dir.expanduser().resolve()
    watches = load_active_watches(state_dir)
    if not watches:
        raise click.ClickException(f"No active watches in {state_dir}.")

    targets: list[ActiveWatch] = (
        [next((w for w in watches if w.name == name), None)]
        if name
        else watches
    )
    if name is not None and targets[0] is None:
        raise click.ClickException(f"No active watch named {name!r}.")

    for watch in targets:
        if watch is None:  # pragma: no cover - guarded above
            continue
        dry = False if execute else watch.dry_run
        cfg = replace(watch.to_watch_config(state_dir), dry_run=dry)
        click.echo(f"[watch] running {watch.name!r} ({cfg.source}) "
                   f"({'dry-run' if dry else 'execute'})")
        ops, scanned = watch_once(cfg)
        click.echo(f"  scanned={scanned} planned={len(ops)}")
        for op in ops:
            echo_operation(op, verbose=verbose)
        click.echo("")


@cli.group("presets")
def presets_cmd() -> None:
    """Manage reusable rule presets (RuleSet library)."""


@presets_cmd.command("list")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
def presets_list(state_dir: Path) -> None:
    """List presets in the library."""
    state_dir = state_dir.expanduser().resolve()
    ensure_builtin_presets(state_dir)
    items = list_presets(state_dir)
    if not items:
        click.echo(f"No presets in {presets_dir(state_dir)}")
        return
    click.echo(f"Presets in {presets_dir(state_dir)}:\n")
    for item in items:
        desc = f" — {item.description}" if item.description else ""
        click.echo(f"  {item.name:24} {item.rule_count:3} rules{desc}")


@presets_cmd.command("import")
@click.argument("rules_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--name", default=None, help="Preset name (default: file stem).")
@click.option("--overwrite", is_flag=True, default=False)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
def presets_import(
    rules_file: Path,
    name: str | None,
    overwrite: bool,
    state_dir: Path,
) -> None:
    """Import a YAML rules file into the preset library."""
    try:
        path = import_rules_file(
            rules_file,
            name=name,
            state_dir=state_dir.expanduser().resolve(),
            overwrite=overwrite,
        )
    except (PresetError, RulesLoadError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported preset → {path}")


@presets_cmd.command("delete")
@click.argument("name")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
@click.option("--yes", is_flag=True, default=False)
def presets_delete(name: str, state_dir: Path, yes: bool) -> None:
    """Delete a preset from the library."""
    if not yes:
        click.confirm(f"Delete preset {name!r}?", abort=True)
    try:
        path = delete_preset(name, state_dir.expanduser().resolve())
    except PresetError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deleted {path}")


@presets_cmd.command("show")
@click.argument("name")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
def presets_show(name: str, state_dir: Path) -> None:
    """Print a preset as YAML."""
    ensure_builtin_presets(state_dir.expanduser().resolve())
    try:
        ruleset = load_preset(name, state_dir.expanduser().resolve())
    except (PresetError, RulesLoadError) as exc:
        raise click.ClickException(str(exc)) from exc
    import yaml

    click.echo(
        yaml.safe_dump(
            ruleset.model_dump(mode="python", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )
    )


@cli.group("perception")
def perception_cmd() -> None:
    """Configure and probe OCR / vision providers."""


@perception_cmd.command("status")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
@click.option(
    "--profile",
    type=click.Choice(sorted(PROFILES.keys())),
    default=None,
)
def perception_status_cmd(state_dir: Path, profile: str | None) -> None:
    """Show perception config and endpoint health."""
    state_dir = state_dir.expanduser().resolve()
    cfg = (
        config_from_profile(profile)
        if profile
        else load_perception_config(state_dir=state_dir)
    )
    status = perception_status(cfg, state_dir=state_dir)
    click.echo(f"Profile: {status.get('profile') or '(file/default)'}")
    click.echo(f"Heuristics: {status['heuristics']}")
    click.echo(
        f"OCR: {status['ocr']['provider']}"
        + (f" model={status['ocr']['model']}" if status["ocr"].get("model") else "")
    )
    if status["ocr"].get("base_url"):
        click.echo(f"  URL: {status['ocr']['base_url']}")
    click.echo(
        f"Vision: {status['vision']['provider']}"
        + (
            f" model={status['vision']['model']}"
            if status["vision"].get("model")
            else ""
        )
    )
    if status["vision"].get("base_url"):
        click.echo(f"  URL: {status['vision']['base_url']}")
    for name, ep in (status.get("endpoints") or {}).items():
        if ep.get("ok"):
            click.echo(f"Endpoint {name}: OK ({ep.get('url')})")
        else:
            click.echo(f"Endpoint {name}: DOWN — {ep.get('error')}")


@perception_cmd.command("models")
@click.option(
    "--role",
    type=click.Choice(["ocr", "vision", "zeroshot"]),
    default=None,
    help="Only show entries for one role.",
)
def perception_models_cmd(role: str | None) -> None:
    """List known model IDs for perception providers (no network)."""
    try:
        rows = list_known_models(role)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if not rows:
        click.echo("No known models for this role.")
        return

    url_width = max(len(item.get("default_base_url") or "-") for item in rows)
    header = (
        f"{'ROLE':9} {'ID':22} {'MODEL':28} "
        f"{'BASE_URL':{url_width}} NOTES"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for item in rows:
        click.echo(
            f"{item['role']:9} {item['id']:22} {item['default_model']:28} "
            f"{item.get('default_base_url') or '-':{url_width}} {item['notes']}"
        )


@perception_cmd.command("init")
@click.option(
    "--profile",
    type=click.Choice(sorted(PROFILES.keys())),
    default="recommended",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
@click.option("--overwrite", is_flag=True, default=False)
def perception_init(profile: str, state_dir: Path, overwrite: bool) -> None:
    """Write perception.yaml from a built-in profile."""
    state_dir = state_dir.expanduser().resolve()
    path = state_dir / "perception.yaml"
    if path.exists() and not overwrite:
        raise click.ClickException(
            f"{path} already exists. Use --overwrite to replace."
        )
    cfg = config_from_profile(profile)
    out = save_perception_config(cfg, path)
    click.echo(f"Wrote {out} (profile={profile})")
    click.echo(
        "Start servers (recommended):\n"
        "  llama-server -hf ggml-org/GLM-OCR-GGUF:Q8_0 --port 8080\n"
        "  llama-server -hf <qwen3-vl-2b-gguf> --port 8081"
    )


@perception_cmd.command("test")
@click.argument("image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
)
@click.option(
    "--profile",
    type=click.Choice(sorted(PROFILES.keys())),
    default=None,
)
@click.option("--ocr", is_flag=True, default=False)
@click.option("--vision", is_flag=True, default=False)
def perception_test(
    image: Path,
    state_dir: Path,
    profile: str | None,
    ocr: bool,
    vision: bool,
) -> None:
    """Run perception extractors on a single image (no moves)."""
    from .facts import collect_facts

    state_dir = state_dir.expanduser().resolve()
    cfg = (
        config_from_profile(profile)
        if profile
        else load_perception_config(state_dir=state_dir)
    )
    warn_remote_perception(profile, state_dir)
    extractors = build_extractors(
        cfg,
        force_ocr=ocr or cfg.ocr.provider != "none",
        force_vision=vision or cfg.vision.provider != "none",
        state_dir=state_dir,
    )
    facts = collect_facts(image.expanduser().resolve(), extractors=extractors)
    click.echo(f"File: {facts.path}")
    click.echo(f"MIME: {facts.mime}  size={facts.size}")
    if facts.features.get("date_taken"):
        click.echo(
            f"date_taken: {facts.features.get('date_taken')} "
            f"({facts.features.get('date_source')})"
        )
    ocr_f = facts.features.get("ocr")
    if ocr_f:
        click.echo(f"OCR provider={ocr_f.get('provider')} model={ocr_f.get('model')}")
        if ocr_f.get("error"):
            click.echo(f"  error: {ocr_f['error']}")
        else:
            text = str(ocr_f.get("text") or "")
            click.echo(f"  text[{len(text)}]: {text[:500]!r}")
    vision_f = facts.features.get("vision")
    if vision_f:
        click.echo(
            f"Vision provider={vision_f.get('provider')} model={vision_f.get('model')}"
        )
        if vision_f.get("error"):
            click.echo(f"  error: {vision_f['error']}")
        for k, v in vision_f.items():
            if k in {"provider", "model", "error", "raw"}:
                continue
            click.echo(f"  {k}: {v}")


@cli.command("reset")
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.local/share/filewizard").expanduser(),
    help="State directory to clean.",
)
@click.option(
    "--all",
    "wipe_all",
    is_flag=True,
    default=False,
    help="Delete the entire state directory (journal, presets, config).",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation.",
)
def reset_cmd(state_dir: Path, wipe_all: bool, yes: bool) -> None:
    """Remove runtime files (cache, queue, logs). Does not uninstall the package."""
    from .persist import reset_runtime_paths

    state_dir = state_dir.expanduser().resolve()
    if wipe_all and not yes:
        raise click.ClickException("Refusing --all without --yes.")
    targets = reset_runtime_paths(state_dir, wipe_all=wipe_all)
    if not targets:
        click.echo("Nothing to reset.")
        return
    click.echo("Will remove:")
    for path in targets:
        click.echo(f"  {path}")
    if not yes:
        click.confirm("Continue?", abort=True)
    for path in targets:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file() or path.is_symlink():
            path.unlink()
    click.echo("Reset done. The Python package is still installed.")


@cli.command("ui")
def ui() -> None:
    """Open the PySide6 graphical interface."""

    try:
        from .ui.app import main as ui_main
    except Exception as exc:
        raise click.ClickException(
            "UI not installed. Install with:\n\n"
            '    pip install -e ".[ui]"\n'
        ) from exc

    ui_main()


@cli.group("mcp")
def mcp_cmd() -> None:
    """MCP server (stdio) exposing the FileWizard pipeline."""


@mcp_cmd.command("serve")
@click.option(
    "--name",
    default="filewizard",
    show_default=True,
    help="MCP server name.",
)
@click.option(
    "--title",
    default="FileWizard",
    show_default=True,
    help="Human-readable server title.",
)
def mcp_serve(name: str, title: str) -> None:
    """Run the MCP server over stdio (blocking until EOF)."""

    try:
        from .mcp import run_stdio
    except Exception as exc:
        raise click.ClickException(
            "MCP support not installed. Install with:\n\n"
            '    pip install -e ".[mcp]"\n'
        ) from exc

    run_stdio(name=name, title=title)
