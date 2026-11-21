"""Command line. Talks to the outside world; core.py and wake.py decide.

lombo-nap doctor                 check the settings and that Jellyfin answers; exit 1 on any failure
lombo-nap plan                   show who is playing and what would happen; changes nothing, ever
lombo-nap run [--loop]           ask "Still watching?" and stop (only when DRY_RUN=false)
lombo-nap wake sample            record the disks' power state and process I/O (every minute, as root)
lombo-nap wake report [--days N] what woke the disks
lombo-nap wake doctor            check that the host gives the wake report what it needs
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, core, notify, sysinfo, wake
from .config import Config, ConfigError, WakeConfig, from_env, wake_from_env
from .jellyfin import Jellyfin, JellyfinError


class Runner:
    """What lives between polls: the per-session counts and the cached segment ends."""

    def __init__(self, cfg: Config, jf: Jellyfin, now: float):
        self.cfg, self.jf = cfg, jf
        self.segs: dict[str, list[float]] = {}
        self.tracks = self._load(now)
        self.prev_tracks: dict[str, core.Track] = {}  # the tracks before the last poll (step drops a stopped one)

    def _load(self, now: float) -> dict[str, core.Track]:
        if not self.cfg.state_file:
            return {}
        try:
            return core.load_tracks(json.loads(Path(self.cfg.state_file).read_text()), now)
        except (OSError, ValueError):
            return {}

    def save(self, now: float) -> None:
        if self.cfg.state_file:
            try:
                Path(self.cfg.state_file).write_text(json.dumps(core.dump_tracks(self.tracks, now)))
            except OSError as e:
                print(f"[warn] could not save {self.cfg.state_file}: {e}", file=sys.stderr)

    def poll(self, now: float) -> list[core.Action]:
        """Read the sessions and update the counts. Sends nothing."""
        sessions = [s for s in self.jf.sessions() if s.get("NowPlayingItem")]
        for s in sessions:
            item = (s["NowPlayingItem"]).get("Id")
            if item and item not in self.segs:
                self.segs[item] = self.jf.segment_ends(item)
        if len(self.segs) > 500:
            self.segs.clear()
        self.prev_tracks = dict(self.tracks)
        self.tracks, actions = core.step(
            self.tracks,
            sessions,
            now,
            self.cfg.limit_hours * 3600.0,
            float(self.cfg.grace_seconds),
            self.segs,
            self.cfg.max_episodes,
            self.cfg.skip_users,
        )
        return actions

    def send(self, a: core.Action) -> None:
        if a.kind == "message":
            self.jf.message(a.session_id, core.MESSAGE_HEADER, core.MESSAGE_TEXT, self.cfg.grace_seconds * 1000)
        elif a.kind == "stop":
            self.jf.stop(a.session_id)
        else:
            self.jf.go_home(a.session_id)


def doctor(cfg: Config) -> int:
    jf = Jellyfin(cfg.jellyfin_url, cfg.jellyfin_api_key)
    ok = True

    def reachable() -> str:
        info = jf.public_info()
        return f"{info.get('ServerName')} {info.get('Version')}"

    def key_accepted() -> str:
        jf.info()
        return "yes"

    def sessions() -> str:
        return f"{len(jf.sessions())} session(s) right now"

    checks: list[tuple[str, Callable[[], str]]] = [
        ("Jellyfin reachable", reachable),
        ("API key accepted", key_accepted),
        ("sessions readable", sessions),
    ]
    for label, check in checks:
        try:
            print(f"[ ok ] {label}: {check()}")
        except JellyfinError as e:
            print(f"[FAIL] {label}: {e}")
            ok = False
    print(f"[ ok ] webhook: {'set' if cfg.webhook_url else 'not set (alerts are skipped)'}")
    print(f"[ ok ] state file: {cfg.state_file or 'not set (counts restart with the app)'}")
    print(f"[ ok ] mode: {'dry run (nothing is sent or stopped)' if cfg.dry_run else 'LIVE'}")
    return 0 if ok else 1


def plan(cfg: Config, now: float | None = None) -> int:
    now = time.time() if now is None else now
    r = Runner(cfg, Jellyfin(cfg.jellyfin_url, cfg.jellyfin_api_key), now)
    actions = r.poll(now)
    lines = core.summary(r.tracks, cfg.limit_hours * 3600.0, now) + [str(a) for a in actions]
    print("\n".join(lines) or "Nobody is playing a movie or episode.")
    print("(a plan sees one moment: counting starts when the app first sees a session)")
    return 0


def run_once(r: Runner, now: float) -> None:
    actions = r.poll(now)
    stopped: list[str] = []
    failed: dict[str, str] = {}  # session id -> label, for stops that did not go through
    for a in actions:
        if r.cfg.dry_run:
            print(f"[dry run] would {a}")
            continue
        if a.kind == "home" and a.session_id in failed:
            continue  # the playback is still running: do not pull the screen away
        try:
            r.send(a)
            print(f"[sent] {a}")
            if a.kind == "stop":
                stopped.append(a.label)
        except JellyfinError as e:
            print(f"[FAIL] {a}: {e}", file=sys.stderr)  # one client failing must not stop the others
            if a.kind == "stop":
                failed[a.session_id] = a.label
                t = r.prev_tracks.get(a.session_id)
                if t:  # keep the session, asked already, and try the stop again after one poll
                    t.prompted_at = now + r.cfg.poll_seconds - r.cfg.grace_seconds
                    r.tracks[a.session_id] = t
    if r.cfg.webhook_url and (stopped or failed):
        parts = ["Stopped unattended playback:\n" + "\n".join(stopped)] if stopped else []
        if failed:
            parts.append("Could not stop (will try again):\n" + "\n".join(failed.values()))
        notify.send(r.cfg.webhook_url, "\n\n".join(parts))
    r.save(now)


def run_loop(r: Runner, loop: bool, sleep: Callable[[float], None] = time.sleep) -> int:
    while True:
        try:
            run_once(r, time.time())
        except (JellyfinError, notify.NotifyError) as e:
            print(f"[FAIL] {e}", file=sys.stderr)  # a loop survives one bad round
            if not loop:
                return 1
        if not loop:
            return 0
        sleep(core.wait_seconds(r.tracks, float(r.cfg.poll_seconds)))


# ------------------------------------------------------------------ the wake report
def wake_cmd(args: argparse.Namespace, wcfg: WakeConfig, now: float | None = None) -> int:
    root, log = Path(wcfg.host_root), Path(wcfg.log_file)
    if args.what == "sample":
        snap = sysinfo.take_snapshot(root, int(time.time() if now is None else now), prev=sysinfo.last_snapshot(log))
        if not snap.disks:
            print("[warn] no spinning disks found (rotational flag in sysfs); nothing recorded", file=sys.stderr)
            return 1
        try:
            sysinfo.append_snapshot(log, snap, wcfg.keep_lines)
        except OSError as e:
            print(f"[FAIL] cannot write {log}: {e}", file=sys.stderr)
            return 1
        return 0
    if args.what == "report":
        if not log.exists():
            print(f"No samples at {log} yet. Run `lombo-nap wake sample` every minute.")
            return 1
        print(wake.report_text(sysinfo.read_snapshots(log), args.days))
        return 0
    return wake_doctor(wcfg)


def wake_doctor(wcfg: WakeConfig) -> int:
    root = Path(wcfg.host_root)
    disks = sysinfo.spinning_disks(root)
    ok = bool(disks)
    print(f"[{' ok ' if disks else 'FAIL'}] spinning disks: {', '.join(disks) or 'none found'}")
    states = {d: wake.parse_hdparm(sysinfo.hdparm_state(d)) for d in disks}
    unknown = [d for d, s in states.items() if s == wake.UNKNOWN]
    if disks:
        print(f"[{'warn' if unknown else ' ok '}] power state (hdparm -C): {states}")
        ok = ok and not unknown
    readable = sum(1 for p in (root / "proc").glob("[0-9]*/io") if os.access(p, os.R_OK))
    print(f"[{' ok ' if readable > 1 else 'warn'}] process I/O readable for {readable} process(es) (needs root)")
    print(f"[ ok ] log file: {wcfg.log_file}")
    return 0 if ok else 1


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lombo-nap", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("plan")
    run = sub.add_parser("run")
    run.add_argument("--loop", action="store_true")
    w = sub.add_parser("wake")
    w.add_argument("what", choices=["sample", "report", "doctor"])
    w.add_argument("--days", type=float, default=2.0)
    args = p.parse_args(argv)
    environ: dict[str, str] = dict(os.environ) if env is None else env

    try:
        if args.cmd == "wake":
            return wake_cmd(args, wake_from_env(environ))
        cfg = from_env(environ)
    except ConfigError as e:
        print(f"[FAIL] settings: {e}", file=sys.stderr)
        return 2

    try:
        if args.cmd == "doctor":
            return doctor(cfg)
        if args.cmd == "plan":
            return plan(cfg)
        runner = Runner(cfg, Jellyfin(cfg.jellyfin_url, cfg.jellyfin_api_key), time.time())
        return run_loop(runner, args.loop)
    except JellyfinError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
