"""Entry shim for GUI — avoids relative import issues in PyInstaller."""
from filewizard.ui.__main__ import main

if __name__ == "__main__":
    main()
