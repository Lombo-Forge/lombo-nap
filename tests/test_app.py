import json
import re
from pathlib import Path

import pytest

from conftest import session
from lombo_nap import cli, core, notify
from lombo_nap.cli import main
from lombo_nap.config import ConfigError, from_env, wake_from_env
from lombo_nap.jellyfin import Jellyfin, JellyfinError

ROOT = Path(__file__).resolve().parent.parent
LIVE = {"LOMBO_NAP_DRY_RUN": "false", "LOMBO_NAP_LIMIT_HOURS": "1", "LOMBO_NAP_GRACE_SECONDS": "10"}


def test_config_defaults_are_safe(env):
    cfg = from_env(env)
    assert cfg.dry_run is True
    assert (cfg.poll_seconds, cfg.limit_hours, cfg.grace_seconds, cfg.max_episodes) == (30, 3, 120, 0)
    assert cfg.state_file is None


def test_config_reads_lists_and_wake_settings(env):
    cfg = from_env({**env, "LOMBO_NAP_SKIP_USERS": " Alice, bob ,", "LOMBO_NAP_STATE_FILE": "state.json"})
    assert cfg.skip_users == {"alice", "bob"}
    assert cfg.state_file == "state.json"
    w = wake_from_env({})
    assert (w.host_root, w.keep_lines) == ("/", 100000)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOMBO_NAP_JELLYFIN_URL", "jellyfin:8096"),
        ("LOMBO_NAP_JELLYFIN_API_KEY", "changeme"),
        ("LOMBO_NAP_WEBHOOK_URL", "ftp://x"),
        ("LOMBO_NAP_POLL_SECONDS", "1"),
        ("LOMBO_NAP_LIMIT_HOURS", "9"),
        ("LOMBO_NAP_GRACE_SECONDS", "soon"),
        ("LOMBO_NAP_MAX_EPISODES", "-1"),
    ],
)
def test_config_rejects_bad_values_and_names_the_setting(env, name, value):
    with pytest.raises(ConfigError, match=name):
        from_env({**env, name: value})


def test_wake_settings_are_validated():
    with pytest.raises(ConfigError, match="LOMBO_NAP_WAKE_KEEP_LINES"):
        wake_from_env({"LOMBO_NAP_WAKE_KEEP_LINES": "5"})


def test_env_example_lists_every_setting_and_only_those():
    used = set(re.findall(r'"([A-Z_]+)"', (ROOT / "src/lombo_nap/config.py").read_text())) - {"LOMBO_NAP_"}
    declared = set(re.findall(r"^LOMBO_NAP_([A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert declared == used
    assert {"DRY_RUN", "LIMIT_HOURS", "WAKE_LOG", "HOST_ROOT", "SKIP_USERS"} <= declared
    # the shipped example is itself valid once the key is filled in
    example = dict(re.findall(r"^(LOMBO_NAP_[A-Z_]+)=(.*)$", (ROOT / ".env.example").read_text(), re.M))
    assert from_env({**example, "LOMBO_NAP_JELLYFIN_API_KEY": "k"}).dry_run is True


def test_client_sends_the_key_and_reports_failures(fake):
    jf = Jellyfin(fake.url, "good-key")
    assert jf.sessions()[0]["Id"] == "s1"
    assert fake.requests[-1]["auth"] == 'MediaBrowser Token="good-key"'
    assert jf.segment_ends("e1") == [90.0]
    assert jf.segment_ends("unknown-item") == []
    jf.message("s1", "H", "T", 5000)
    jf.stop("s1")
    jf.go_home("s1")
    assert fake.posts()[0]["body"] == {"Header": "H", "Text": "T", "TimeoutMs": 5000}
    assert fake.commands() == ["/Sessions/s1/Message", "/Sessions/s1/Playing/Stop", "/Sessions/s1/Command/GoHome"]
    with pytest.raises(JellyfinError, match="HTTP 401"):
        Jellyfin(fake.url, "wrong").info()
    with pytest.raises(JellyfinError):
        Jellyfin("http://127.0.0.1:1", "k", timeout=1).public_info()


def test_notify_posts_json(fake):
    notify.send(fake.url + "/hook", "hello")
    assert fake.posts()[0]["body"] == {"content": "hello", "text": "hello"}
    with pytest.raises(notify.NotifyError):
        notify.send("http://127.0.0.1:1/hook", "x", timeout=1)


def test_doctor_passes_and_fails(env, fake, capsys):
    assert main(["doctor"], env) == 0
    assert "[FAIL]" not in capsys.readouterr().out
    assert main(["doctor"], {**env, "LOMBO_NAP_JELLYFIN_API_KEY": "wrong"}) == 1
    assert "API key accepted: /System/Info: HTTP 401" in capsys.readouterr().out


def test_bad_settings_exit_2(capsys):
    assert main(["plan"], {}) == 2
    assert "LOMBO_NAP_JELLYFIN_URL" in capsys.readouterr().err
    assert main(["wake", "report"], {"LOMBO_NAP_WAKE_KEEP_LINES": "x"}) == 2


def test_plan_never_posts(env, fake, capsys):
    assert main(["plan"], {**env, **LIVE}) == 0
    out = capsys.readouterr().out
    assert "alice on Living room TV (Some Show - Pilot): no interaction for 0 min" in out
    assert "would be asked in 60 min" in out
    assert fake.posts() == []
    fake.sessions = []
    assert main(["plan"], env) == 0
    assert "Nobody is playing" in capsys.readouterr().out


def tick(r, fake, t):
    """One poll at time t, with the playing position moved on by the same amount (normal playback)."""
    last = getattr(r, "last", None)
    for x in sorted({*range((last or 0) + 100, t, 100), t}) if last is not None else [t]:
        fake.sessions = [session(pos=x)]
        cli.run_once(r, x)
    r.last = t


def test_dry_run_logs_but_sends_nothing(env, fake, capsys, tmp_path):
    cfg = from_env({**env, **LIVE, "LOMBO_NAP_DRY_RUN": "true"})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    tick(r, fake, 0)
    tick(r, fake, 3600)
    assert "[dry run] would show" in capsys.readouterr().out
    assert fake.commands() == []


def test_live_run_asks_then_stops_and_tells_the_webhook(env, fake, capsys, tmp_path):
    state = tmp_path / "state.json"
    cfg = from_env({**env, **LIVE, "LOMBO_NAP_STATE_FILE": str(state)})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    tick(r, fake, 0)
    assert fake.commands() == []
    tick(r, fake, 3600)
    assert fake.commands() == ["/Sessions/s1/Message"]
    assert fake.posts()[0]["body"]["TimeoutMs"] == 10_000
    tick(r, fake, 3700)
    assert fake.commands()[1:] == ["/Sessions/s1/Playing/Stop", "/Sessions/s1/Command/GoHome"]
    assert "Living room TV" in fake.posts()[-1]["body"]["content"]
    assert json.loads(state.read_text())["tracks"] == {}
    capsys.readouterr()
    # a second app instance picks the saved counts up again
    r2 = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 3700)
    assert r2.tracks == {}
    state.write_text(json.dumps(core.dump_tracks(r.tracks | {"x": core.Track("e", "s", 1, 1, False, 0, 0)}, 3700)))
    assert "x" in cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 3710).tracks
    state.write_text("junk")
    assert cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 3710).tracks == {}


