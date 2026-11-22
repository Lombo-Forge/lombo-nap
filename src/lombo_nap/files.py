"""Writing a file so a reader never sees half of it."""

import contextlib
import os


def atomic_write(path: str, text: str, mode: int = 0o644) -> None:
    """Write to a temporary name, then rename over `path`. Raises OSError."""
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), mode)
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
