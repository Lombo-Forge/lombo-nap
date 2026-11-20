---
name: adapt
description: Change LomboNap's rules, thresholds, settings or alerts without breaking it. Use when the user wants different behaviour, a new setting, a new Jellyfin call, a different alert target, or a change to the wake report.
---

# Adapt LomboNap

1. **Change what counts as an interaction, or when to ask:** edit `_interaction`, `deadline` or `step` in `core.py`.
   Write the test first in `tests/test_core.py` with the `session()` helper from `conftest.py` and the `watch()`
   helper (polls once a minute, position follows the clock), watch it fail, then change the code. Keep `core.py`
   free of network, disk and clock: `now` is passed in.
2. **Change a threshold:** limit hours, grace and episode count are settings (`LIMIT_HOURS`, `GRACE_SECONDS`,
   `MAX_EPISODES`); the skip-detection constants (`SEEK_SLACK`, `SKIP_MAX`, `END_ZONE`, `CHAIN_END`) are at the top of `core.py`.
3. **Add a setting:** `config.py` (validated, the message names the variable), `.env.example` (one comment line; a test
   keeps the file and `config.py` in sync), and `compose.example.yaml` if it needs passing through. Add a bad-value case to `test_app.py`.
4. **Add a Jellyfin call:** a method in `jellyfin.py`, a route in the fake in `tests/conftest.py`, a test. Check it against a throwaway Jellyfin.
5. **Change the wake report:** parsing and attribution are in `wake.py` (pure, tested with fixture text); reading `/proc`
   is in `sysinfo.py` (tested with a fake root). Never add anything that wakes, spins down or writes to a device.
6. **Different alert target:** `notify.py` posts JSON; point `LOMBO_NAP_WEBHOOK_URL` at a bridge instead of editing code.

Finish with the checks in `AGENTS.md` (ruff, mypy, pytest with coverage, leak check).
