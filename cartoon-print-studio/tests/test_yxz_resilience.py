"""Tests for the robustness work: cheap liveness probe, lean preview
responses, and handing a finished model to the slicer on this machine.

The common theme is "the visitor must not get stuck": nothing here may
block on the network, and every failure has to answer with something the
interface can show.
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


WORKTREE = Path(__file__).resolve().parents[1]
TEST_DATA = tempfile.TemporaryDirectory(prefix="cartoon-resilience-tests-")
os.environ["CARTOON_ROOT"] = str(WORKTREE)
os.environ["CARTOON_FRONTEND_DIR"] = str(WORKTREE / "frontend")
os.environ["CARTOON_DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(WORKTREE / "backend"))

import server
import mesh_isolation
import software_integrations


def _png_bytes(color=(10, 120, 200)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


class PingTests(unittest.TestCase):
    """The supervisor probes /api/ping to decide whether the backend lives."""

    def setUp(self):
        self.client = TestClient(server.app)

    def test_ping_answers_without_touching_any_provider(self):
        with patch.object(server.tripo_api, "health", side_effect=AssertionError("no network")):
            response = self.client.get("/api/ping")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("ts", payload)

    def test_ping_does_not_scan_the_registry(self):
        """The old probe (/api/software/detect) takes seconds on a cold cache."""
        with patch.object(
            software_integrations,
            "_windows_registry_candidates",
            side_effect=AssertionError("must not scan the registry"),
        ), patch.object(
            software_integrations,
            "_shortcut_candidates",
            side_effect=AssertionError("must not scan the start menu"),
        ):
            response = self.client.get("/api/ping")
        self.assertEqual(response.status_code, 200)


class PreviewPayloadTests(unittest.TestCase):
    """Four inlined 1024x1024 PNGs made the preview answer ~10 MB."""

    def setUp(self):
        self.client = TestClient(server.app)
        self.sid = "resilience-previews-01"

    def _fake_generate(self, prompts, **kwargs):
        return "test", [( _png_bytes(), "test" ) for _ in prompts]

    def test_previews_answer_with_paths_instead_of_base64(self):
        with patch.object(server.api_image, "generate_previews", side_effect=self._fake_generate):
            response = self.client.post("/api/previews", json={
                "prompt": "一只可爱的机器人",
                "n": 2,
                "session_id": self.sid,
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["previews"]), 2)
        for item in payload["previews"]:
            self.assertTrue(item["path"].startswith("/api/data/"))
            self.assertFalse(item.get("b64"), "base64 must be opt-in")
        self.assertLess(len(response.content), 4096, "the answer must stay small")

    def test_previews_can_still_inline_base64_when_asked(self):
        with patch.object(server.api_image, "generate_previews", side_effect=self._fake_generate):
            response = self.client.post("/api/previews", json={
                "prompt": "一只可爱的机器人",
                "n": 1,
                "session_id": self.sid,
                "include_b64": True,
            })
        self.assertEqual(response.status_code, 200)
        item = response.json()["previews"][0]
        self.assertTrue(item.get("b64"))

    def test_previews_reject_an_empty_prompt(self):
        response = self.client.post("/api/previews", json={"prompt": "   ", "n": 1})
        self.assertEqual(response.status_code, 400)


class SoftwareHandoverTests(unittest.TestCase):
    """A finished model has to reach the slicer that is installed here."""

    def setUp(self):
        self.client = TestClient(server.app)
        self.tool = {
            "id": "bambu",
            "name": "Bambu Studio",
            "kind": "3d-print",
            "available": True,
            "path": r"C:\Program Files\Bambu Studio\bambu-studio.exe",
            "formats": ["stl", "obj"],
            "verifiedFormats": ["stl"],
            "overridden": False,
            "override": "",
            "overrideMissing": False,
        }

    def test_software_open_hands_a_preset_model_to_the_slicer(self):
        with patch.object(
            software_integrations,
            "detect_software",
            return_value=[self.tool],
        ), patch.object(
            software_integrations,
            "open_export",
            return_value={"message": "已打开"},
        ) as opener:
            response = self.client.post("/api/software/open", json={
                "software_id": "bambu",
                "fmt": "stl",
                "path": "presets/models/pose_wave/model.stl",
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(opener.called, "the slicer must actually be launched")
        handed_over = opener.call_args[0][1]
        self.assertTrue(os.path.isfile(handed_over))
        self.assertTrue(handed_over.lower().endswith("model.stl"))

    def test_software_open_refuses_a_path_outside_the_project(self):
        with patch.object(
            software_integrations,
            "detect_software",
            return_value=[self.tool],
        ), patch.object(
            software_integrations,
            "open_export",
        ) as opener:
            response = self.client.post("/api/software/open", json={
                "software_id": "bambu",
                "fmt": "stl",
                "path": "../../Windows/System32/cmd.exe",
            })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(opener.called, "nothing may be launched")

    def test_detect_ignores_a_shell_saved_as_a_slicer_path(self):
        """A wrong override used to hide the real installation."""
        software_integrations.save_override("bambu", r"C:\Windows\System32\cmd.exe")
        try:
            tools = software_integrations.detect_software()
        finally:
            software_integrations.clear_override("bambu")
        bambu = next(item for item in tools if item["id"] == "bambu")
        self.assertNotEqual(bambu["path"], r"C:\Windows\System32\cmd.exe")
        self.assertFalse(bambu["overridden"])

    def test_saving_a_shell_as_a_slicer_path_is_refused(self):
        response = self.client.post("/api/software/path", json={
            "software_id": "bambu",
            "path": r"C:\Windows\System32\cmd.exe",
        })
        self.assertEqual(response.status_code, 400)


class CrashForensicsTests(unittest.TestCase):
    """The supervisor truncates the log on every restart, so the backend
    keeps its own breadcrumb file that is never overwritten."""

    def test_crash_log_is_written_to_a_file_that_survives(self):
        marker = "unit-test-crash-marker"
        server._crash_log(marker)
        self.assertTrue(os.path.isfile(server._CRASH_FILE))
        content = Path(server._CRASH_FILE).read_text(encoding="utf-8")
        self.assertIn(marker, content)

    def test_crash_log_never_raises(self):
        original = server._CRASH_FILE
        server._CRASH_FILE = os.path.join("Z:\\", "definitely", "not", "writable", "x.log")
        try:
            server._crash_log("this must not raise")
        finally:
            server._CRASH_FILE = original


class LocalMeshIsolationTests(unittest.TestCase):
    """The local builders load gigabytes of weights.

    When they run inside the API server, a machine that runs out of
    commit charge loses the whole server -- and with it every open chat
    turn.  They therefore run in a child process.
    """

    def test_probe_reports_availability_without_raising(self):
        status = mesh_isolation.probe_local_mesh("triposr", timeout_s=120)
        self.assertIsInstance(status, dict)
        self.assertIn("available", status)

    def test_probe_of_an_unknown_engine_reports_unavailable(self):
        status = mesh_isolation.probe_local_mesh("no-such-engine", timeout_s=60)
        self.assertFalse(status.get("available"))
        self.assertTrue(status.get("reason"))

    def test_a_failing_worker_leaves_the_server_alive(self):
        """A dead worker may fail the request; it may not fail the server."""
        with tempfile.TemporaryDirectory(prefix="cartoon-mesh-test-") as folder:
            with self.assertRaises(mesh_isolation.LocalMeshError):
                mesh_isolation.run_local_mesh(
                    "no-such-engine",
                    os.path.join(folder, "img_0.png"),
                    os.path.join(folder, "out"),
                    timeout_s=60,
                )
        # The API server is still perfectly usable.
        client = TestClient(server.app)
        self.assertEqual(client.get("/api/ping").status_code, 200)

    def test_the_worker_reports_a_failure_instead_of_crashing(self):
        import json
        import subprocess
        import sys as _sys

        with tempfile.TemporaryDirectory(prefix="cartoon-worker-test-") as folder:
            payload_path = os.path.join(folder, "payload.json")
            result_path = os.path.join(folder, "result.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump({"image_paths": [], "output_dir": folder, "kwargs": {}}, fh)
            completed = subprocess.run(
                [_sys.executable, mesh_isolation.WORKER, "build", "no-such-engine", payload_path, result_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertNotEqual(completed.returncode, 0)
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)
        self.assertFalse(result["ok"])
        self.assertIn("no-such-engine", result["error"])


if __name__ == "__main__":
    unittest.main()
