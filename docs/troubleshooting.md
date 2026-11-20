# Troubleshooting

## Contents

- [doctor says FAIL](#doctor-says-fail)
- [Nothing is ever stopped](#nothing-is-ever-stopped)
- [Someone was stopped who was watching](#someone-was-stopped-who-was-watching)
- [The message does not appear](#the-message-does-not-appear)
- [The wake report is empty](#the-wake-report-is-empty)

## doctor says FAIL

| You see | Fix |
|---|---|
| `settings: LOMBO_NAP_X ...` (exit 2) | Fix that variable in `.env`. The message names it. |
| `Jellyfin reachable: ... urlopen error` | Inside the container the URL is not the one in your browser. Use the service name or LAN address. |
| `API key accepted: HTTP 401` | Create a new key and update `.env`. |
| `sessions readable: HTTP 403` | The key cannot list sessions; create a new one as an administrator. |

## Nothing is ever stopped

Dry run is on (`doctor` prints the mode), the limit has not been reached (`lombo-nap plan` shows minutes left),
or people keep interacting. A restart without `LOMBO_NAP_STATE_FILE` resets every count.

## Someone was stopped who was watching

Raise `LOMBO_NAP_LIMIT_HOURS` or `LOMBO_NAP_GRACE_SECONDS`, or add the user to `LOMBO_NAP_SKIP_USERS`. A client
that does not report its playback position looks like a paused or seeking one; open an issue with `plan` output.

## The message does not appear

Some clients ignore on-screen messages from the server (not verified per client). The stop still follows after
the grace period. Try a longer grace period and test on the client in question.

## The wake report is empty

Run `sudo lombo-nap wake doctor`. No spinning disks means sysfs says every disk is non-rotational (some USB bridges
report wrongly). "unknown" power state means `hdparm` is missing or the drive does not answer `-C`. No suspects
means the sampler is not root. Remember the report only shows wakes between two samples a minute apart.
