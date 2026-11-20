"""The decisions for "Still watching?". Pure: no network, disk or clock (the caller passes `now`).

A TV left running keeps a disk spinning all night. For every playing movie or episode this counts
continuous playback since the person last DID something. At the limit (hours, or a number of
episodes in a row) the screen shows "Still watching?". If nothing happens for `grace` seconds,
playback is stopped and the client is sent to its home page.

What counts as the person doing something (an "interaction"):
  * pressing play or pause,
  * starting a title by hand (not the next episode rolling on by itself),
  * a seek backwards, or a big jump forward.
What does not: autoplay into the next episode, and automatic skips (small forward jumps, a jump to
the very end of the episode, or a jump onto the end of an intro/credits segment).

A movie longer than the limit is allowed to finish: its deadline is a minute after it ends.
"""

from dataclasses import dataclass
from typing import Any

TICKS = 10_000_000  # Jellyfin ticks per second
SEEK_SLACK = 20.0  # seconds of drift before a position change counts as a seek
SKIP_MAX = 180.0  # a forward jump up to this is an automatic skip
END_ZONE = 90.0  # landing this close to the end is an outro skip
SEG_SLACK = 15.0  # a jump landing this close to a media segment's end is the auto-skip
CHAIN_END = 0.6  # same show, and the last episode was at least this far in: autoplay rolled on
RESTORE_MAX = 600.0  # saved counts older than this (a long outage) are dropped
RETAIN = 120.0  # keep a session's count this long if it vanishes between two episodes
MESSAGE_HEADER = "Still watching?"
MESSAGE_TEXT = "Still watching? Pause and play to keep going."


@dataclass
class Track:
    """What we remember about one playing session between polls."""

    item_id: str
    series_id: str
    pos: float | None  # seconds at the last poll (None: restored after a restart)
    runtime: float
    paused: bool
    seen_at: float
    quiet_since: float  # last interaction (or start)
    prompted_at: float | None = None
    is_movie: bool = False
    episodes: int = 1  # titles played since the last interaction, this one included
    label: str = ""


@dataclass(frozen=True)
class Action:
    kind: str  # "message", "stop" or "home"
    session_id: str
    label: str

    def __str__(self) -> str:
        what = {
            "message": 'show "Still watching?" on',
            "stop": "stop playback on",
            "home": "send to the home screen:",
        }[self.kind]
        return f"{what} {self.label}"


def _label(s: dict[str, Any], item: dict[str, Any]) -> str:
    title = item.get("Name") or "?"
    if item.get("SeriesName"):
        title = f"{item['SeriesName']} - {title}"
    return f"{s.get('UserName') or '?'} on {s.get('DeviceName') or '?'} ({title})"


def observe(s: dict[str, Any]) -> dict[str, Any] | None:
    """The bits of a Jellyfin session we use, or None if it is not playing a movie or episode."""
    item = s.get("NowPlayingItem") or {}
    if item.get("Type") not in ("Movie", "Episode"):
        return None
    ps = s.get("PlayState") or {}
    return {
        "sid": s.get("Id") or "",
        "user": s.get("UserName") or "",
        "label": _label(s, item),
        "item": item.get("Id") or "",
        "series": item.get("SeriesId") or "",
        "movie": item.get("Type") == "Movie",
        "runtime": (item.get("RunTimeTicks") or 0) / TICKS,
        "pos": (ps.get("PositionTicks") or 0) / TICKS,
        "paused": bool(ps.get("IsPaused")),
    }


def _interaction(t: Track, o: dict[str, Any], now: float, seg_ends: list[float]) -> bool:
    """Did the person do something since the last poll? `seg_ends` are the seconds where this
    item's intro / credits / recap segments end, so a jump onto one is seen as an auto-skip."""
    if o["item"] != t.item_id:
        rolled = (
            t.series_id
            and o["series"] == t.series_id
            and not t.is_movie
            and t.runtime
            and (t.pos or 0) >= CHAIN_END * t.runtime
        )
        return not rolled  # a new title: rolled on by itself, or picked by hand?
    if t.paused != o["paused"]:
        return True  # pressed play or pause
    if t.paused or t.pos is None:
        return False  # still paused, or restored after a restart with nothing to compare
    jump = o["pos"] - t.pos - (now - t.seen_at)  # position change beyond normal playback
    if jump < -SEEK_SLACK:
        return True
    if jump > SEEK_SLACK:
        landed_on_segment = any(abs(o["pos"] - e) <= SEG_SLACK for e in seg_ends)
        auto = jump <= SKIP_MAX or (o["runtime"] and o["pos"] >= o["runtime"] - END_ZONE) or landed_on_segment
        return not auto
    return False


