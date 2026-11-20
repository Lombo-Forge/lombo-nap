"""The disk wake report, pure part: parse /proc and sysfs text, then work out what woke a disk.

No file, process or clock is touched here (sysinfo.py does that), so every function takes text or
plain values and can be tested with fixtures.

How a wake is attributed: two snapshots a minute or so apart. If a disk was in standby in the first
and active in the second, every process whose read/write byte counters grew in between is a suspect.
Suspects that also hold files open under that disk's mount points are ranked first. This is a hint,
not proof: /proc/<pid>/io does not say which disk the bytes went to.
"""

import json
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

STANDBY, ACTIVE, UNKNOWN = "standby", "active", "unknown"
SECTOR = 512


@dataclass(frozen=True)
class DiskSample:
    state: str
    sectors_read: int
    sectors_written: int
    mounts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcSample:
    comm: str
    container: str
    read_bytes: int
    write_bytes: int
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    ts: int  # seconds since the epoch
    disks: dict[str, DiskSample]
    procs: dict[str, ProcSample]  # key: pid as text


@dataclass(frozen=True)
class Suspect:
    pid: str
    comm: str
    container: str
    bytes: int
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Wake:
    disk: str
    ts: int
    sectors: int  # sectors moved on the disk between the two snapshots
    suspects: tuple[Suspect, ...]


# ------------------------------------------------------------------ parsing /proc and sysfs text
def parse_diskstats(text: str) -> dict[str, tuple[int, int]]:
    """/proc/diskstats -> {name: (sectors read, sectors written)}. Bad lines are skipped."""
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 10 and f[5].isdigit() and f[9].isdigit():
            out[f[2]] = (int(f[5]), int(f[9]))
    return out


