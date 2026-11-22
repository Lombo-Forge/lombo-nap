# Contracts other programs may rely on

## Contents

- [The limits file](#the-limits-file)
- [The status document](#the-status-document)
- [What a version bump means](#what-a-version-bump-means)
- [How a page or panel uses this](#how-a-page-or-panel-uses-this)
- [What stays on you](#what-stays-on-you)

Everything below is a promise to other programs (an admin page, a dashboard, another Lombo-Forge app). If you change
it, change this file in the same pull request. Nothing here was tried against a real client or a real panel.

Both files are plain JSON on disk. There is no server and no token: whoever can write the limits file can change
how long people may watch, so keep it writable by your panel only.

## The limits file

Set `LOMBO_NAP_LIMITS_FILE` to a path. Without it nothing is read.

```json
{
  "version": 1,
  "limits": {
    "alice": 2,
    "bob": 4.5
  }
}
```

| Field | Meaning |
|---|---|
| `version` | Whole number, `1` today. Anything else makes the file damaged. |
| `limits` | Jellyfin user name to hours, an object. Names match in any case and are trimmed. Hours may be decimal (`4.5`). Values below 1 become 1, above 6 become 6. An empty object is fine and means "nobody has their own limit in this file". |

Unknown extra fields at the top level are ignored.

How it is used:

- The app re-reads the file at the start of **every round** (`LOMBO_NAP_POLL_SECONDS`, 30 by default), so a new value
  applies within one round. No restart. A person who is already being asked is not affected by a change.
- It wins over `LOMBO_NAP_USER_LIMITS`, name by name. A person who is in neither uses `LOMBO_NAP_LIMIT_HOURS`.
  So removing a person from the file puts them back on the env list, then the global limit.
- **Missing file:** the same as an empty one (the status document says `"limits_file": "missing"`).
- **Damaged file:** not JSON, not an object, `version` not 1, `limits` not an object, a name that is empty or listed
  twice (in any case), or an hour value that is not a number (text, `true`, `null`). The **whole file** is ignored,
  not just the bad entry. The limits from the last good read stay in force; if there never was one, the env list and
  the global limit apply. One warning line is printed per distinct problem, and the status document says
  `"limits_file": "damaged"` until the file is fixed. `doctor` shows a `[warn]` line.
- **Writing it safely:** write the new contents to a temporary file in the same folder, then rename it over the real
  one (`os.replace` in Python, `mv` in a shell). A reader then sees the old file or the new one, never half of one.
  Writing in place also works most of the time, but a read in the middle looks like a damaged file for one round.
- Names are Jellyfin **user names**. If someone is renamed in Jellyfin, their entry no longer matches until you
  rename it in the file.

## The status document

Set `LOMBO_NAP_STATUS_FILE` to a path. `lombo-nap run` rewrites it after every round, in dry run too (it only
describes what the app tracks and changes nothing). `lombo-nap status --json` prints the file; `lombo-nap status`
prints a short summary. Both read the file and need the same setting; the counts live in the running app, so a
separate command cannot compute them itself.

```json
{
  "version": 1,
  "updated": 1800000000,
  "dry_run": true,
  "limit_hours": 3,
  "grace_seconds": 120,
  "poll_seconds": 30,
  "limits_file": "ok",
  "limits": {"alice": 2.0},
  "sessions": [
    {
      "user": "alice",
      "label": "alice on Living room TV (Some Show - Pilot)",
      "paused": false,
      "state": "counting",
      "quiet_seconds": 1800,
      "titles_in_row": 3,
      "limit_seconds": 7200,
      "limit_source": "own",
      "ask_in_seconds": 5400,
      "stop_in_seconds": null
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `version` | Whole number, `1` today. See [what a version bump means](#what-a-version-bump-means). |
| `updated` | Unix time in seconds when the round ran. |
| `dry_run` | `true` when nothing is really sent or stopped. |
| `limit_hours`, `grace_seconds`, `poll_seconds` | The global settings in force. |
| `limits_file` | `off` (no `LOMBO_NAP_LIMITS_FILE`), `ok`, `missing` or `damaged`. A reader should accept other words and treat them as unknown. |
| `limits` | The own limits in force right now, name (lower case) to hours, from the file and the env list together. |
| `sessions` | One row per playing movie or episode the app counts, sorted by user then label. People in `LOMBO_NAP_SKIP_USERS` are not listed. A session that stopped is gone from the list. |
| `user` | The Jellyfin user name as the session reports it. |
| `label` | A line for people: user, device, title. Text from Jellyfin, shown as received. |
| `paused` | Whether the session was paused at the last round. |
| `state` | `counting` (not asked yet) or `asked` (the message was sent, waiting for an answer). |
| `quiet_seconds` | Seconds since the last interaction (or since the app first saw the session). |
| `titles_in_row` | Titles played since the last interaction, this one included. |
| `limit_seconds` | The limit that applies to this person, in seconds. |
| `limit_source` | `own` (a name in `limits`) or `default` (the global limit). |
| `ask_in_seconds` | While `counting`: seconds until the message, `0` if due this round; `null` when `asked`. A long movie allowed to finish pushes this out. |
| `stop_in_seconds` | While `asked`: seconds until playback is stopped if nobody answers; `null` when `counting`. |

The file is written to a temporary name and renamed, mode 0644, so a reader sees the old file or the new one. It holds
names and titles of what people are watching: restrict the folder if that matters to you. If it cannot be written
the round still succeeds and prints a warning. A round that fails (Jellyfin is down) leaves the old file as it was, so
treat a file older than a few rounds (`poll_seconds`) as stale, and a missing file as "nothing known".

## What a version bump means

- **Same version:** a new, optional field may be added at the top level or to a session, and a new word may appear in
  `limits_file`. A reader must ignore fields it does not know. The limits file may gain new optional top-level fields
  the same way (today they are ignored).
- **`version` goes up:** a field was removed or renamed, or its meaning or type changed. A reader that does not know
  the new number should treat the document as unreadable. For the limits file the app does the same: a version it does
  not know makes the file damaged, so a panel written for a newer shape fails loudly instead of being half-obeyed.
  Each file has its own number but they only change in a release that says so.

## How a page or panel uses this

1. **Change someone's hours:** read your limits file (or start from `{"version":1,"limits":{}}`), set the name, write it
   atomically. Clamp to 1 to 6 yourself if you show the allowed range; the app clamps anyway.
2. **Show what is happening:** read `status.json`, check `version` is a number you know and `updated` is recent, then
   list `sessions`. `ask_in_seconds` and `stop_in_seconds` are the countdowns.
3. **Show which limit is in force:** `limits` for the map, `limit_source` per session. If `limits_file` is `damaged`,
   tell the admin: their last edit is not being applied.
4. Keep both files in a folder the app and your panel can both reach (a shared volume in Docker; the app needs the
   limits file readable and the status file's folder writable).

## What stays on you

Nap does these on purpose, or leaves them out. If you want them, add them in your own admin page:

| Wanted | What to do |
|---|---|
| A page where people set their own hours | Build it; it writes the limits file. Nap has no login, no web page and no network service. |
| Keep the allowed range narrower than 1 to 6 hours (for example a house maximum of 4) | Clamp before you write the file. Nap always allows up to 6. |
| Turn Nap off for one person without a restart | Not supported. `LOMBO_NAP_SKIP_USERS` is read at start. The closest thing is a 6 hour limit in the limits file. |
| Limits that survive a Jellyfin rename or follow the account id | Nap matches by user name. Keep your own id-to-name map and write names. |
| Know that a client really showed the message or stopped | Nap sends the calls and reports failures it sees; whether a client app honours them is not verified. Test each client you care about. |
| History of who was asked or stopped | Use the webhook (`LOMBO_NAP_WEBHOOK_URL`, stops only) or collect `status.json` yourself; Nap keeps no history. |
