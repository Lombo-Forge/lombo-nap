# How it is built

## Contents

- [The shape](#the-shape)
- [Contracts](#contracts)
- [Why it is split this way](#why-it-is-split-this-way)
- [Safe by default](#safe-by-default)
- [Settings](#settings)
- [Alerts](#alerts)
- [Adding a Jellyfin call](#adding-a-jellyfin-call)

## The shape

```
Jellyfin  <--  jellyfin.py  -->  cli.py (Runner)  -->  core.py (decides)
                                      |
                                      +-->  notify.py  -->  your webhook

/proc, /sys, hdparm  <--  sysinfo.py  -->  cli.py (wake)  -->  wake.py (parses, attributes)
                                                |
                                                +-->  the wake log (one JSON line per sample)
```

`core.py` and `wake.py` never touch the network, the disk, a process or the clock: they take text or
plain values and return plain values. `jellyfin.py`, `sysinfo.py` and `notify.py` do the I/O. `cli.py`
joins them and is the only place that prints.

## Contracts

Names that other code and tests rely on.

| Function | Takes | Returns |
|---|---|---|
| `core.step(tracks, sessions, now, limit, grace, segments, max_episodes, skip_users, user_limits)` | the last poll's `Track`s, Jellyfin's `/Sessions` list, the time in seconds | `(new tracks, [Action])`. An `Action` is `message`, `stop` or `home` for one session. It sends nothing. |
| `core.deadline(track, limit, now)` | one track | when it is due its prompt (a long movie is allowed to finish) |
| `limits.parse(text)` | the limits file's text | `{lower-case name: seconds}`, or raises `LimitsFileError`. `LimitsFile.refresh()` re-reads and keeps the last good contents. |
| `status.build(tracks, now, ...)` | the tracks and the settings in force | the status document (a dict); `status.write` stores it atomically |
| `core.dump_tracks` / `load_tracks` | tracks, time | a JSON-able dict, and back. Old or malformed data gives `{}`. |
| `wake.parse_diskstats(text)` | `/proc/diskstats` | `{disk: (sectors read, sectors written)}` |
| `wake.parse_mounts(text)`, `mounts_by_disk` | `/proc/mounts` | mount points per whole disk |
| `wake.parse_hdparm(text)` | `hdparm -C` output | `standby`, `active` or `unknown` |
| `wake.parse_container`, `parse_proc_io` | cgroup text, io text | a 12-character container id or `""`; `(read_bytes, write_bytes)` |
| `wake.find_wakes(prev, cur)` | two `Snapshot`s | `[Wake]`: disks that went standby to active, with ranked suspects |
| `wake.report_text(snapshots, days)` | all snapshots | the report |
| `sysinfo.take_snapshot(root, now, state_of)` | host root, time, a function giving hdparm text | a `Snapshot` (fake roots and fake `state_of` in tests) |

The wake log is one line per sample: `{"ts":..., "disks":{name:[state, sectors_read, sectors_written, [mounts]]},
"procs":{pid:[comm, container, read_bytes, write_bytes, [paths]]}}`. Unreadable lines are skipped.

## Why it is split this way

Rules are the part that changes most and breaks most quietly. Because `step()` takes plain data and
returns plain data, a test is a few lines and needs no server or clock. The I/O layers are thin and are
tested against a fake Jellyfin on localhost (`tests/conftest.py`) and a fake `/proc` tree in `tmp_path`.

## Safe by default

- `DRY_RUN` is true until the person sets it to false. In dry run `run` only prints `[dry run] would ...`.
- `plan` never sends anything and never writes the state file.
- The wake report only reads: `hdparm -C` asks for the power state and does not wake the disk. Nothing writes to a device.
- `doctor` separates "Jellyfin is unreachable" from "the key was refused".
- A bad setting stops the app at start-up and names the variable.
- In `--loop` mode one failed round, or one client that refuses a command, is printed and the next one still runs.

## Settings

Every setting is an environment variable with the `LOMBO_NAP_` prefix, validated in `config.py`.
To add one: read it in `config.py` with a clear error, add a line to `.env.example` (a test keeps them in
sync), and add a test.

## Alerts

`notify.send(url, message)` posts JSON with the text under `content` and `text`, which Discord, Slack and
many bridges accept. It is only used when a stop really happened (not in dry run).

## Adding a Jellyfin call

Add a method to `Jellyfin` in `jellyfin.py` that calls `self._call(path)`, add the path to the fake in
`tests/conftest.py`, and test it. The API reference for your server version is at
`https://your-server/api-docs/swagger`. Check a new call against a throwaway Jellyfin before relying on it.
