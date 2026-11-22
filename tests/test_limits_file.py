"""The limits file: re-read every round, priority over the env list, damaged file handling."""

import json
import os

import pytest

from conftest import session
from lombo_nap import cli
from lombo_nap.cli import main
from lombo_nap.config import from_env
from lombo_nap.jellyfin import Jellyfin
from lombo_nap.limits import LimitsFile, LimitsFileError, parse

H = 3600.0


def doc(limits, version=1, **extra):
    return json.dumps({"version": version, "limits": limits, **extra})


def test_parse_case_decimal_clamp_and_unknown_fields():
    out = parse(doc({" Alice ": 2, "bob": 4.5, "carol": 99, "dan": 0.2}, future_field=True))
    assert out == {"alice": 2 * H, "bob": 4.5 * H, "carol": 6 * H, "dan": H}
    assert parse(doc({})) == {}


@pytest.mark.parametrize(
    "text",
    [
        "{nope",
        "[]",
        '{"limits": {}}',
        doc({}, version=2),
        doc({}, version=True),
        doc({}, version="1"),
        '{"version": 1}',
        '{"version": 1, "limits": []}',
        doc({"a": "2"}),
        doc({"a": True}),
        doc({"a": None}),
        doc({"": 2}),
        doc({"A": 2, "a": 3}),
        '{"version": 1, "limits": {"a": NaN}}',
        '{"version": 1, "limits": {"a": Infinity}}',
    ],
)
def test_parse_rejects_anything_unclear(text):
    with pytest.raises(LimitsFileError):
        parse(text)


def test_file_is_reread_and_a_damaged_one_keeps_the_last_good(tmp_path, capsys):
    p = tmp_path / "limits.json"
    lf = LimitsFile(str(p))
    lf.refresh()
    assert (lf.state, lf.limits) == ("missing", {})
    p.write_text(doc({"alice": 2}))
    lf.refresh()
    assert (lf.state, lf.limits) == ("ok", {"alice": 2 * H})
    p.write_text("{broken")
    lf.refresh()
    lf.refresh()
    assert (lf.state, lf.limits) == ("damaged", {"alice": 2 * H})
    assert capsys.readouterr().err.count("ignored") == 1  # one warning, not one per round
    p.write_text(doc({"alice": 5}))
    lf.refresh()
    assert (lf.state, lf.limits) == ("ok", {"alice": 5 * H})
    p.unlink()
    lf.refresh()
    assert (lf.state, lf.limits) == ("missing", {})


def test_unreadable_path_is_damaged_not_a_crash(tmp_path):
    lf = LimitsFile(str(tmp_path))  # a directory
    lf.refresh()
    assert (lf.state, lf.limits) == ("damaged", {})


def test_unset_means_off():
    lf = LimitsFile(None)
    lf.refresh()
    assert (lf.state, lf.limits) == ("off", {})


def test_a_new_hour_applies_without_a_restart_and_beats_the_env_list(env, fake, tmp_path):
    p = tmp_path / "limits.json"
    cfg = from_env({**env, "LOMBO_NAP_USER_LIMITS": "alice:1,carol:2", "LOMBO_NAP_LIMITS_FILE": str(p)})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    fake.sessions = [session("a", user="Alice", pos=0)]
    r.poll(0)
    assert r.user_limits() == {"alice": H, "carol": 2 * H}  # no file yet: the env list
    p.write_text(doc({"ALICE": 5}))
    fake.sessions = [session("a", user="Alice", pos=100)]
    assert r.poll(100) == []  # 100 s in, her env limit was 1 h; the file says 5 h
    assert r.user_limits() == {"alice": 5 * H, "carol": 2 * H}
    # not asked at 3.5 h with a 5 h file limit, asked at 5 h
    for t in range(200, int(5 * H) + 300, 100):
        fake.sessions = [session("a", user="Alice", pos=t)]
        acts = r.poll(t)
        if acts:
            assert t >= 5 * H
            break
    else:
        pytest.fail("never asked")


def test_damaged_file_at_start_falls_back_to_the_env_list(env, fake, tmp_path):
    p = tmp_path / "limits.json"
    p.write_text("junk")
    cfg = from_env({**env, "LOMBO_NAP_USER_LIMITS": "alice:2", "LOMBO_NAP_LIMITS_FILE": str(p)})
    r = cli.Runner(cfg, Jellyfin(fake.url, "good-key"), 0)
    r.poll(0)
    assert r.user_limits() == {"alice": 2 * H}


def test_doctor_reports_the_limits_file(env, fake, tmp_path, capsys):
    p = tmp_path / "limits.json"
    p.write_text(doc({"bob": 4}))
    e = {**env, "LOMBO_NAP_LIMITS_FILE": str(p)}
    assert main(["doctor"], e) == 0
    out = capsys.readouterr().out
    assert f"limits file: {p} (ok)" in out
    assert "own limits: bob 4 h" in out
    p.write_text("x")
    assert main(["doctor"], e) == 0
    assert "[warn] limits file" in capsys.readouterr().out
    assert os.path.exists(p)
