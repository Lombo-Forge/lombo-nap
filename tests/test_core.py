"""The decisions: who is unattended, when to ask, when to stop. No network, no clock."""

from conftest import session
from lombo_nap import core

H = 3600.0
LIMIT, GRACE = 3 * H, 120.0


def poll(tracks, sessions, now, **kw):
    return core.step(tracks, sessions, now, LIMIT, GRACE, **kw)


def watch(tracks, start, end, every=60, **kw):
    """Poll once per `every` seconds from start to end while the show plays on (position = time)."""
    actions = []
    t = start
    while t <= end:
        tracks, acts = poll(tracks, [session(pos=t, **kw)], t)
        actions += acts
        t += every
    return tracks, actions


def kinds(actions):
    return [a.kind for a in actions]


def only(tracks):
    return next(iter(tracks.values()))


def test_asked_at_the_limit_then_stopped_after_the_grace():
    tracks, acts = watch({}, 0, LIMIT - 60)
    assert acts == []
    tracks, acts = watch(tracks, LIMIT, LIMIT + 60)
    assert kinds(acts) == ["message"]  # asked once, not at every poll
    tracks, acts = watch(tracks, LIMIT + 120, LIMIT + 120)
    assert kinds(acts) == ["stop", "home"]
    assert tracks == {}  # a fresh count when something plays again


def test_pause_and_play_answers_the_question():
    tracks, acts = watch({}, 0, LIMIT)
    assert kinds(acts) == ["message"]
    tracks, _ = poll(tracks, [session(pos=LIMIT + 5, paused=True)], LIMIT + 5)
    assert only(tracks).prompted_at is None
    tracks, acts = watch(tracks, LIMIT + 6, LIMIT + 6 + GRACE + 60)
    assert acts == []  # the count restarted at the pause


def test_autoplay_is_not_an_interaction_but_a_hand_picked_title_is():
    tracks, _ = poll({}, [session(item="e1", pos=1400)], 0)
    tracks, _ = poll(tracks, [session(item="e2", pos=5)], 100)
    assert (only(tracks).quiet_since, only(tracks).episodes) == (0, 2)
    tracks, _ = poll(tracks, [session(item="m9", series="other", pos=5)], 200)
    assert (only(tracks).quiet_since, only(tracks).episodes) == (200, 1)


def test_asked_after_n_episodes_in_a_row():
    tracks, _ = poll({}, [session(item="e1", pos=1400)], 0, max_episodes=2)
    tracks, _ = poll(tracks, [session(item="e2", pos=1400)], 100, max_episodes=2)
    tracks, acts = poll(tracks, [session(item="e3", pos=5)], 200, max_episodes=2)
    assert kinds(acts) == ["message"]


def test_seeks_count_and_automatic_skips_do_not():
    base = session(pos=100, runtime=3000)
    tracks, _ = poll({}, [base], 0)
    tracks, _ = poll(tracks, [session(pos=200, runtime=3000)], 10)  # 90 s skip: intro skipper
    assert only(tracks).quiet_since == 0
    tracks, _ = poll(tracks, [session(pos=1200, runtime=3000)], 20, segments={"e1": [1195.0]})  # on a segment end
    assert only(tracks).quiet_since == 0
    tracks, _ = poll(tracks, [session(pos=2000, runtime=3000)], 30)  # a big jump forward by hand
    assert only(tracks).quiet_since == 30
    tracks, _ = poll(tracks, [session(pos=100, runtime=3000)], 40)  # back
    assert only(tracks).quiet_since == 40
    tracks, _ = poll({}, [base], 0)
    tracks, _ = poll(tracks, [session(pos=2950, runtime=3000)], 20)  # lands near the end: outro skip
    assert only(tracks).quiet_since == 0


def test_a_long_movie_may_finish_but_a_paused_one_is_not_heading_for_its_end():
    long = {"kind": "Movie", "item": "m1", "series": "", "runtime": int(4 * H)}
    _, acts = watch({}, 0, LIMIT + 600, **long)
    assert acts == []  # past the limit, but the film is allowed to finish
    _, acts = watch({}, 0, LIMIT, paused=True, **long)
    assert kinds(acts) == ["message"]


def test_skipped_users_and_non_video_sessions_are_ignored():
    music = session(sid="m")
    music["NowPlayingItem"]["Type"] = "Audio"
    sessions = [music, session(sid="x", user="Alice"), {"UserName": "bob"}]
    tracks, acts = poll({}, sessions, 0, skip_users=frozenset({"alice"}))
    assert tracks == {}
    assert acts == []


def test_a_session_that_vanishes_between_episodes_keeps_its_count_for_a_while():
    tracks, _ = poll({}, [session()], 0)
    tracks, _ = poll(tracks, [], core.RETAIN - 1)
    assert len(tracks) == 1
    tracks, _ = poll(tracks, [], core.RETAIN + 1)
    assert tracks == {}


def test_wait_summary_and_action_text():
    tracks, _ = poll({}, [session(pos=0)], 0)
    assert core.wait_seconds(tracks, 30) == 30
    assert "would be asked in 180 min" in core.summary(tracks, LIMIT, 0)[0]
    tracks, acts = watch(tracks, 60, LIMIT)
    assert core.wait_seconds(tracks, 30) == 1.0
    assert "asked, waiting" in core.summary(tracks, LIMIT, LIMIT)[0]
    assert str(acts[0]).startswith('show "Still watching?" on alice on Living room TV (Some Show - Pilot)')
    assert str(core.Action("stop", "s", "x")) == "stop playback on x"
    assert str(core.Action("home", "s", "x")) == "send to the home screen: x"


def test_saved_counts_survive_a_restart_but_not_a_long_outage():
    tracks, _ = poll({}, [session(pos=100)], 0)
    saved = core.dump_tracks(tracks, 50)
    t = only(core.load_tracks(saved, 100))
    assert (t.pos, t.quiet_since, t.label) == (None, 0, "alice on Living room TV (Some Show - Pilot)")
    assert core.load_tracks(saved, 50 + core.RESTORE_MAX + 1) == {}
    assert core.load_tracks({"at": 1}, 2) == {}
    assert core.load_tracks("junk", 2) == {}
