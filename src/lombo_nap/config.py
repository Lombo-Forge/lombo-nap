"""Settings, read once from environment variables (see .env.example).

Every setting has a LOMBO_NAP_ prefix so it never collides with another container's variables.
A bad value stops the app at start-up with a message that names the variable.

Two groups: `from_env` for "Still watching?" (needs Jellyfin) and `wake_from_env` for the disk
wake report (needs no Jellyfin, only the log path).
"""

from dataclasses import dataclass
from urllib.parse import urlparse

PREFIX = "LOMBO_NAP_"


class ConfigError(Exception):
    """A setting is missing or invalid. The message says which one and what to do."""


@dataclass(frozen=True)
class Config:
    jellyfin_url: str
    jellyfin_api_key: str
    webhook_url: str | None
    dry_run: bool
    poll_seconds: int
    limit_hours: int
    grace_seconds: int
    max_episodes: int
    skip_users: frozenset[str]
    state_file: str | None


@dataclass(frozen=True)
class WakeConfig:
    log_file: str
    host_root: str
    keep_lines: int


def _truthy(value: str, name: str) -> bool:
    """Strict on/off: a typo such as DRY_RUN=treu is an error, never a silent 'off'."""
    word = value.strip().lower()
    if word in {"1", "true", "yes", "on"}:
        return True
    if word in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{PREFIX}{name} must be true or false (got {value!r})")


def _number(raw: str, name: str, low: int, high: int) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{PREFIX}{name} must be a whole number") from None
    if not low <= value <= high:
        raise ConfigError(f"{PREFIX}{name} must be between {low} and {high} (got {value})")
    return value


def from_env(env: dict[str, str]) -> Config:
    def get(name: str, default: str = "") -> str:
        return (env.get(PREFIX + name) or default).strip()

    url = get("JELLYFIN_URL").rstrip("/")
    if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
        raise ConfigError(f"{PREFIX}JELLYFIN_URL must be a full URL such as http://jellyfin:8096 (got {url!r})")

    key = get("JELLYFIN_API_KEY")
    if not key or key == "changeme":
        raise ConfigError(f"{PREFIX}JELLYFIN_API_KEY is not set. Create one in Jellyfin: Dashboard > API Keys.")

    webhook = get("WEBHOOK_URL") or None
    if webhook and urlparse(webhook).scheme not in {"http", "https"}:
        raise ConfigError(f"{PREFIX}WEBHOOK_URL must start with http:// or https:// (or be empty)")

    users = frozenset(u.strip().lower() for u in get("SKIP_USERS").split(",") if u.strip())

    # Safe by default: nothing is sent or stopped until the person sets DRY_RUN=false.
    return Config(
        jellyfin_url=url,
        jellyfin_api_key=key,
        webhook_url=webhook,
        dry_run=_truthy(get("DRY_RUN", "true") or "true", "DRY_RUN"),
        poll_seconds=_number(get("POLL_SECONDS", "30"), "POLL_SECONDS", 5, 3600),
        limit_hours=_number(get("LIMIT_HOURS", "3"), "LIMIT_HOURS", 1, 6),
        grace_seconds=_number(get("GRACE_SECONDS", "120"), "GRACE_SECONDS", 10, 3600),
        max_episodes=_number(get("MAX_EPISODES", "0"), "MAX_EPISODES", 0, 50),
        skip_users=users,
        state_file=get("STATE_FILE") or None,
    )


def wake_from_env(env: dict[str, str]) -> WakeConfig:
    def get(name: str, default: str = "") -> str:
        return (env.get(PREFIX + name) or default).strip()

    return WakeConfig(
        log_file=get("WAKE_LOG", "/var/lib/lombo-nap/wake.jsonl"),
        host_root=get("HOST_ROOT", "/"),
        keep_lines=_number(get("WAKE_KEEP_LINES", "100000"), "WAKE_KEEP_LINES", 1000, 10_000_000),
    )
