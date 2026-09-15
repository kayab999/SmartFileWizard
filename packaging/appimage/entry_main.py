"""Unified entry for AppImage: GUI by default, CLI when CLI args given.

PyInstaller entry point that dispatches to CLI or GUI without relying on
two separate EXEs (which caused script mixing in one-dir mode).
"""
import sys

CLI_SUBCOMMANDS = {
    "run", "undo", "purge", "watch", "presets", "perception", "reset", "ui", "mcp",
    "list", "add", "remove", "import", "delete", "show", "status", "models",
    "init", "test", "serve", "once", "help",
}

def should_run_cli(argv: list[str]) -> bool:
    if not argv:
        return False
    first = argv[0]
    # Flags that clearly mean CLI
    if first in ("--help", "-h", "--version", "-V"):
        return True
    if first in CLI_SUBCOMMANDS:
        return True
    # Also handle --help after subcommand? cli(click) will handle
    return False

def main() -> None:
    # If invoked via symlink name, respect it
    prog = sys.argv[0]
    if "filewizard-ui" in prog:
        from filewizard.ui.__main__ import main as gui_main
        gui_main()
        return
    if "filewizard-mcp" in prog or "filewizard-cli" in prog:
        from filewizard.cli import cli
        cli()
        return

    args = sys.argv[1:]
    if should_run_cli(args):
        from filewizard.cli import cli
        # click expects sys.argv intact
        cli()
    else:
        # No args or unknown -> GUI
        try:
            from filewizard.ui.__main__ import main as gui_main
            gui_main()
        except SystemExit:
            raise
        except Exception as exc:
            # If GUI fails due to missing display/PySide6, fall back to CLI help
            # but show the error.
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    main()