def test_a_failed_stop_is_not_reported_as_done_and_is_retried(env, fake, capsys):
    fake.fail_stop = True
    cfg = from_env({**env, **LIVE})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    for t in (0, 3600, 3700):
        tick(r, fake, t)
    assert "[FAIL] stop playback" in capsys.readouterr().err
    assert "/Sessions/s1/Command/GoHome" not in fake.commands()  # still playing: no go-home
    alert = fake.posts()[-1]["body"]["content"]
    assert "Could not stop" in alert
    assert "Stopped unattended" not in alert
    assert "s1" in r.tracks  # kept, already asked: eligible for a retry
    assert r.tracks["s1"].prompted_at is not None
    fake.fail_stop = False
    tick(r, fake, 3740)  # one poll later the stop goes through
    assert fake.commands()[-2:] == ["/Sessions/s1/Playing/Stop", "/Sessions/s1/Command/GoHome"]
    assert fake.commands().count("/Sessions/s1/Playing/Stop") == 2
    assert fake.posts()[-1]["body"]["content"].startswith("Stopped unattended")
    assert r.tracks == {}


def test_state_file_that_cannot_be_written_only_warns(env, fake, capsys):
    cfg = from_env({**env, "LOMBO_NAP_STATE_FILE": "/proc/nope/state.json"})
    cli.run_once(cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0), 0)
    assert "could not save" in capsys.readouterr().err


def test_run_exits_and_loop_survives_a_bad_round(env, fake, capsys):
    assert main(["run"], env) == 0
    bad = {**env, "LOMBO_NAP_JELLYFIN_API_KEY": "wrong"}
    assert main(["run"], bad) == 1
    assert "HTTP 401" in capsys.readouterr().err
    r = cli.Runner(from_env(bad), Jellyfin(fake.url, "wrong"), 0)
    pauses: list[float] = []

    def stop_after_two(seconds: float) -> None:
        pauses.append(seconds)
        if len(pauses) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cli.run_loop(r, True, stop_after_two)
    assert pauses == [30.0, 30.0]


def test_main_reports_a_jellyfin_error_from_plan(env, capsys):
    assert main(["plan"], {**env, "LOMBO_NAP_JELLYFIN_API_KEY": "wrong"}) == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_session_helper_matches_what_core_reads():
    assert core.observe(session())["label"] == "alice on Living room TV (Some Show - Pilot)"


def test_the_state_file_is_written_atomically(env, fake, tmp_path):
    state = tmp_path / "state.json"
    cfg = from_env({**env, "LOMBO_NAP_STATE_FILE": str(state)})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    r.poll(0)
    r.save(0)
    assert json.loads(state.read_text())["tracks"]
    assert not (tmp_path / "state.json.tmp").exists()


def test_a_failing_jellyfin_is_retried_at_the_poll_pace_not_every_second(env, fake):
    cfg = from_env({**env, "LOMBO_NAP_LIMIT_HOURS": "1"})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    r.tracks = {"s1": core.Track("e1", "show", None, 1500, False, 0, 0, prompted_at=0.0, user="alice")}
    fake.key = "rotated"  # every call now fails
    slept: list[float] = []

    def stop_after_two(s: float) -> None:
        slept.append(s)
        if len(slept) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cli.run_loop(r, True, stop_after_two)
    assert slept == [30.0, 30.0]
