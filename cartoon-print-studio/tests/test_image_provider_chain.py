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
        # AIXJ (gpt-image-2) carries the pictures; MiniMax (H3) is the
        # fallback that keeps the chain alive when the gateway is down.
        self.assertEqual(chain[0], "aixj")
        self.assertIn("aixj", chain)
        self.assertIn("minimax", chain)
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


class SingleKeyFailureTests(unittest.TestCase):
    """One spent key must not take the whole provider down with it.

    AIXJ, MiniMax and jojo are all used with more than one key.  When the
    shared circuit breaker was opened by a single key it also threw away
    the keys that still worked, and the chain ended up with nothing --
    which is how "one key ran out of credit" turned into "no preview at
    all" in the middle of the exhibition.
    """

    def test_a_spent_key_reports_a_partial_failure_while_a_key_is_left(self):
        with patch.object(api_image, "MINIMAX_IMAGE_KEYS", ["sk-spent", "sk-good"]), \
             patch.object(api_image, "_MINIMAX_DEAD_KEYS", {"sk-spent"}):
            api_image._report_key_dead("minimax", "quota", "HTTP 402")

            # The breaker must not have been opened: the second key works.
            self.assertFalse(api_image._provider_is_open("minimax"))

    def test_the_last_dead_key_does_take_the_provider_out_of_the_chain(self):
        with patch.object(api_image, "MINIMAX_IMAGE_KEYS", ["sk-spent"]), \
             patch.object(api_image, "_MINIMAX_DEAD_KEYS", {"sk-spent"}):
            api_image._report_key_dead("minimax", "quota", "HTTP 402")

            # Nothing is left to try, so the provider has to be skipped.
            self.assertFalse(api_image._provider_has_live_key("minimax"))

    def test_a_provider_without_a_usable_key_is_reported_as_such(self):
        with patch.object(api_image, "AIXJ_IMAGE_KEYS", ["sk-dead"]), \
             patch.object(api_image, "_AIXJ_DEAD_KEYS", {"sk-dead"}):
            self.assertFalse(api_image._provider_has_live_key("aixj"))

    def test_a_provider_with_a_usable_key_is_kept(self):
        with patch.object(api_image, "MINIMAX_IMAGE_KEYS", ["sk-dead", "sk-good"]), \
             patch.object(api_image, "_MINIMAX_DEAD_KEYS", {"sk-dead"}):
            self.assertTrue(api_image._provider_has_live_key("minimax"))


class ProviderSkipTests(unittest.TestCase):
    """A provider that is known to be down must not be dialled at all."""

    def test_an_open_provider_is_not_called(self):
        called = []

        def _aixj(*args, **kwargs):
            called.append("aixj")
            return None

        def _minimax(*args, **kwargs):
            called.append("minimax")
            return [(PNG, "minimax#1"), (PNG, "minimax#2")]

        with patch.object(api_image, "_provider_is_open",
                          side_effect=lambda name: name == "aixj"), \
             patch.object(api_image, "_provider_has_live_key", return_value=True), \
             patch.object(api_image, "_try_aixj_image", _aixj), \
             patch.object(api_image, "_try_minimax_image", _minimax):
            source, items = api_image.generate_previews(["p"] * 2, prefer="auto")

        self.assertNotIn("aixj", called)
        self.assertIn("minimax", called)
        self.assertEqual(source, "minimax-image")
        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
