"""MCP server (0.7). Exposes the same pipeline behind the MCP protocol.

The `mcp` SDK is an optional dependency (`filewizard[mcp]`) and is imported
lazily so that importing this package never requires it (invariant I4).
"""

from .tools import filewizard_apply_agent_labels
from .tools import filewizard_collect_facts
from .tools import filewizard_execute
from .tools import filewizard_journal_batches
from .tools import filewizard_list_presets
from .tools import filewizard_plan
from .tools import filewizard_undo_batch
from .tools import filewizard_version, ping

__all__ = [
    "filewizard_version",
    "ping",
    "filewizard_list_presets",
    "filewizard_journal_batches",
    "filewizard_collect_facts",
    "filewizard_plan",
    "filewizard_execute",
    "filewizard_undo_batch",
    "filewizard_apply_agent_labels",
    "build_server",
    "run_stdio",
]

# SDK import is deferred to keep core imports light (ADR-0004).


def build_server(name: str = "filewizard", title: str = "FileWizard"):
    """Build an MCP server instance with the initial read-only tools.

    Requires the optional extra `filewizard[mcp]`.
    """
    from .server import build_server as _build

    return _build(name=name, title=title)


def run_stdio(name: str = "filewizard", title: str = "FileWizard") -> None:
    """Run the MCP server over stdio (blocking). Exit on EOF / Ctrl-C."""
    from .server import run_stdio as _run

    _run(name=name, title=title)