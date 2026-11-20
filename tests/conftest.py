"""A fake Jellyfin and a fake webhook on localhost, so tests need no real server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

TICKS = 10_000_000


def session(sid="s1", user="alice", item="e1", series="show", pos=60, runtime=1500, paused=False, kind="Episode"):
    """A Jellyfin session in the shape /Sessions returns."""
    return {
        "Id": sid,
        "UserName": user,
        "DeviceName": "Living room TV",
        "NowPlayingItem": {
            "Id": item,
            "SeriesId": series,
            "Type": kind,
            "Name": "Pilot",
            "SeriesName": "Some Show",
            "RunTimeTicks": runtime * TICKS,
        },
        "PlayState": {"PositionTicks": pos * TICKS, "IsPaused": paused},
    }


class Fake:
    def __init__(self):
        self.requests: list[dict] = []
        self.key = "good-key"
        self.sessions = [session(), {"Id": "idle", "UserName": "bob"}]
        self.segments = {"e1": [{"EndTicks": 90 * TICKS}]}
        self.fail_stop = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, payload=None):
                data = b"" if code == 204 else json.dumps(payload if payload is not None else {}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
                segments = outer.segments.get(self.path.rsplit("/", 1)[1])
                if self.path == "/System/Info/Public":
                    self._reply(200, {"ServerName": "Fake", "Version": "0.0.0"})
                elif self.headers.get("Authorization") != f'MediaBrowser Token="{outer.key}"':
                    self._reply(401)
                elif self.path == "/System/Info":
                    self._reply(200, {"ServerName": "Fake"})
                elif self.path == "/Sessions":
                    self._reply(200, outer.sessions)
                elif self.path.startswith("/MediaSegments/") and segments is not None:
                    self._reply(200, {"Items": segments})
                else:
                    self._reply(404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"method": "POST", "path": self.path, "body": json.loads(raw) if raw else None})
                failing = outer.fail_stop and self.path.endswith("/Playing/Stop")
                self._reply(500 if failing else 204)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self):
        return [r for r in self.requests if r["method"] == "POST"]

    def commands(self):
        """Only what was sent to sessions (not the webhook)."""
        return [r["path"] for r in self.posts() if r["path"].startswith("/Sessions/")]


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.server.shutdown()


@pytest.fixture
def env(fake):
    return {
        "LOMBO_NAP_JELLYFIN_URL": fake.url,
        "LOMBO_NAP_JELLYFIN_API_KEY": "good-key",
        "LOMBO_NAP_WEBHOOK_URL": fake.url + "/hook",
    }
