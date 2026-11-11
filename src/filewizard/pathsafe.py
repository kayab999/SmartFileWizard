"""Path safety helpers: fail closed on symlink components."""

from __future__ import annotations

import os
from pathlib import Path


def has_symlink_component(path: Path) -> bool:
    """True if any component of the (absolute) path is a symlink."""
    try:
        current = Path(path).expanduser()
        if not current.is_absolute():
            current = Path.cwd() / current
        for parent in (current, *current.parents):
            if parent.is_symlink():
                return True
    except OSError:
        return True
    return False


def secure_resolve(path: Path) -> Path:
    """Resolve ``path`` and reject any symlink component (O_NOFOLLOW).

    Uses ``os.open(..., O_NOFOLLOW)`` on each existing component so a
    symlink swap is detected, not followed. Non-existent trailing
    components (planned destinations) are appended to the verified prefix.
    """
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    # Walk from the root with O_NOFOLLOW per component.
    parts = path.parts[1:]  # drop '/'
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    verified = Path("/")
    try:
        for i, part in enumerate(parts):
            try:
                nfd = os.open(
                    part,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY,
                    dir_fd=fd,
                )
            except (OSError, NotADirectoryError):
                # Leaf may be a regular file or not exist yet.
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None  # type: ignore[assignment]
                verified = verified / part
                # Verify this component is not a symlink even if it exists.
                if verified.is_symlink():
                    raise ValueError(f"symlink component in path: {verified}")
                break
            os.close(fd)
            fd = nfd
            verified = verified / part
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    if verified.is_symlink():
        raise ValueError(f"symlink in path: {verified}")
    return verified
