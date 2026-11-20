"""The wake report: parsing fixtures of /proc text, attribution, and a fake /proc tree on disk."""

import argparse
import os
from pathlib import Path

import pytest

from lombo_nap import sysinfo, wake
from lombo_nap.cli import wake_cmd, wake_doctor
from lombo_nap.config import WakeConfig

DISKSTATS = """\
   8       0 sda 100 0 2000 50 30 0 800 20 0 70 70
   8       1 sda1 90 0 1900 40 30 0 800 20 0 60 60
   8      16 sdb 10 0 160 5 4 0 64 2 0 7 7
 259       0 nvme0n1 5 0 80 1 5 0 80 1 0 2 2
   7       0 loop0 1 0 8 0 0 0 0 0 0 0 0
bad line
"""
MOUNTS = """\
/dev/sda1 /mnt/hdd1 ext4 rw 0 0
/dev/sdb1 /mnt/hdd\\0402 ext4 rw 0 0
/dev/nvme0n1p2 / ext4 rw 0 0
tmpfs /run tmpfs rw 0 0
"""
CID = "ab" * 32


def test_parse_diskstats_skips_bad_lines():
    stats = wake.parse_diskstats(DISKSTATS)
    assert stats["sda"] == (2000, 800)
    assert "bad" not in stats
    assert len(stats) == 5


def test_mounts_and_base_disks():
    mounts = wake.parse_mounts(MOUNTS)
    assert ("/dev/sdb1", "/mnt/hdd 2") in mounts
    assert len(mounts) == 3  # tmpfs is not a device
    assert wake.mounts_by_disk(mounts) == {"sda": ("/mnt/hdd1",), "sdb": ("/mnt/hdd 2",), "nvme0n1": ("/",)}
    assert [wake.base_disk(d) for d in ("/dev/sdc12", "/dev/mmcblk0p1", "/dev/dm-0", "sdd")] == [
        "sdc",
        "mmcblk0",
        "dm-0",
        "sdd",
    ]


@pytest.mark.parametrize(
    ("text", "state"),
    [
        (" drive state is:  standby\n", "standby"),
        (" drive state is:  sleeping", "standby"),
        (" drive state is:  active/idle", "active"),
        (" drive state is:  idle", "active"),
        (" drive state is:  unknown", "unknown"),
        ("", "unknown"),
    ],
)
def test_parse_hdparm(text, state):
    assert wake.parse_hdparm(text) == state


def test_parse_container_and_proc_io():
    assert wake.parse_container(f"0::/system.slice/docker-{CID}.scope\n") == "abababababab"
    assert wake.parse_container("0::/user.slice\n") == ""
    assert wake.parse_proc_io("rchar: 5\nread_bytes: 4096\nwrite_bytes: 8192\n") == (4096, 8192)
    assert wake.parse_proc_io("nothing useful") == (0, 0)
    assert wake.parse_proc_io("read_bytes: x\nwrite_bytes: 1") == (0, 0)


def test_paths_under_ignores_the_root_mount():
    paths = ["/mnt/hdd1/tv/a.mkv", "/mnt/hdd10/x", "/etc/passwd", "/mnt/hdd1/tv/a.mkv"]
    assert wake.paths_under(paths, ("/mnt/hdd1",)) == ("/mnt/hdd1/tv/a.mkv",)
    assert wake.paths_under(paths, ("/",)) == ()


def snap(ts, state, sectors=0, procs=None):
    disks = {"sda": wake.DiskSample(state, sectors, 0, ("/mnt/hdd1",))}
    return wake.Snapshot(ts, disks, procs or {})


def test_snapshot_round_trips_and_rejects_junk():
    s = snap(10, "standby", 5, {"7": wake.ProcSample("scanner", "abc", 1, 2, ("/mnt/hdd1/a",))})
    assert wake.from_json(wake.to_json(s)) == s
    for junk in ("not json", "{}", '{"ts":1,"disks":{"a":[]},"procs":{}}', "[]"):
        with pytest.raises(ValueError, match=r".*"):
            wake.from_json(junk)


def test_a_wake_names_the_processes_whose_io_grew():
    p1 = {
        "1": wake.ProcSample("indexer", "", 100, 0),
        "2": wake.ProcSample("player", "abc", 100, 0, ("/mnt/hdd1/tv/a.mkv", "/etc/x")),
        "3": wake.ProcSample("quiet", "", 50, 50),
    }
    p2 = {
        "1": wake.ProcSample("indexer", "", 900_000, 0),
        "2": wake.ProcSample("player", "abc", 4_200, 0, ("/mnt/hdd1/tv/a.mkv", "/etc/x")),
        "3": wake.ProcSample("quiet", "", 50, 50),
        "4": wake.ProcSample("new", "", 10, 0),
        "5": wake.ProcSample("recycled", "", 1, 0),
    }
    p1["5"] = wake.ProcSample("other-name", "", 999, 0)  # same pid, different program: counted from zero
    wakes = wake.find_wakes(snap(0, "standby", 10, p1), snap(60, "active", 30, p2))
    assert len(wakes) == 1
    w = wakes[0]
    assert (w.disk, w.sectors) == ("sda", 20)
    assert [s.comm for s in w.suspects] == ["player", "indexer", "new", "recycled"]  # files on the disk rank first
    assert w.suspects[0].paths == ("/mnt/hdd1/tv/a.mkv",)
    assert w.suspects[0].container == "abc"


def test_no_wake_without_a_standby_to_active_change():
    assert wake.find_wakes(snap(0, "active"), snap(60, "active")) == []
    assert wake.find_wakes(snap(0, "standby"), snap(60, "standby")) == []
    assert wake.find_wakes(snap(0, "unknown"), snap(60, "active")) == []
    assert wake.find_wakes(wake.Snapshot(0, {}, {}), snap(60, "active")) == []


