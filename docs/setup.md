# Setup

## Contents

- [Still watching? in Docker](#still-watching-in-docker)
- [The wake report on the host](#the-wake-report-on-the-host)
- [Going live](#going-live)

## Still watching? in Docker

1. Create an API key in Jellyfin (Dashboard > API Keys) for LomboNap only.
2. `cp .env.example .env`, set `LOMBO_NAP_JELLYFIN_URL` and `LOMBO_NAP_JELLYFIN_API_KEY`. Put the container
   on Jellyfin's network, or use the machine's LAN address.
3. `docker compose -f compose.example.yaml up -d`, then
   `docker compose -f compose.example.yaml exec lombo-nap lombo-nap doctor`. All lines should say `ok`.
4. Watch `docker compose logs -f lombo-nap` and `lombo-nap plan` for a day. Lines starting with `[dry run] would`
   are what it would have done.

`compose.example.yaml` mounts a small volume for `LOMBO_NAP_STATE_FILE` so a restart keeps the counts.

## The wake report on the host

This part must see the host's `/proc`, sysfs and disks, so it runs on the host, not in the container.

1. Install Python 3.12 or newer and `hdparm` (`sudo apt install hdparm`).
2. `pip install .` in a virtual environment, or run `python -m lombo_nap.cli` from `src/`.
3. Run `sudo lombo-nap wake doctor`. It should list your spinning disks and a power state for each.
4. Install the systemd units from [examples/](../examples): `lombo-nap-wake.service` and `lombo-nap-wake.timer`
   (one sample a minute), after editing the paths.
5. Next day: `sudo lombo-nap wake report --days 1`.

Environment for the host: `LOMBO_NAP_WAKE_LOG` (default `/var/lib/lombo-nap/wake.jsonl`), `LOMBO_NAP_WAKE_KEEP_LINES` (the most samples kept when the log is trimmed; the log is also trimmed to its newest half whenever it passes 32 MiB). Each sample keeps the 40 processes that moved the most data since the previous sample, with up to 5 open files each.
The sampler never needs a Jellyfin key.

## Going live

Set `LOMBO_NAP_DRY_RUN=false` and restart. Start with a long `LOMBO_NAP_GRACE_SECONDS` and one test client you can
see, and check that client really shows the message and stops. Which clients do is not verified, see the README.
