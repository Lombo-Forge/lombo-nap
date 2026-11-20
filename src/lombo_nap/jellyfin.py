"""A small Jellyfin client, standard library only.

Authentication uses an API key (Jellyfin: Dashboard > API Keys) in the Authorization header.
Every failure becomes a JellyfinError with a short message, so callers print it instead of crashing.
"""

import json
import urllib.error
import urllib.request
from typing import Any, cast


class JellyfinError(Exception):
    """A request failed. The message names the path and the reason."""


class Jellyfin:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.timeout = timeout

    def _call(self, path: str, auth: bool = True, body: dict[str, Any] | None = None, post: bool = False) -> Any:
        # S310 is silenced here: config.py only accepts http(s) URLs.
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if post else "GET")  # noqa: S310
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f'MediaBrowser Token="{self.key}"')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise JellyfinError(f"{path}: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise JellyfinError(f"{path}: {e}") from e

    def public_info(self) -> dict[str, Any]:
        """Server name and version. Needs no key, so it tells 'unreachable' apart from 'bad key'."""
        return cast(dict[str, Any], self._call("/System/Info/Public", auth=False))

    def info(self) -> dict[str, Any]:
        """Needs a valid key."""
        return cast(dict[str, Any], self._call("/System/Info"))

    def sessions(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("/Sessions") or [])

    def segment_ends(self, item_id: str) -> list[float]:
        """Seconds where the item's intro / credits / recap segments end. [] when unknown."""
        try:
            data = self._call(f"/MediaSegments/{item_id}") or {}
        except JellyfinError:
            return []
        return [(x.get("EndTicks") or 0) / 10_000_000 for x in data.get("Items", [])]

    def message(self, session_id: str, header: str, text: str, timeout_ms: int) -> None:
        self._call(
            f"/Sessions/{session_id}/Message",
            body={"Header": header, "Text": text, "TimeoutMs": timeout_ms},
            post=True,
        )

    def stop(self, session_id: str) -> None:
        self._call(f"/Sessions/{session_id}/Playing/Stop", post=True)

    def go_home(self, session_id: str) -> None:
        self._call(f"/Sessions/{session_id}/Command/GoHome", post=True)
