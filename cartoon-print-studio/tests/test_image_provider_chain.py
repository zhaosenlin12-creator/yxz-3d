"""Tests for the image provider chain.

The visitor never picks a model, so the backend has to survive a provider
that is down (AIXJ answers 502), a key whose account is spent (MiniMax
answers HTTP 200 with the Token Plan limit) and a key whose credit is
gone (jojo answers 403).  Every one of those cases must still deliver a
complete set of pictures.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WORKTREE = Path(__file__).resolve().parents[1]
TEST_DATA = tempfile.TemporaryDirectory(prefix="cartoon-image-chain-")
os.environ["CARTOON_ROOT"] = str(WORKTREE)
os.environ["CARTOON_DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(WORKTREE / "backend"))

import api_image


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MinimaxQuotaBreakerTests(unittest.TestCase):
    """A spent MiniMax key must be taken out of the rotation."""

    def setUp(self):
        api_image._MINIMAX_DEAD_KEYS.clear()
        api_image._MINIMAX_DEAD_UNTIL.clear()

    def tearDown(self):
        api_image._MINIMAX_DEAD_KEYS.clear()
        api_image._MINIMAX_DEAD_UNTIL.clear()

    def test_token_plan_limit_counts_as_a_quota_error(self):
        base = {"status_code": 2056, "status_msg": "has reached the Token Plan limit"}
        self.assertTrue(api_image._minimax_quota_error(base))

    def test_a_broken_prompt_is_not_a_quota_error(self):
        base = {"status_code": 1000, "status_msg": "bad parameter"}
        self.assertFalse(api_image._minimax_quota_error(base))

    def test_spent_key_is_blacklisted_and_the_next_key_takes_over(self):
        """The second key must serve the picture without a second doomed call."""
        spent, healthy = "sk-spent", "sk-healthy"
        calls = []

        def _urlopen(req, timeout=None):
            key = req.headers["Authorization"].split(" ", 1)[1]
            calls.append(key)
            if key == spent:
                return _FakeResponse({
                    "base_resp": {"status_code": 2056,
                                  "status_msg": "has reached the Token Plan limit"},
                })
            return _FakeResponse({"base_resp": {"status_code": 0},
                                   "image_urls": ["https://x/i.png"]})

        with patch.object(api_image, "MINIMAX_IMAGE_KEYS", [spent, healthy]), \
             patch.object(api_image, "_download_with_retry", return_value=PNG), \
             patch.object(api_image.urllib.request, "urlopen", side_effect=_urlopen):
            out = api_image._minimax_image_call("a red cube", n=1)

        self.assertIsNotNone(out)
        self.assertEqual(out, [PNG])
        # The spent key was tried once and then taken out of the rotation.
        self.assertIn(spent, api_image._MINIMAX_DEAD_KEYS)
        self.assertEqual(calls.count(spent), 1)

        # A second round skips the spent key entirely.
        calls.clear()
        with patch.object(api_image, "MINIMAX_IMAGE_KEYS", [spent, healthy]), \
             patch.object(api_image, "_download_with_retry", return_value=PNG), \
             patch.object(api_image.urllib.request, "urlopen", side_effect=_urlopen):
            api_image._minimax_image_call("a blue cube", n=1)
        self.assertNotIn(spent, calls)
        self.assertEqual(calls.count(healthy), 1)


class ProviderChainTests(unittest.TestCase):
    """The chain itself must survive a dead provider."""

    def test_auto_chain_starts_with_the_configured_primary(self):
        chain = api_image._provider_chain("auto")
        self.assertEqual(chain[0], "minimax")
        self.assertIn("aixj", chain)
        self.assertIn("jojo", chain)
        self.assertEqual(chain[-1], "local")

    def test_an_explicit_preference_still_keeps_the_others_as_backup(self):
        chain = api_image._provider_chain("aixj")
        self.assertEqual(chain[0], "aixj")
        self.assertIn("minimax", chain)
        self.assertIn("jojo", chain)

    def test_a_dead_provider_hands_over_to_the_next_one(self):
        """AIXJ down -> jojo out of credit -> minimax still delivers 4 pictures."""
        with patch.object(api_image, "_try_aixj_image", return_value=None), \
             patch.object(api_image, "_try_jojo_image", return_value=None), \
             patch.object(api_image, "_try_minimax_image",
                          return_value=[(PNG, "minimax#1"), (PNG, "minimax#2"),
                                        (PNG, "minimax#3"), (PNG, "minimax#4")]):
            source, items = api_image.generate_previews(["p"] * 4, prefer="auto")

        self.assertEqual(source, "minimax-image")
        self.assertEqual(len(items), 4)
        self.assertTrue(all(blob is not None for blob, _ in items))

    def test_a_partial_provider_is_topped_up_by_the_next_one(self):
        """Two good pictures plus two holes must not be handed to the visitor."""
        with patch.object(api_image, "_try_minimax_image",
                          return_value=[(PNG, "minimax#1"), (None, "minimax#fail2")]), \
             patch.object(api_image, "_try_aixj_image",
                          return_value=[(PNG, "aixj#1"), (PNG, "aixj#2")]):
            source, items = api_image.generate_previews(["p"] * 2, prefer="minimax")

        self.assertEqual(len(items), 2)
        self.assertTrue(all(blob is not None for blob, _ in items))
        self.assertEqual(source, "aixj-image")


if __name__ == "__main__":
    unittest.main()
