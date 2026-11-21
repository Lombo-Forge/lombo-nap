"""The disk wake report, I/O part: read /proc and sysfs, ask hdparm for the power state, keep the log.

`hdparm -C` only asks the drive for its power state; it does not wake it. Nothing here writes to a
device. `root` is "/" on a real host; tests point it at a fake tree.
"""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import wake

MAX_FDS = 300  # per process: enough to find the open files without walking a huge directory
MAX_PROCS = 40  # processes kept per snapshot, by bytes moved since the previous sample
MAX_PATHS = 5  # open files kept per process
MAX_LOG_BYTES = 32 * 1024 * 1024  # the log is trimmed to its newest half when it passes this


def hdparm_state(name: str) -> str:
    """Power state text from `hdparm -C /dev/<name>`; "" when hdparm is missing or refuses."""
    try:
        done = subprocess.run(  # noqa: S603  fixed arguments, name comes from sysfs
            ["hdparm", "-C", f"/dev/{name}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def spinning_disks(root: Path) -> list[str]:
    """Whole disks that are rotational (the ones that can spin down)."""
    stats = wake.parse_diskstats(_read(root / "proc/diskstats"))
    return sorted(n for n in stats if _read(root / "sys/block" / n / "queue/rotational").strip() == "1")


def _open_paths(pid_dir: Path) -> list[str]:
    paths = []
    try:
        for i, fd in enumerate(os.scandir(pid_dir / "fd")):
            if i >= MAX_FDS:
                break
            try:
                paths.append(os.readlink(fd.path))
            except OSError:
                continue
    except OSError:
        pass
    return paths


def take_snapshot(
    root: Path, now: int, state_of: Callable[[str], str] = hdparm_state, prev: wake.Snapshot | None = None
) -> wake.Snapshot:
    """`prev` (the last sample) lets the 40 kept processes be the ones whose counters grew, not the biggest lifetime."""
    stats = wake.parse_diskstats(_read(root / "proc/diskstats"))
    mounts = wake.mounts_by_disk(wake.parse_mounts(_read(root / "proc/mounts")))
    disks = {}
    for name in spinning_disks(root):
        read, written = stats[name]
        disks[name] = wake.DiskSample(wake.parse_hdparm(state_of(name)), read, written, mounts.get(name, ()))
    all_mounts = tuple(m for d in disks.values() for m in d.mounts)

    procs: dict[str, wake.ProcSample] = {}
    try:
        entries = list((root / "proc").iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        io = _read(entry / "io")
        if not io:
            continue  # not readable (not root) or the process is gone
        r, w = wake.parse_proc_io(io)
        if r + w == 0:
            continue
        paths = wake.paths_under(_open_paths(entry), all_mounts)[:MAX_PATHS]
        procs[entry.name] = wake.ProcSample(
            _read(entry / "comm").strip() or "?", wake.parse_container(_read(entry / "cgroup")), r, w, paths
        )
    before = prev.procs if prev else {}

    def moved(kv: tuple[str, wake.ProcSample]) -> tuple[bool, bool, int]:
        """Bytes moved since the previous sample (a new pid or program counts from zero), as find_wakes does."""
        p, old = kv[1], before.get(kv[0])
        grown = (p.read_bytes + p.write_bytes) - (
            (old.read_bytes + old.write_bytes) if old and old.comm == p.comm else 0
        )
        return grown > 0, bool(p.paths), grown

    top = sorted(procs.items(), key=moved, reverse=True)
    return wake.Snapshot(now, disks, dict(top[:MAX_PROCS]))


def append_snapshot(path: Path, snap: wake.Snapshot, keep_lines: int, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Add one line; when the file passes `max_bytes`, keep only its newest lines (at most `keep_lines`).

    Only the tail is read, and the trimmed copy is written beside the log and swapped in with
    os.replace, so a crash or a reader never sees a short file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(wake.to_json(snap) + "\n")
    size = path.stat().st_size
    if size <= max_bytes:
        return
    with path.open("rb") as f:
        f.seek(size - max_bytes // 2)
        tail = f.read().splitlines(keepends=True)[1:]  # the first line is cut in half
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(b"".join(tail[-keep_lines:]))
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def last_snapshot(path: Path, tail_bytes: int = 1 << 20) -> wake.Snapshot | None:
    """The newest snapshot in the log, reading only the end of the file."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - tail_bytes))
            data = f.read()
    except OSError:
        return None
    for line in reversed(data.decode(errors="replace").splitlines()):
        try:
            return wake.from_json(line)
        except ValueError:
            continue
    return None


def read_snapshots(path: Path) -> list[wake.Snapshot]:
    snaps = []
    for line in _read(path).splitlines():
        try:
            snaps.append(wake.from_json(line))
        except ValueError:
            continue  # a half-written or foreign line is skipped
    return snaps
