"""Smoke-test every read-only endpoint of the 宜小智 backend.

Read-only by design: nothing here mutates state or spends API quota, so it is
safe to run against a live workstation while the user is using the UI.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

GETS: list[tuple[str, str]] = [
    ("health", "/api/health"),
    ("engines", "/api/engines"),
    ("presets", "/api/presets/models"),
    ("projects", "/api/projects"),
    ("demo", "/api/demo"),
    ("bambu", "/api/bambu"),
    ("software/detect", "/api/software/detect"),
    ("laser/templates", "/api/laser/templates"),
    ("scenes/config", "/api/scenes/config"),
]

POSTS: list[tuple[str, str, dict]] = [
    ("prompt/polish", "/api/prompt/polish", {"prompt": "一个小摆件"}),
    ("session/from-image", "/api/session/from-image", {}),
]


def call(method: str, path: str, payload: dict | None = None, timeout: int = 30):
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, time.time() - started, body
    except urllib.error.HTTPError as exc:
        return exc.code, time.time() - started, exc.read()
    except Exception as exc:  # noqa: BLE001 - we want the reason printed
        return 0, time.time() - started, str(exc).encode()


def preview(body: bytes, limit: int = 220) -> str:
    text = body.decode("utf-8", "replace").replace("\n", " ")
    return text[:limit]


def main() -> int:
    failures = 0
    print(f"{'ENDPOINT':<34} {'CODE':<6} {'MS':<7} NOTE")
    print("-" * 100)

    for name, path in GETS:
        code, ms, body = call("GET", path)
        note = preview(body)
        if code != 200:
            failures += 1
            note = f"FAIL {note}"
        print(f"{name:<34} {code:<6} {ms*1000:<7.0f} {note}")

    for name, path, payload in POSTS:
        code, ms, body = call("POST", path, payload)
        note = preview(body)
        # A 4xx that carries a clear application-level error is still a live
        # endpoint (the route answered); only transport errors / 5xx count.
        if code == 0 or code >= 500:
            failures += 1
            note = f"FAIL {note}"
        print(f"{name:<34} {code:<6} {ms*1000:<7.0f} {note}")

    print("-" * 100)
    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
