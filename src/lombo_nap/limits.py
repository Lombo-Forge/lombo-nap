"""The limits file: per-person hours that can change while the app runs (docs/contracts.md).

`{"version": 1, "limits": {"alice": 2, "bob": 4.5}}`, read again every round. A missing file means no
file limits. A damaged file (not JSON, wrong shape, a version this app does not know, a value that is not a
number) is ignored as a whole: the last good contents stay in force, or, if there never were any, the
`LOMBO_NAP_USER_LIMITS` list and the global limit apply.
"""

import json
import math
import sys
from pathlib import Path
from typing import Any

from .config import MAX_HOURS, MIN_HOURS

VERSION = 1


class LimitsFileError(Exception):
    """The file is not usable. The message says why, in plain words."""


def parse(text: str) -> dict[str, float]:
    """The file's text -> {lower-case name: seconds}, hours clamped to 1..6. Raises LimitsFileError."""
    try:
        doc: Any = json.loads(text)
    except ValueError:
        raise LimitsFileError("not valid JSON") from None
    if not isinstance(doc, dict):
        raise LimitsFileError("the top level must be an object")
    version = doc.get("version")
    if isinstance(version, bool) or version != VERSION:
        raise LimitsFileError(f"version {version!r} is not understood (this app reads version {VERSION})")
    raw = doc.get("limits")
    if not isinstance(raw, dict):
        raise LimitsFileError('"limits" must be an object of name: hours')
    out: dict[str, float] = {}
    for name, hours in raw.items():
        key = name.strip().lower()
        if not key:
            raise LimitsFileError("a name is empty")
        if key in out:
            raise LimitsFileError(f"{key!r} is listed more than once")
        if isinstance(hours, bool) or not isinstance(hours, int | float) or not math.isfinite(hours):
            raise LimitsFileError(f"hours for {name!r} must be a number")
        out[key] = max(MIN_HOURS, min(MAX_HOURS, float(hours))) * 3600.0
    return out


class LimitsFile:
    """Re-reads the file on `refresh()` and remembers the last good contents."""

    def __init__(self, path: str | None):
        self.path = path
        self.limits: dict[str, float] = {}
        self.state = "off" if not path else "ok"  # off, ok, missing or damaged
        self._warned = ""

    def refresh(self) -> None:
        if not self.path:
            return
        try:
            text = Path(self.path).read_text()
        except FileNotFoundError:
            self.limits, self.state, self._warned = {}, "missing", ""
            return
        except (OSError, UnicodeDecodeError) as e:
            self._damaged(str(e))
            return
        try:
            self.limits, self.state, self._warned = parse(text), "ok", ""
        except LimitsFileError as e:
            self._damaged(str(e))

    def _damaged(self, why: str) -> None:
        self.state = "damaged"  # self.limits keeps the last good contents
        if why != self._warned:  # once per problem, not once per round
            self._warned = why
            print(f"[warn] limits file {self.path} ignored ({why}); keeping the last good limits", file=sys.stderr)