def test_report_text():
    assert "No samples yet" in wake.report_text([], 2)
    procs = {"1": wake.ProcSample("indexer", "", 0, 2_000_000, ("/mnt/hdd1/x",))}
    snaps = [snap(0, "standby"), snap(60, "active", 100, procs), snap(120, "standby"), snap(180, "standby")]
    text = wake.report_text(snaps, 2)
    assert "sda" in text
    assert "1" in text.splitlines()[1]  # one wake-up
    assert "75%" in text  # three of four samples asleep
    assert "indexer (pid 1, host) 1.9 MiB  files: /mnt/hdd1/x" in text
    quiet = wake.report_text([snap(0, "standby"), snap(60, "active")], 2)
    assert "no process I/O seen" in quiet
    assert "hdparm" in wake.report_text([snap(0, "unknown")], 2)
    old = wake.report_text([snap(0, "standby"), snap(60, "active"), snap(10**6, "standby")], 0.001)
    assert "1 samples" in old
    assert wake._size(500) == "500 B"
    assert wake._size(5 * 1024**4).endswith("GiB")


# ------------------------------------------------------------------ a fake /proc and /sys tree
@pytest.fixture
def host(tmp_path: Path) -> Path:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/diskstats").write_text(DISKSTATS)
    (tmp_path / "proc/mounts").write_text(MOUNTS)
    for name, rota in (("sda", "1"), ("sdb", "1"), ("nvme0n1", "0")):
        q = tmp_path / "sys/block" / name / "queue"
        q.mkdir(parents=True)
        (q / "rotational").write_text(rota + "\n")
    media = tmp_path / "mnt-file"
    media.write_text("x")
    for pid, comm, io, cg in (
        ("42", "scanner\n", "read_bytes: 5000\nwrite_bytes: 0\n", f"0::/docker-{CID}.scope\n"),
        ("43", "idle\n", "read_bytes: 0\nwrite_bytes: 0\n", ""),
        ("44", "locked\n", "", ""),
    ):
        d = tmp_path / "proc" / pid
        d.mkdir()
        (d / "comm").write_text(comm)
        (d / "cgroup").write_text(cg)
        if io:
            (d / "io").write_text(io)
    (tmp_path / "proc/42/fd").mkdir()
    os.symlink("/mnt/hdd1/tv/a.mkv", tmp_path / "proc/42/fd/3")
    (tmp_path / "proc/self-note").write_text("not a pid")
    return tmp_path


def fake_hdparm(name):
    return " drive state is:  standby" if name == "sda" else ""


def test_take_snapshot_reads_the_fake_tree(host):
    assert sysinfo.spinning_disks(host) == ["sda", "sdb"]
    s = sysinfo.take_snapshot(host, 99, fake_hdparm)
    assert s.disks["sda"] == wake.DiskSample("standby", 2000, 800, ("/mnt/hdd1",))
    assert s.disks["sdb"].state == "unknown"
    assert list(s.procs) == ["42"]  # idle and unreadable processes are left out
    assert s.procs["42"] == wake.ProcSample("scanner", "abababababab", 5000, 0, ("/mnt/hdd1/tv/a.mkv",))


def test_log_is_appended_trimmed_and_read_back(tmp_path):
    log = tmp_path / "sub/wake.jsonl"
    for i in range(10):
        sysinfo.append_snapshot(log, snap(i, "standby"), 4)
    snaps = sysinfo.read_snapshots(log)
    assert [s.ts for s in snaps][-1] == 9
    assert len(snaps) <= 6
    log.write_text(log.read_text() + "half-written\n")
    assert len(sysinfo.read_snapshots(log)) == len(snaps)
    assert sysinfo.read_snapshots(tmp_path / "missing") == []


def test_hdparm_state_survives_a_missing_binary(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert sysinfo.hdparm_state("sda") == ""


def args(what, days=2.0):
    return argparse.Namespace(what=what, days=days)


def test_report_without_samples(host, tmp_path, capsys):
    wcfg = WakeConfig(str(tmp_path / "w.jsonl"), str(host), 1000)
    assert wake_cmd(args("report"), wcfg) == 1
    assert "No samples" in capsys.readouterr().out


def test_wake_sample_report_and_doctor(host, tmp_path, monkeypatch, capsys):
    real = sysinfo.take_snapshot
    monkeypatch.setattr(sysinfo, "hdparm_state", fake_hdparm)
    monkeypatch.setattr(sysinfo, "take_snapshot", lambda root, now: real(root, now, fake_hdparm))
    wcfg = WakeConfig(str(tmp_path / "w.jsonl"), str(host), 1000)
    assert wake_cmd(args("sample"), wcfg, now=1000) == 0
    assert wake_cmd(args("report"), wcfg) == 0
    assert "sda" in capsys.readouterr().out
    assert wake_doctor(wcfg) == 1  # sdb has no power state in the fake
    out = capsys.readouterr().out
    assert "spinning disks: sda, sdb" in out
    assert wake_cmd(args("doctor"), wcfg) == 1
    capsys.readouterr()
    bad = WakeConfig(str(tmp_path / "x"), str(tmp_path / "empty"), 1000)
    assert wake_cmd(args("sample"), bad, now=1) == 1
    assert "no spinning disks" in capsys.readouterr().err
    assert wake_doctor(bad) == 1
    unwritable = WakeConfig("/proc/forbidden/wake.jsonl", str(host), 1000)
    assert wake_cmd(args("sample"), unwritable, now=1) == 1
    assert "cannot write" in capsys.readouterr().err
