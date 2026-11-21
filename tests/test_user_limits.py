"""Per-person limits: parsing, the 1 to 6 hour range, the fallback, case, and the decisions."""

import pytest

from conftest import session
from lombo_nap import cli, core
from lombo_nap.cli import main
from lombo_nap.config import ConfigError, from_env
from lombo_nap.jellyfin import Jellyfin

H = 3600.0
LIMIT, GRACE = 3 * H, 120.0


def test_parse_case_decimal_and_clamp(env):
    cfg = from_env({**env, "LOMBO_NAP_USER_LIMITS": " Alice:2, bob:4.5 ,carol:99,dan:0.2,"})
    assert cfg.user_limits == {"alice": 7200.0, "bob": 16200.0, "carol": 6 * H, "dan": H}
    assert from_env(env).user_limits == {}


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        ("alice", "alice"),
        ("alice:", "alice:"),
        (":2", ":2"),
        ("alice:two", "alice:two"),
        ("a:2,b:nan", "b:nan"),
        ("a:inf", "a:inf"),
    ],
)
def test_reject_malformed_entries_and_name_the_entry(env, value, bad):
    with pytest.raises(ConfigError, match=f"LOMBO_NAP_USER_LIMITS entry '{bad}'"):
        from_env({**env, "LOMBO_NAP_USER_LIMITS": value})


def test_reject_duplicates_in_any_case(env):
    with pytest.raises(ConfigError, match="more than once"):
        from_env({**env, "LOMBO_NAP_USER_LIMITS": "alice:2,ALICE:3"})


def test_the_global_limit_keeps_its_range(env):
    with pytest.raises(ConfigError, match="LOMBO_NAP_LIMIT_HOURS"):
        from_env({**env, "LOMBO_NAP_LIMIT_HOURS": "7"})


def test_doctor_and_plan_show_each_limit(env, fake, capsys):
    env = {**env, "LOMBO_NAP_USER_LIMITS": "alice:2"}
    assert main(["doctor"], env) == 0
    assert "limits: 3 h for everyone else; own limits: alice 2 h" in capsys.readouterr().out
    assert main(["plan"], env) == 0
    out = capsys.readouterr().out
    assert "Limits: 3 h for everyone else; own limits: alice 2 h" in out
    assert "would be asked in 120 min (limit 2 h)" in out


def test_core_uses_the_person_limit_and_the_default():
    tracks: dict[str, core.Track] = {}
    asked: list[tuple[str, str]] = []
    for t in range(0, int(H) + 1, 100):  # a poll every 100 s, playback moving on normally
        sessions = [session("a", user="Alice", item="e1", pos=t), session("b", user="bob", item="e2", pos=t)]
        tracks, acts = core.step(tracks, sessions, t, LIMIT, GRACE, user_limits={"alice": H})
        asked += [(a.kind, a.session_id) for a in acts]
    assert asked == [("message", "a")]
    assert tracks["b"].prompted_at is None
    assert core.limit_for("ALICE", LIMIT, {"alice": H}) == H
    assert core.limit_for("bob", LIMIT, {"alice": H}) == LIMIT
    assert core.limit_for("bob", LIMIT, None) == LIMIT


def test_the_user_survives_a_restart_so_the_limit_still_applies():
    tracks, _ = core.step({}, [session(user="Alice")], 0, LIMIT, GRACE)
    assert core.load_tracks(core.dump_tracks(tracks, 0), 10)["s1"].user == "Alice"


def test_runner_asks_the_limited_person_first(env, fake):
    cfg = from_env({**env, "LOMBO_NAP_USER_LIMITS": "ALICE:1"})  # everyone else: 3 h
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    asked: list[str] = []
    for t in range(0, 3701, 100):
        fake.sessions = [session("a", user="Alice", item="e1", pos=t), session("b", user="bob", item="e2", pos=t)]
        asked += [a.session_id for a in r.poll(t) if a.kind == "message"]
    assert asked == ["a"]
    assert r.tracks["b"].prompted_at is None
