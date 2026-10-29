"""Tests for the shared provider circuit breaker and the server-side
3D engine chain.

The theme: a provider that is known to be down must not be tried again by
the next visitor, and the 3D build must walk the engines on the server so
that a build survives the browser that started it.
"""
import base64
import io
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


WORKTREE = Path(__file__).resolve().parents[1]
TEST_DATA = tempfile.TemporaryDirectory(prefix="cartoon-provider-health-")
os.environ["CARTOON_ROOT"] = str(WORKTREE)
os.environ["CARTOON_FRONTEND_DIR"] = str(WORKTREE / "frontend")
os.environ["CARTOON_DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(WORKTREE / "backend"))

import provider_health
import server


def _png_bytes(color=(10, 120, 200)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(blob: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(blob).decode("ascii")


class ProviderHealthTests(unittest.TestCase):
    """The breaker itself."""

    def setUp(self):
        for name in ("tripo3d", "hunyuan3d", "aixj"):
            provider_health.reset(name)

    def test_a_healthy_provider_is_usable(self):
        self.assertFalse(provider_health.is_open("tripo3d"))
        self.assertEqual(provider_health.remaining("tripo3d"), 0.0)

    def test_a_network_failure_opens_the_circuit(self):
        provider_health.report_failure("tripo3d", "network", "dns")
        self.assertTrue(provider_health.is_open("tripo3d"))
        self.assertGreater(provider_health.remaining("tripo3d"), 0)

    def test_a_success_closes_the_circuit_again(self):
        provider_health.report_failure("tripo3d", "network", "dns")
        provider_health.report_success("tripo3d")
        self.assertFalse(provider_health.is_open("tripo3d"))

    def test_repeated_failures_wait_longer(self):
        first = provider_health.report_failure("tripo3d", "network", "dns")
        second = provider_health.report_failure("tripo3d", "network", "dns")
        self.assertGreater(second, first)

    def test_a_quota_failure_outlasts_a_network_failure(self):
        quota = provider_health.report_failure("aixj", "quota", "spent")
        network = provider_health.report_failure("aixj", "network", "dns")
        self.assertGreater(quota, network)

    def test_the_state_survives_a_restart(self):
        """A backend restart must not forget that a provider is down."""
        provider_health.report_failure("hunyuan3d", "network", "tls timeout")
        self.assertTrue(Path(provider_health._state_file()).is_file())

        # Pretend the process restarted: the in-memory table is dropped and
        # the file is read again.
        provider_health._STATE.clear()
        self.assertTrue(provider_health.is_open("hunyuan3d"))


class BuildChainTests(unittest.TestCase):
    """The server-side engine chain."""

    def setUp(self):
        self.client = TestClient(server.app)
        self.sid = "chain-test-session"
        for name in ("tripo3d", "hunyuan3d", "aixj", "minimax", "jojo"):
            provider_health.reset(name)
        previews = Path(TEST_DATA.name) / self.sid / "previews"
        previews.mkdir(parents=True, exist_ok=True)
        (previews / "img_0.png").write_bytes(_png_bytes())

    def test_a_failing_engine_does_not_stop_the_chain(self):
        """The cloud engines fail, the local relief engine answers."""
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                server, "to_3d_tripo",
                side_effect=server.HTTPException(500, "boom")))
            stack.enter_context(patch.object(
                server, "to_3d_hycloud",
                side_effect=server.HTTPException(503, "boom")))
            stack.enter_context(patch.object(
                server, "to_3d_v2",
                side_effect=server.HTTPException(501, "not installed")))
            cartoon = stack.enter_context(patch.object(
                server, "to_3d_cartoon",
                return_value={
                    "session_id": self.sid,
                    "model_url": f"/api/data/{self.sid}/model/mesh.glb",
                }))
            stack.enter_context(patch("time.sleep", lambda *_a, **_k: None))
            response = self.client.post("/api/3d_build", json={
                "session_id": self.sid,
                "image_index": 0,
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], self.sid)
        self.assertTrue(cartoon.called)
        chain = [item["engine"] for item in payload["engine_chain"]]
        self.assertEqual(chain[:3], ["tripo", "hycloud", "v2"])

    def test_a_known_dead_provider_is_skipped(self):
        """A provider on cooldown must not be called at all."""
        provider_health.report_failure("tripo3d", "network", "dns")
        with ExitStack() as stack:
            tripo = stack.enter_context(patch.object(
                server, "to_3d_tripo",
                side_effect=AssertionError("must be skipped")))
            hycloud = stack.enter_context(patch.object(
                server, "to_3d_hycloud",
                return_value={
                    "session_id": self.sid,
                    "model_url": f"/api/data/{self.sid}/model/mesh.glb",
                    "engine": "hunyuan3d-cloud",
                }))
            response = self.client.post("/api/3d_build", json={
                "session_id": self.sid,
                "image_index": 0,
            })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(tripo.called)
        self.assertTrue(hycloud.called)
        chain = response.json().get("engine_chain") or []
        self.assertEqual(chain[0]["engine"], "tripo")
        self.assertTrue(chain[0].get("skipped"))
        provider_health.reset("tripo3d")

    def test_the_edited_preview_reaches_every_engine(self):
        """The canvas edit used to reach only the relief engine."""
        with ExitStack() as stack:
            tripo = stack.enter_context(patch.object(
                server, "to_3d_tripo",
                return_value={
                    "session_id": self.sid,
                    "model_url": f"/api/data/{self.sid}/model/mesh.glb",
                }))
            response = self.client.post("/api/3d_build", json={
                "session_id": self.sid,
                "image_index": 0,
                "custom_image": _data_url(_png_bytes((200, 20, 20))),
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(tripo.called)
        self.assertEqual(tripo.call_args.args[0].source_png, "edit_0.png")
        edited = Path(TEST_DATA.name) / self.sid / "previews" / "edit_0.png"
        self.assertTrue(edited.is_file())

    def test_a_missing_preview_is_reported_once(self):
        with patch.object(server, "to_3d_tripo",
                          side_effect=AssertionError("no engine may run")) as tripo:
            response = self.client.post("/api/3d_build", json={
                "session_id": "chain-test-missing",
                "image_index": 0,
            })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(tripo.called)


if __name__ == "__main__":
    unittest.main()
