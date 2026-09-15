"""MCP server construction with the official `mcp` SDK (optional extra).

The SDK is imported only when this module is actually used (serve), keeping
core imports free of the dependency (invariant I4, ADR-0004).
"""

from __future__ import annotations

from pathlib import Path

from filewizard import __version__

from .tools import filewizard_apply_agent_labels as _apply_agent_labels
from .tools import filewizard_collect_facts as _collect_facts
from .tools import filewizard_execute as _execute
from .tools import filewizard_journal_batches as _journal_batches
from .tools import filewizard_list_presets as _list_presets
from .tools import filewizard_plan as _plan
from .tools import filewizard_undo_batch as _undo_batch
from .tools import filewizard_version as _filewizard_version
from .tools import ping as _ping


def _require_sdk():
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "MCP support requires the optional extra: pip install 'filewizard[mcp]'"
        ) from exc
    return MCPServer


def build_server(name: str = "filewizard", title: str = "FileWizard"):
    """Build an MCP server exposing the current tools.

    Read-only tools (WP-0.7.2): `filewizard_list_presets`,
    `filewizard_journal_batches`, `filewizard_collect_facts`,
    plus skeleton tools `ping`, `filewizard_version`.
    """
    MCPServer = _require_sdk()
    server = MCPServer(
        name=name,
        title=title,
        version=__version__,
        instructions=(
            "FileWizard MCP. Perception provides evidence; rules decide; "
            "the journal undoes. Execute tools require explicit confirmation."
        ),
    )

    @server.tool(
        name="ping",
        description="Liveness check. Returns {'ok': true, 'pong': 'pong'}.",
    )
    def ping() -> dict:
        return _ping()

    @server.tool(
        name="filewizard_version",
        description="Returns the FileWizard version string.",
    )
    def filewizard_version() -> dict:
        return _filewizard_version()

    @server.tool(
        name="filewizard_list_presets",
        description=(
            "List organization rule presets from the local library. "
            "Read-only; absolute paths."
        ),
    )
    def filewizard_list_presets(state_dir: str | None = None) -> dict:
        return _list_presets(Path(state_dir) if state_dir else None)

    @server.tool(
        name="filewizard_journal_batches",
        description=(
            "List journal batches (aggregated operations) from the undo journal. "
            "Read-only; absolute paths."
        ),
    )
    def filewizard_journal_batches(
        state_dir: str | None = None,
        limit: int = 20,
    ) -> dict:
        return _journal_batches(
            Path(state_dir) if state_dir else None,
            limit=limit,
        )

    @server.tool(
        name="filewizard_collect_facts",
        description=(
            "Collect metadata facts for a single file (size, mime, dates, "
            "image dims). Read-only; returns the resolved absolute path."
        ),
    )
    def filewizard_collect_facts(path: str) -> dict:
        return _collect_facts(path)

    @server.tool(
        name="filewizard_plan",
        description=(
            "Dry-run classification plan for a source directory. Never moves "
            "files. Requires exactly one of preset or rules."
        ),
    )
    def filewizard_plan(
        source: str,
        preset: str | None = None,
        rules: str | None = None,
        state_dir: str | None = None,
        limit: int = 100,
        perception_profile: str | None = None,
        enable_ocr: bool = False,
        enable_vision: bool = False,
        agent_features: dict | None = None,
    ) -> dict:
        return _plan(
            source,
            state_dir,
            preset=preset,
            rules=rules,
            limit=limit,
            perception_profile=perception_profile,
            enable_ocr=enable_ocr,
            enable_vision=enable_vision,
            agent_features=agent_features,
        )

    @server.tool(
        name="filewizard_execute",
        description=(
            "Execute a classification plan (mutates files). Requires "
            "confirm=true; otherwise returns a structured error."
        ),
    )
    def filewizard_execute(
        source: str,
        preset: str | None = None,
        rules: str | None = None,
        state_dir: str | None = None,
        limit: int = 100,
        confirm: bool = False,
        perception_profile: str | None = None,
        enable_ocr: bool = False,
        enable_vision: bool = False,
        agent_features: dict | None = None,
    ) -> dict:
        return _execute(
            source,
            state_dir,
            preset=preset,
            rules=rules,
            limit=limit,
            confirm=confirm,
            perception_profile=perception_profile,
            enable_ocr=enable_ocr,
            enable_vision=enable_vision,
            agent_features=agent_features,
        )

    @server.tool(
        name="filewizard_undo_batch",
        description=(
            "Undo a journal batch. Dry-run by default; applies the reverse "
            "moves only when confirm=true."
        ),
    )
    def filewizard_undo_batch(
        batch_id: str,
        state_dir: str | None = None,
        confirm: bool = False,
    ) -> dict:
        return _undo_batch(batch_id, state_dir, confirm=confirm)

    @server.tool(
        name="filewizard_apply_agent_labels",
        description=(
            "Apply agent labels (path -> feature dict, WP-0.5.3 cascade "
            "shape) to a dry-run plan. Never writes to disk; optionally runs "
            "a plan using the supplied labels as evidence."
        ),
    )
    def filewizard_apply_agent_labels(
        labels: dict,
        source: str | None = None,
        preset: str | None = None,
        rules: str | None = None,
        state_dir: str | None = None,
        limit: int = 100,
    ) -> dict:
        return _apply_agent_labels(
            labels,
            source,
            state_dir,
            preset=preset,
            rules=rules,
            limit=limit,
        )

    return server


def run_stdio(name: str = "filewizard", title: str = "FileWizard") -> None:
    """Serve over stdio until EOF. Convenience wrapper for CLI entrypoint."""
    server = build_server(name=name, title=title)

    try:
        import asyncio
    except ImportError:  # pragma: no cover - python always has asyncio
        raise

    try:
        asyncio.run(server.run_stdio_async())
    except KeyboardInterrupt:
        pass