"""The status document: what the app tracks right now (docs/contracts.md). Pure except `write()`."""

import json
from typing import Any

from . import core
from .files import atomic_write

VERSION = 1


def build(
    tracks: dict[str, core.Track],
    now: float,
    *,
    dry_run: bool,
    limit_hours: int,
    grace_seconds: int,
    poll_seconds: int,
    user_limits: dict[str, float],
    limits_file: str,
) -> dict[str, Any]:
    default = limit_hours * 3600.0
    rows: list[dict[str, Any]] = []
    for t in tracks.values():
        own = core.limit_for(t.user, default, user_limits)
        asked = t.prompted_at is not None
        rows.append(
            {
                "user": t.user,
                "label": t.label,
                "paused": t.paused,
                "state": "asked" if asked else "counting",
                "quiet_seconds": int(max(0.0, now - t.quiet_since)),
                "titles_in_row": t.episodes,
                "limit_seconds": int(own),
                "limit_source": "own" if t.user.lower() in user_limits else "default",
                "ask_in_seconds": None if asked else int(max(0.0, core.deadline(t, own, now) - now)),
                "stop_in_seconds": int(max(0.0, (t.prompted_at or 0.0) + grace_seconds - now)) if asked else None,
            }
        )
    rows.sort(key=lambda r: (r["user"].lower(), r["label"]))
    return {
        "version": VERSION,
        "updated": int(now),
        "dry_run": dry_run,
        "limit_hours": limit_hours,
        "grace_seconds": grace_seconds,
        "poll_seconds": poll_seconds,
        "limits_file": limits_file,
        "limits": {n: s / 3600 for n, s in sorted(user_limits.items())},
        "sessions": rows,
    }


def write(path: str, doc: dict[str, Any]) -> None:
    """Atomic, mode 0644. Raises OSError."""
    atomic_write(path, json.dumps(doc))