def deadline(t: Track, limit: float, now: float) -> float:
    """When this session is due its prompt: `limit` after the last interaction, or, for a movie
    that runs past the limit, a minute after it ends (a pause does not add a runtime)."""
    due = t.quiet_since + limit
    if t.is_movie and t.runtime > limit and not t.paused and t.pos is not None:
        due = max(due, now + max(0.0, t.runtime - t.pos) + 60)
    return due


def step(
    tracks: dict[str, Track],
    sessions: list[dict[str, Any]],
    now: float,
    limit: float,
    grace: float,
    segments: dict[str, list[float]] | None = None,
    max_episodes: int = 0,
    skip_users: frozenset[str] = frozenset(),
) -> tuple[dict[str, Track], list[Action]]:
    """One poll. Returns (new tracks, actions). Nothing is sent here; the caller decides (dry run)."""
    out = {k: t for k, t in tracks.items() if now - t.seen_at <= RETAIN}
    actions: list[Action] = []
    for s in sessions:
        o = observe(s)
        if not o or not o["sid"] or o["user"].lower() in skip_users:
            continue
        key = o["sid"]
        t = out.get(key)
        if t is None:  # first sight counts as a start
            t = Track(o["item"], o["series"], o["pos"], o["runtime"], o["paused"], now, now, is_movie=o["movie"])
        else:
            if _interaction(t, o, now, (segments or {}).get(o["item"], [])):
                t.quiet_since, t.prompted_at, t.episodes = now, None, 1
            elif o["item"] != t.item_id:
                t.episodes += 1
            if o["item"] != t.item_id:
                t.item_id, t.series_id, t.is_movie = o["item"], o["series"], o["movie"]
            t.pos, t.runtime, t.paused, t.seen_at = o["pos"], o["runtime"], o["paused"], now
        t.label = o["label"]
        out[key] = t
        if t.prompted_at is None:
            if now >= deadline(t, limit, now) or (max_episodes and t.episodes > max_episodes):
                t.prompted_at = now
                actions.append(Action("message", key, t.label))
        elif now - t.prompted_at >= grace:
            actions += [Action("stop", key, t.label), Action("home", key, t.label)]
            del out[key]  # a fresh count when something plays again
    return out, actions


def wait_seconds(tracks: dict[str, Track], poll: float) -> float:
    """Poll every second while someone is being asked, so a quick pause and play is seen."""
    return 1.0 if any(t.prompted_at is not None for t in tracks.values()) else poll


def summary(tracks: dict[str, Track], limit: float, now: float) -> list[str]:
    """One line per tracked session, for `plan`."""
    lines = []
    for t in tracks.values():
        quiet = int((now - t.quiet_since) // 60)
        left = int(max(0.0, deadline(t, limit, now) - now) // 60)
        state = "asked, waiting for an answer" if t.prompted_at is not None else f"would be asked in {left} min"
        lines.append(f"{t.label}: no interaction for {quiet} min, {t.episodes} title(s) in a row, {state}")
    return lines


def dump_tracks(tracks: dict[str, Track], now: float) -> dict[str, Any]:
    """Counts survive a restart; positions do not (the first poll has nothing to compare)."""
    keep = ("item_id", "series_id", "runtime", "paused", "quiet_since", "prompted_at", "is_movie", "episodes", "label")
    return {"at": now, "tracks": {k: {f: getattr(t, f) for f in keep} for k, t in tracks.items()}}


def load_tracks(data: Any, now: float) -> dict[str, Track]:
    """Inverse of dump_tracks. Anything old or malformed gives a fresh start."""
    try:
        if now - float(data["at"]) > RESTORE_MAX:
            return {}
        return {
            k: Track(
                v["item_id"],
                v["series_id"],
                None,
                float(v["runtime"]),
                bool(v["paused"]),
                now,
                float(v["quiet_since"]),
                None if v.get("prompted_at") is None else float(v["prompted_at"]),
                bool(v["is_movie"]),
                int(v.get("episodes", 1)),
                str(v.get("label", "")),
            )
            for k, v in data["tracks"].items()
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return {}
