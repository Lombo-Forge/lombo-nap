# How it works

## Contents

- [Still watching?](#still-watching)
- [What counts as doing something](#what-counts-as-doing-something)
- [The wake report](#the-wake-report)
- [Limits of the wake report](#limits-of-the-wake-report)

## Still watching?

Every `LOMBO_NAP_POLL_SECONDS` (30 by default; every second while someone is being asked) the app reads
Jellyfin's session list. For each session playing a movie or episode it remembers when the person last did
something. When that was `LOMBO_NAP_LIMIT_HOURS` ago (or the same number of titles in a row has passed
`LOMBO_NAP_MAX_EPISODES`), it sends a message: "Still watching? Pause and play to keep going." If nothing
happens for `LOMBO_NAP_GRACE_SECONDS`, it sends Stop and then GoHome to that session, and (when a webhook is
set) tells it. A stopped session starts a fresh count the next time something plays.

In dry run all of this happens only in the log.

## What counts as doing something

Counts: pressing play or pause, starting a title by hand, a seek backwards, a big jump forward.
Does not count: autoplay into the next episode of the same show (the previous one was at least 60% done),
a forward jump of up to 3 minutes, a jump to the last 90 seconds, a jump onto the end of an intro, credits
or recap segment (read from Jellyfin's media segments, so skip-intro plugins are not mistaken for people).
A movie longer than the limit is allowed to finish. Users in `LOMBO_NAP_SKIP_USERS` are ignored.

A session that disappears for less than two minutes (between two episodes) keeps its count. With
`LOMBO_NAP_STATE_FILE` the counts are saved at every poll and picked up after a restart if younger than ten
minutes; positions are not saved, so the first poll after a restart only restores the clock.

## The wake report

`wake sample` runs on the host once a minute. It records, for every rotational disk (sysfs says so), the power
state from `hdparm -C`, the sectors read and written from `/proc/diskstats`, and the top processes by bytes moved
from `/proc/<pid>/io`, with their container (from the cgroup) and any files they hold open under that disk's
mount points. `wake report` compares neighbouring samples. A standby followed by active is a wake-up; the
processes whose counters grew between the two are the suspects, those holding files on that disk first.

## Limits of the wake report

- `/proc/<pid>/io` does not say which disk the bytes went to, so a suspect is a hint.
- A process that did its I/O and exited between two samples is not seen.
- A wake by the disk's own firmware, a SMART query or a file manager's thumbnails looks like any other process.
- Needs root to read other users' processes, and `hdparm` for the power state.
