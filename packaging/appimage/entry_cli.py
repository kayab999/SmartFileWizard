"""Entry shim for CLI — avoids relative import issues in PyInstaller."""
from filewizard.cli import cli

if __name__ == "__main__":
    cli()
