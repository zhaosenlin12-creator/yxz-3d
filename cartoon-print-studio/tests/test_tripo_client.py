import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


WORKTREE = Path(__file__).resolve().parents[1]
os.environ.setdefault("CARTOON_ROOT", str(WORKTREE))
sys.path.insert(0, str(WORKTREE / "backend"))

import tripo_api


def _response(payload, status=200):
    """A fake urlopen response carrying a JSON body."""

    class _Response:
        def __init__(self):
            self._body = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Response()


class TripoPlatformTests(unittest.TestCase):
    """Tripo runs two regional platforms; the client has to reach both."""

    def setUp(self):
        self._version = tripo_api._api_version
        self._keys = list(tripo_api.API_KEYS)
        self._active = tripo_api._active_key_index
        tripo_api.API_KEYS = ["key-cn", "key-global"]
        tripo_api.API_KEY = "key-cn"
        tripo_api._active_key_index = 0

    def tearDown(self):
        tripo_api._api_version = self._version
        tripo_api.BASE = tripo_api._base_for(self._version)
        tripo_api.API_KEYS = self._keys
        tripo_api.API_KEY = self._keys[0] if self._keys else ""
        tripo_api._active_key_index = self._active

    def test_cn_key_is_accepted_by_the_cn_platform(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            if "api.tripo3d.ai" in req.full_url:
                raise urllib.error.HTTPError(
                    req.full_url, 401, "unauthorized", {}, None
                )
            return _response({"code": 0, "data": {"balance": 600.0, "frozen": 0.0}})

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            result = tripo_api.get_balance(timeout=5, retries=0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["balance"], 600)
        self.assertEqual(result["platform"], "v3")
        self.assertTrue(seen["url"].startswith("https://openapi.tripo3d.com/v3/account/balance"))

    def test_a_key_the_platform_rejects_falls_through_to_the_next_one(self):
        tried = []

        def fake_urlopen(req, timeout=None):
            tried.append(req.full_url)
            auth = req.headers.get("Authorization")
            if auth == "Bearer key-cn":
                raise urllib.error.HTTPError(
                    req.full_url, 401, "unauthorized", {}, None
                )
            return _response({"code": 0, "data": {"balance": 20, "frozen": 0}});

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            result = tripo_api.get_balance(timeout=5, retries=0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["balance"], 20)
        self.assertEqual(len(tried), 2)

    def test_upload_and_task_paths_follow_the_platform(self):
        paths = []

        def fake_urlopen(req, timeout=None):
            paths.append(req.full_url)
            if req.method == "POST" and req.full_url.endswith("/files"):
                return _response({"code": 0, "data": {"file_token": "file_abc"}})
            return _response({"code": 0, "data": {"task_id": "task_abc"}})

        with tempfile.TemporaryDirectory(prefix="tripo-upload-") as tmp:
            source = Path(tmp) / "preview.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 512)
            with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
                token = tripo_api.upload_image(str(source))
                task = tripo_api._request(
                    "POST", "create",
                    body_for=lambda version: json.dumps({"input": token}).encode(),
                    headers={"Content-Type": "application/json"},
                    timeout=5, retries=0,
                )

        self.assertEqual(token, "file_abc")
        self.assertEqual(task["data"]["task_id"], "task_abc")
        self.assertTrue(paths[0].startswith("https://openapi.tripo3d.com/v3/files"))
        self.assertTrue(
            paths[1].startswith("https://openapi.tripo3d.com/v3/generation/image-to-model")
        )


if __name__ == "__main__":
    unittest.main()
