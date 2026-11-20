---
name: troubleshoot
description: Diagnose LomboNap problems from doctor output and logs. Use when the app fails to start, doctor shows FAIL, nobody is ever asked or stopped, someone was stopped wrongly, the message does not appear, or the wake report is empty.
---

# Troubleshoot LomboNap

Start with `lombo-nap doctor` (and `lombo-nap wake doctor` on the host for the report).

| You see | It means | Fix |
|---|---|---|
| `[FAIL] settings: LOMBO_NAP_X ...` (exit 2) | A setting is missing or invalid; the message names it. | Fix that variable in `.env`; restart. |
| `Jellyfin reachable: ... urlopen error` | The container cannot reach that URL. | Use the compose service name or LAN address, not the browser's URL; check the shared network. |
| `API key accepted: HTTP 401` | Key refused. | Create a new key in Dashboard > API Keys. |
| `sessions readable: HTTP 403` | The key cannot list sessions. | Create the key as an administrator. |
| Nothing is ever stopped | Dry run is on, the limit is not reached (`plan` shows minutes left), or people interact, or no state file so a restart reset the counts. | Read `plan`; set `LOMBO_NAP_STATE_FILE`; set `DRY_RUN=false` when ready. |
| Someone stopped while watching | The client does not report position or play state, or the limit is short. | Raise `LIMIT_HOURS` / `GRACE_SECONDS`, or add the user to `SKIP_USERS`. |
| No message on screen | The client ignores server messages (unverified per client). | Stop still follows after the grace period; test per client. |
| `wake report`: no spinning disks | sysfs says every disk is non-rotational. | Check `/sys/block/*/queue/rotational`. |
| `wake report`: power state unknown | `hdparm` missing or the drive does not answer `-C`. | `apt install hdparm`; run as root. |
| `wake report`: no process I/O seen | Sampler is not root. | Run the timer unit as root. |

Logs: `docker compose logs --tail 100 lombo-nap`; a failed round is logged with `[FAIL]` and the loop continues.
When reporting a bug include `doctor` output with the key and webhook URL removed.
