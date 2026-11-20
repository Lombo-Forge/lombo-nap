# AGENTS.md

Notes for an AI coding agent (or a person) working in this repo. `CLAUDE.md` pulls this file in.


## What this is

LomboNap is a small Python 3.12 program with two features. (1) "Still watching?": through the Jellyfin
API it finds playback nobody is watching, shows a message and, after a grace period, stops it. (2) A disk
wake report: what woke the hard disks from spin-down, from `/proc`, sysfs and `hdparm -C`.
**Stopping playback affects real viewers**, so dry run stays the default.
Standard library only (add a dependency only when it clearly earns its place).

## Layout

| Path | What |
|---|---|
| `src/lombo_nap/core.py` | "Still watching?" decisions. Pure: no network, disk or clock. Who is unattended, when to ask, when to stop. |
| `src/lombo_nap/wake.py` | Wake report decisions. Pure: parses `/proc` and hdparm text, attributes wakes, formats the report. |
| `src/lombo_nap/jellyfin.py` | The Jellyfin client (sessions, segments, message, stop, go home). |
| `src/lombo_nap/sysinfo.py` | Reads `/proc` and sysfs, runs `hdparm -C`, keeps the wake log. Never writes to a device. |
| `src/lombo_nap/cli.py` | `doctor`, `plan`, `run`, `wake ...`. The only place that joins the pieces and prints. |
| `src/lombo_nap/config.py` | Settings from `LOMBO_NAP_*` environment variables. |
| `src/lombo_nap/notify.py` | Webhook alerts. |
| `examples/` | systemd unit and timer for the wake sampler. |
| `tests/` | pytest: a fake Jellyfin recording message and stop calls, and a fake `/proc` tree. Never real disks. |
| `scripts/leak-check.sh` | Fails when private or personal strings appear. CI runs it. |
| `docs/` | One topic per file, each with a `## Contents` list. |

## Rules

- **Keep `core.py` pure.** If a rule needs data, pass it in. That is what makes it testable.
- **Safe by default.** `DRY_RUN` defaults to true. `plan` must never change anything. Only `run` with
  `DRY_RUN=false` may send a message or stop a session.
- **Never touch real disks in tests.** Tests give `take_snapshot` a fake root and a fake power-state function.
  `hdparm -C` only asks for the state; never add a call that wakes, spins down or writes to a device.
- **A new setting** goes in `config.py` (validated, message names the variable), `.env.example`
  (one comment line), and `compose.example.yaml` if it needs passing through.
- **Fail with a message, not a traceback.** Wrap outside calls; the loop survives one bad round.
- **Never put private details in the repo:** real hostnames, IPs, webhook URLs, API keys, local
  paths. Use `jellyfin.example.com`, `/mnt/media`, `changeme`. `scripts/leak-check.sh` enforces it;
  patterns live in `scripts/leak-patterns.txt`.
- Plain language in docs and messages. Call a PC used for encoding a "main PC with a discrete
  graphics card". Never call anything "official" or imply the Jellyfin project made it.
- The Lombo look (every icon has the Lombo L) is in `docs/branding.md`.

## Test

```sh
pip install -e '.[dev]'
pre-commit install            # once: runs the checks below before every commit
pre-commit run --all-files    # ruff lint + format, strict mypy, file hygiene, leak check
pytest -q --cov               # tests with coverage (the gate is `fail_under` in pyproject.toml)
```

These are the same checks CI runs (one config: `.pre-commit-config.yaml` and `pyproject.toml`), so what passes
locally passes there. The tooling is the same in every Lombo-Forge repo: ruff for lint and format, strict mypy,
pytest. Do not loosen a rule to make a change pass; fix the code, or say why in a comment next to a narrow `noqa`.

Without Python installed: `docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c "pip install -q -e '.[dev]' && pytest -q"`.
Tests use a fake server; before claiming a Jellyfin behaviour works, check it against a throwaway
Jellyfin container, never someone's real server.

## Working efficiently

- Optional tools that live in your own profile, not in this repo. Skip any you do not have.
- Graphify: build the code-only graph with `graphify update .` (never `/graphify .`, which costs tokens) and run
  `graphify query "<question>"` before grepping. `graphify-out/` is generated and gitignored; INFERRED edges are guesses.
- Ponytail: the smallest change that fully solves the task. Keep diffs small and focused.

## Skills (`.claude/skills/`)

- `install-into-my-stack`: help a user put the app into their setup and run `doctor`.
- `troubleshoot`: read `doctor` output and logs.
- `adapt`: change the rules, thresholds or settings safely.
