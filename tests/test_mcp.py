"""WP-0.7.1: MCP skeleton — lazy import, pure tool payloads, server build."""

from filewizard import __version__


def test_mcp_module_imports_without_starting_stdio() -> None:
    """Importing filewizard.mcp must not start any transport."""
    import filewizard.mcp as mcp

    assert callable(mcp.ping)
    assert callable(mcp.filewizard_version)
    assert callable(mcp.build_server)
    assert callable(mcp.run_stdio)


def test_version_tool_pure_function() -> None:
    from filewizard.mcp.tools import filewizard_version

    payload = filewizard_version()
    assert payload["ok"] is True
    assert payload["tool"] == "filewizard_version"
    assert payload["version"] == __version__


def test_ping_tool_pure_function() -> None:
    from filewizard.mcp.tools import ping

    payload = ping()
    assert payload["ok"] is True
    assert payload["pong"] == "pong"


def test_result_error_shape() -> None:
    from filewizard.mcp.tools import result_error

    payload = result_error("filewizard_plan", "bad preset")
    assert payload == {"ok": False, "tool": "filewizard_plan", "error": "bad preset"}


def test_build_server_registers_tools() -> None:
    """Optional-mcp: exercise server build when the SDK is installed."""
    from filewizard.mcp.server import _require_sdk

    try:
        _require_sdk()
    except ImportError:
        # SDK extra not installed in this env: skeleton still valid.
        return

    from filewizard.mcp.server import build_server

    server = build_server()
    assert server is not None
    names = [t.name for t in server._tool_manager.list_tools()]
    assert "ping" in names
    assert "filewizard_version" in names

    # The wrapped payload logic is fully covered by the pure-function tests;
    # calling through ToolManager requires an MCP Context (transport-level).