def parse_mounts(text: str) -> list[tuple[str, str]]:
    """/proc/mounts -> [(device, mount point)] for real /dev/ devices. \\040 style escapes are decoded."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 2 and f[0].startswith("/dev/"):
            out.append((f[0], re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), f[1])))
    return out


def base_disk(device: str) -> str:
    """/dev/sdb1 -> sdb, /dev/nvme0n1p2 -> nvme0n1, /dev/mmcblk0p1 -> mmcblk0."""
    name = device.removeprefix("/dev/")
    if re.match(r"(nvme\d+n\d+|mmcblk\d+)p\d+$", name):
        return re.sub(r"p\d+$", "", name)
    return re.sub(r"\d+$", "", name) if re.match(r"(sd|vd|hd|xvd)[a-z]+\d+$", name) else name


def mounts_by_disk(mounts: list[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    found: dict[str, list[str]] = {}
    for dev, point in mounts:
        found.setdefault(base_disk(dev), []).append(point)
    return {k: tuple(v) for k, v in found.items()}


def parse_hdparm(text: str) -> str:
    """Output of `hdparm -C` -> "standby", "active" or "unknown"."""
    m = re.search(r"drive state is:\s*(\S+)", text)
    if not m:
        return UNKNOWN
    state = m.group(1).lower()
    if state in {"standby", "sleeping"}:
        return STANDBY
    return ACTIVE if state.startswith("active") or state == "idle" else UNKNOWN


def parse_container(cgroup_text: str) -> str:
    """/proc/<pid>/cgroup -> the first 12 characters of a container id, or "" for a host process."""
    m = re.search(r"\b([0-9a-f]{64})\b", cgroup_text)
    return m.group(1)[:12] if m else ""


def parse_proc_io(text: str) -> tuple[int, int]:
    """/proc/<pid>/io -> (read_bytes, write_bytes): what really went to storage, not cache hits."""
    vals = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    try:
        return int(vals["read_bytes"]), int(vals["write_bytes"])
    except (KeyError, ValueError):
        return 0, 0


def paths_under(paths: list[str], mounts: tuple[str, ...]) -> tuple[str, ...]:
    """The paths that sit inside one of the mount points (never the root mount: that matches everything)."""
    keep = [m.rstrip("/") + "/" for m in mounts if m != "/"]
    return tuple(sorted({p for p in paths if any(p.startswith(k) for k in keep)}))


# ------------------------------------------------------------------ snapshot <-> one JSON line
def to_json(snap: Snapshot) -> str:
    return json.dumps(
        {
            "ts": snap.ts,
            "disks": {k: [d.state, d.sectors_read, d.sectors_written, list(d.mounts)] for k, d in snap.disks.items()},
            "procs": {
                k: [p.comm, p.container, p.read_bytes, p.write_bytes, list(p.paths)] for k, p in snap.procs.items()
            },
        },
        separators=(",", ":"),
    )


def from_json(line: str) -> Snapshot:
    """Raises ValueError for anything that is not a snapshot line."""
    try:
        d: Any = json.loads(line)
        return Snapshot(
            int(d["ts"]),
            {k: DiskSample(v[0], int(v[1]), int(v[2]), tuple(v[3])) for k, v in d["disks"].items()},
            {k: ProcSample(v[0], v[1], int(v[2]), int(v[3]), tuple(v[4])) for k, v in d["procs"].items()},
        )
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise ValueError(f"not a snapshot line: {e}") from e


# ------------------------------------------------------------------ attribution
def find_wakes(prev: Snapshot, cur: Snapshot, top: int = 5) -> list[Wake]:
    """Disks that went from standby to active between two snapshots, with the likely culprits."""
    wakes = []
    for name, now in cur.disks.items():
        before = prev.disks.get(name)
        if not before or before.state != STANDBY or now.state != ACTIVE:
            continue
        suspects = []
        for pid, p in cur.procs.items():
            old = prev.procs.get(pid)
            grown = (p.read_bytes + p.write_bytes) - (
                (old.read_bytes + old.write_bytes) if old and old.comm == p.comm else 0
            )
            if grown > 0:
                suspects.append(Suspect(pid, p.comm, p.container, grown, paths_under(list(p.paths), now.mounts)))
        suspects.sort(key=lambda s: (bool(s.paths), s.bytes), reverse=True)
        sectors = (now.sectors_read - before.sectors_read) + (now.sectors_written - before.sectors_written)
        wakes.append(Wake(name, cur.ts, max(0, sectors), tuple(suspects[:top])))
    return wakes


def all_wakes(snaps: list[Snapshot]) -> list[Wake]:
    ordered = sorted(snaps, key=lambda s: s.ts)
    return [w for a, b in pairwise(ordered) for w in find_wakes(a, b)]


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"  # unreachable; keeps the type checker happy


def _when(ts: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def report_text(snaps: list[Snapshot], days: float, max_events: int = 10) -> str:
    """The report: per disk wake-ups and time asleep, then the latest wakes with their suspects."""
    if not snaps:
        return "No samples yet. Run `lombo-nap wake sample` every minute (see examples/)."
    ordered = sorted(snaps, key=lambda s: s.ts)
    cutoff = ordered[-1].ts - int(days * 86400)
    recent = [s for s in ordered if s.ts >= cutoff]
    count: dict[str, int] = {}
    asleep: dict[str, int] = {}
    for s in recent:
        for name, d in s.disks.items():
            if d.state != UNKNOWN:
                count[name] = count.get(name, 0) + 1
                asleep[name] = asleep.get(name, 0) + (d.state == STANDBY)
    wakes = all_wakes(recent)
    lines = [f"{'disk':<12} {'wake-ups':>8} {'asleep':>7}   (last {days:g} days, {len(recent)} samples)"]
    for name in sorted(count):
        n = sum(1 for w in wakes if w.disk == name)
        lines.append(f"{name:<12} {n:>8} {100 * asleep[name] / count[name]:>6.0f}%")
    if not count:
        lines.append("No disk reported a power state. Is hdparm installed, and are the disks spinning (not SSD)?")
    for w in wakes[-max_events:]:
        lines.append(f"\n{_when(w.ts)}  {w.disk} woke ({w.sectors * SECTOR // 1024} KiB moved)")
        if not w.suspects:
            lines.append("  no process I/O seen (run the sampler as root to read /proc/<pid>/io)")
        for sus in w.suspects:
            where = f"container {sus.container}" if sus.container else "host"
            hint = f"  files: {', '.join(sus.paths[:3])}" if sus.paths else ""
            lines.append(f"  {sus.comm} (pid {sus.pid}, {where}) {_size(sus.bytes)}{hint}")
    return "\n".join(lines)
