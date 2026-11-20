---
name: install-into-my-stack
description: Help a user install LomboNap next to their own Jellyfin server and verify it with doctor. Use when someone asks to set it up, install it, add it to their compose file or server, or set up the disk wake report.
---

# Install LomboNap

Ask for: how Jellyfin is reached from the app (URL), whether Jellyfin runs in Docker, and whether they want the
disk wake report (it must run on the host).

1. **API key:** Jellyfin, Dashboard > API Keys > +, named `LomboNap`.
2. **.env:** copy `.env.example` to `.env`; set `LOMBO_NAP_JELLYFIN_URL` and `LOMBO_NAP_JELLYFIN_API_KEY`. Leave
   `LOMBO_NAP_DRY_RUN=true`.
3. **Compose:** merge the block from `compose.example.yaml` into theirs (keep the `/data` volume), joining Jellyfin's network if it is in another project.
4. `docker compose up -d`, then `docker compose exec lombo-nap lombo-nap doctor`. Every line must say ok. Fix FAIL lines first (see troubleshoot).
5. **Watch in dry run:** `lombo-nap plan` and `docker compose logs lombo-nap` for a day. Only after reading
   `[dry run] would ...` lines set `LOMBO_NAP_DRY_RUN=false`. Test on one client you can see. Say plainly that client support for the message is unverified.
6. **Wake report (optional):** on the host install `hdparm` and the package, run `sudo lombo-nap wake doctor`, install
   `examples/lombo-nap-wake.service` and `.timer` after editing the path, enable the timer, read `sudo lombo-nap wake report` the next day.

Never run it against someone's server without their say-so, and never put their key in a file that is committed.
