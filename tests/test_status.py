"""The status document and `lombo-nap status`."""

import json

import pytest

from conftest import session
from lombo_nap import cli, status
from lombo_nap.cli import main
from lombo_nap.config import from_env
from lombo_nap.jellyfin import Jellyfin, JellyfinError


def runner(env, fake, tmp_path, **more):
    cfg = from_env({**env, "LOMBO_NAP_STATUS_FILE": str(tmp_path / "status.json"), **more})
    return cfg, cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)


def test_run_writes_the_document_every_round_in_dry_run_too(env, fake, tmp_path):
    _cfg, r = runner(env, fake, tmp_path, LOMBO_NAP_USER_LIMITS="alice:2")
    fake.sessions = [session("b", user="bob", pos=1), session("a", user="Alice", pos=1), {"Id": "idle"}]
    cli.run_once(r, 600.0)
    doc = json.loads((tmp_path / "status.json").read_text())
    assert doc == {
        "version": 1,
        "updated": 600,
        "dry_run": True,
        "limit_hours": 3,
        "grace_seconds": 120,
        "poll_seconds": 30,
        "limits_file": "off",
        "limits": {"alice": 2.0},
        "sessions": [
            {
                "user": "Alice",
                "label": "Alice on Living room TV (Some Show - Pilot)",
                "paused": False,
                "state": "counting",
                "quiet_seconds": 0,
                "titles_in_row": 1,
                "limit_seconds": 7200,
                "limit_source": "own",
                "ask_in_seconds": 7200,
                "stop_in_seconds": None,
            },
            {
                "user": "bob",
                "label": "bob on Living room TV (Some Show - Pilot)",
                "paused": False,
                "state": "counting",
                "quiet_seconds": 0,
                "titles_in_row": 1,
                "limit_seconds": 10800,
                "limit_source": "default",
                "ask_in_seconds": 10800,
                "stop_in_seconds": None,
            },
        ],
    }
    assert (tmp_path / "status.json").stat().st_mode & 0o777 == 0o644
    assert not (tmp_path / "status.json.tmp").exists()


def test_an_asked_session_shows_the_time_left_to_answer(env, fake, tmp_path):
    _cfg, r = runner(env, fake, tmp_path, LOMBO_NAP_LIMIT_HOURS="1")
    for t in range(0, 3701, 100):
        fake.sessions = [session("a", pos=t)]
        r.poll(t)
    row = status.build(
        r.tracks,
        3700.0,
        dry_run=True,
        limit_hours=1,
        grace_seconds=120,
        poll_seconds=30,
        user_limits={},
        limits_file="off",
    )["sessions"][0]
    assert row["state"] == "asked"
    assert row["ask_in_seconds"] is None
    assert 0 < row["stop_in_seconds"] <= 120


def test_no_setting_no_file(env, fake, tmp_path):
    cfg = from_env(env)
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    cli.run_once(r, 1.0)
    assert list(tmp_path.iterdir()) == []


def test_a_status_file_that_cannot_be_written_only_warns(env, fake, tmp_path, capsys):
    cfg = from_env({**env, "LOMBO_NAP_STATUS_FILE": str(tmp_path / "no" / "such" / "status.json")})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    cli.run_once(r, 1.0)
    assert "could not write" in capsys.readouterr().err


def test_a_failed_round_leaves_the_old_file(env, fake, tmp_path):
    _cfg, r = runner(env, fake, tmp_path)
    cli.run_once(r, 1.0)
    before = (tmp_path / "status.json").read_text()
    fake.key = "rotated"
    with pytest.raises(JellyfinError):
        cli.run_once(r, 2.0)
    assert (tmp_path / "status.json").read_text() == before


def test_status_command_prints_the_document_or_a_summary(env, fake, tmp_path, capsys):
    e = {**env, "LOMBO_NAP_STATUS_FILE": str(tmp_path / "status.json")}
    assert main(["status", "--json"], e) == 1  # nothing written yet
    assert "no readable status document" in capsys.readouterr().err
    _cfg, r = runner(env, fake, tmp_path)
    cli.run_once(r, 600.0)
    assert main(["status", "--json"], e) == 0
    assert json.loads(capsys.readouterr().out)["sessions"][0]["user"] == "alice"
    assert main(["status"], e) == 0
    out = capsys.readouterr().out
    assert "asked in 180 min (limit 3 h)" in out
    assert "(dry run)" in out


def test_status_command_errors(env, tmp_path, capsys):
    assert main(["status"], env) == 1
    assert "LOMBO_NAP_STATUS_FILE is not set" in capsys.readouterr().err
    p = tmp_path / "status.json"
    e = {**env, "LOMBO_NAP_STATUS_FILE": str(p)}
    p.write_text(json.dumps({"version": 2}))
    assert main(["status", "--json"], e) == 1
    assert "not understood" in capsys.readouterr().err
    p.write_text("[1]")
    assert main(["status"], e) == 1


def test_status_command_with_nobody_playing(env, fake, tmp_path, capsys):
    fake.sessions = []
    _cfg, r = runner(env, fake, tmp_path)
    cli.run_once(r, 5.0)
    assert main(["status"], {**env, "LOMBO_NAP_STATUS_FILE": str(tmp_path / "status.json")}) == 0
    assert "Nobody is playing" in capsys.readouterr().out
