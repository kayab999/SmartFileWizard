from __future__ import annotations

import os
from pathlib import Path

DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".cache",
    ".local",
    "node_modules",
}


def iter_files(
    root: Path,
    include_hidden: bool = False,
):
    """
    Iterate regular files recursively.

    Safety defaults:
      - ignore common tooling directories
      - ignore hidden entries by default
      - do not follow symlinks (avoids cycles)
      - skip sockets, devices, and other non-regular files
      - skip paths that raise OSError (permissions / race deletions)
    """

    root = root.expanduser().resolve()

    try:
        if not root.is_dir():
            return
    except OSError:
        return

    def _on_walk_error(err: OSError) -> None:
        # Permissions, vanished dirs, etc. — skip and continue.
        return None

    for dirpath, dirnames, filenames in os.walk(
        root,
        followlinks=False,
        onerror=_on_walk_error,
    ):
        # Mutate dirnames in place so walk does not descend into filtered dirs.
        filtered: list[str] = []
        for name in dirnames:
            if name in DEFAULT_IGNORED_DIRS:
                continue
            if not include_hidden and name.startswith("."):
                continue
            filtered.append(name)
        dirnames[:] = filtered

        for filename in filenames:
            if not include_hidden and filename.startswith("."):
                continue

            path = Path(dirpath) / filename

            try:
                # Symlinks are never followed as directory roots (followlinks=False)
                # and never yielded as files even if they point to regular files.
                if path.is_symlink():
                    continue
                if not path.is_file():
                    continue
            except OSError:
                # Permission denied, vanished mid-scan, etc.
                continue

            yield path
