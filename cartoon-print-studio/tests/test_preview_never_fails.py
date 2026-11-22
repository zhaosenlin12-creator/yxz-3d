"""A preview must always exist.

The exhibition machine talks to services it does not control: AIXJ ran
out of credit in the middle of a session and MiniMax answered 402 for one
of its two keys.  When every provider died at once the endpoint used to
answer HTTP 500, and the assistant then described a picture that was
never drawn -- the visitor was told "预览出来了" while the chat stayed
empty.  A preview request therefore has to end with a picture, no matter
how bad the day is.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


WORKTREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WORKTREE, "backend"))

# NOTE: ``server`` must NOT be imported at module level here, and this file
# must not set CARTOON_DATA_DIR.  The backend binds its data directory when
# it is first imported, and several test modules set that variable while
# they are collected.  Importing the backend here -- this file sorts
# before test_provider_health.py -- would move the data directory out from
# under the tests that write their fixtures into it, and they would fail
# with a 404 for pictures that are really there.


def _server():
    """The backend module, imported lazily for the reason above."""
    import server

    return server


class PreviewNeverFailsTests(unittest.TestCase):
    def test_the_placeholder_is_a_real_picture(self):
        server = _server()
        out_dir = tempfile.mkdtemp()
        source, results = server._placeholder_previews("圣诞树桌面摆件", out_dir, 4)

        self.assertEqual(source, "placeholder")
        self.assertEqual(len(results), 4)
        for blob, _tag in results:
            self.assertTrue(blob)
            self.assertEqual(blob[:4], b"\x89PNG")

    def test_the_endpoint_answers_with_a_picture_when_every_provider_fails(self):
        """The cloud chain explodes -- the visitor still gets something."""
        server = _server()
        with patch.object(server.api_image, "generate_previews",
                          side_effect=RuntimeError("every provider is dead")), \
             patch.object(server.local_preview, "render_previews",
                          side_effect=RuntimeError("Pillow is broken too")):
            with TestClient(server.app) as client:
                response = client.post("/api/previews", json={
                    "prompt": "圣诞树桌面摆件",
                    "n": 2,
                    "session_id": "fallbacktest",
                })

        self.assertEqual(response.status_code, 200, response.text[:400])
        payload = response.json()
        self.assertEqual(len(payload["previews"]), 2)
        for item in payload["previews"]:
            self.assertTrue(item["path"].endswith(".png"))

    def test_the_endpoint_answers_with_a_picture_when_the_chain_is_empty(self):
        """The providers answer, but every picture is empty."""
        server = _server()
        with patch.object(server.api_image, "generate_previews",
                          return_value=("aixj-image", [(None, "aixj#fail")] * 4)), \
             patch.object(server.local_preview, "render_previews",
                          side_effect=RuntimeError("Pillow is broken too")):
            with TestClient(server.app) as client:
                response = client.post("/api/previews", json={
                    "prompt": "圣诞树桌面摆件",
                    "n": 4,
                    "session_id": "emptytest",
                })

        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(len(response.json()["previews"]), 4)


if __name__ == "__main__":
    unittest.main()
