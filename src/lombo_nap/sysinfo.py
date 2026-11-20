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
MAX_PROCS = 40  # processes kept per snapshot, by bytes moved


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


def take_snapshot(root: Path, now: int, state_of: Callable[[str], str] = hdparm_state) -> wake.Snapshot:
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
        paths = wake.paths_under(_open_paths(entry), all_mounts)
        procs[entry.name] = wake.ProcSample(
            _read(entry / "comm").strip() or "?", wake.parse_container(_read(entry / "cgroup")), r, w, paths
        )
    top = sorted(procs.items(), key=lambda kv: (bool(kv[1].paths), kv[1].read_bytes + kv[1].write_bytes), reverse=True)
    return wake.Snapshot(now, disks, dict(top[:MAX_PROCS]))


def append_snapshot(path: Path, snap: wake.Snapshot, keep_lines: int) -> None:
    """Add one line; when the file is a third over `keep_lines`, drop the oldest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(wake.to_json(snap) + "\n")
    lines = path.read_text().splitlines()
    if len(lines) > keep_lines * 4 // 3:
        path.write_text("\n".join(lines[-keep_lines:]) + "\n")


def read_snapshots(path: Path) -> list[wake.Snapshot]:
    snaps = []
    for line in _read(path).splitlines():
        try:
            snaps.append(wake.from_json(line))
        except ValueError:
            continue  # a half-written or foreign line is skipped
    return snaps
