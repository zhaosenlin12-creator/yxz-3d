"""Repeatable browser regression for the creation workbench.

Run with:
    python tests/browser_qa.py [--base http://127.0.0.1:8010] [--out screenshots]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


WORKTREE = Path(__file__).resolve().parents[1]


def png_data_url(color=(40, 120, 200), size=(8, 8)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


class WorkbenchQA:
    def __init__(self, page, base_url: str):
        self.page = page
        self.base_url = base_url
        self.failures = []

    def check(self, condition, label):
        if condition:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}")
            self.failures.append(label)
        return bool(condition)

    def node_count(self):
        return self.page.locator("#canvas-world .canvas-node").count()

    def canvas_box(self):
        return self.page.locator("#canvas-viewport").bounding_box()

    def viewer_pixels(self):
        """Screenshot the 3D viewport and describe how varied it is."""
        shot = self.page.locator("#viewer").screenshot()
        image = Image.open(io.BytesIO(shot)).convert("RGB")
        colors = image.getcolors(maxcolors=image.width * image.height) or []
        return len(colors), image.tobytes()

    def check_viewer_renders(self, out_dir):
        """The Three.js viewport must show a model and react to the controls."""
        page = self.page
        page.evaluate(
            "() => { document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));"
            " document.querySelector('#step-prompt').classList.add('active'); }"
        )
        page.click("#btn-demo")
        page.wait_for_selector("#viewer canvas", timeout=60000)
        page.wait_for_timeout(2500)

        colors, first = self.viewer_pixels()
        self.check(colors > 8, f"the 3D viewport is not blank ({colors} distinct colours)")
        page.screenshot(path=str(out_dir / "viewer-3d.png"), full_page=False)

        box = page.locator("#viewer").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2 + 120, box["y"] + box["height"] / 2 + 40, steps=12)
        page.mouse.up()
        page.wait_for_timeout(700)
        _, after_orbit = self.viewer_pixels()
        self.check(after_orbit != first, "dragging the viewport rotates the model")

        page.mouse.wheel(0, -600)
        page.wait_for_timeout(700)
        _, after_zoom = self.viewer_pixels()
        self.check(after_zoom != after_orbit, "the wheel zooms the model")

        tools = page.locator("#viewer ~ * .viewer-toolbar .viewer-tool, .viewer-toolbar .viewer-tool")
        boxes = [tools.nth(index).bounding_box() for index in range(tools.count())]
        overlapping = []
        for i, one in enumerate(boxes):
            for two in boxes[i + 1:]:
                if not one or not two:
                    continue
                if (one["x"] < two["x"] + two["width"] and two["x"] < one["x"] + one["width"]
                        and one["y"] < two["y"] + two["height"] and two["y"] < one["y"] + one["height"]):
                    overlapping.append((i, boxes.index(two)))
        self.check(not overlapping, f"the viewer controls do not overlap ({overlapping})")

    def stub_generation(self):
        """Replace the slow preview generation with deterministic answers."""
        image = png_data_url()

        def handle_previews(route):
            try:
                requested = route.request.post_data_json.get("session_id") or "qa-session"
            except Exception:
                requested = "qa-session"
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"session_id": requested, "queued": True}))

        def handle_progress(route):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"events": [], "latest": {"step": "done", "message": "done"}}))

        def handle_result(route):
            body = {
                "session_id": "qa-session",
                "ready": True,
                "previews": [{"index": 0, "path": "/api/data/qa-session/previews/img_0.png", "b64": ""},
                             {"index": 1, "path": "/api/data/qa-session/previews/img_1.png", "b64": ""}],
                "specs": [{"caption": "front pose"}, {"caption": "waving pose"}],
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        def handle_preview_image(route):
            raw = base64.b64decode(image.split(",", 1)[1])
            route.fulfill(status=200, content_type="image/png", body=raw)

        self.page.route(lambda url: url.split("?")[0].endswith("/api/previews_v2"), handle_previews)
        self.page.route(lambda url: "/api/progress/" in url, handle_progress)
        self.page.route(lambda url: "/api/session/" in url and url.split("?")[0].endswith("/result"), handle_result)
        self.page.route(lambda url: "/api/data/qa-session/previews/" in url, handle_preview_image)

    def run(self, out_dir):
        page = self.page
        console_errors = []
        failed_requests = []
        page.on("console", self._console_handler(console_errors))
        page.on("requestfailed", lambda request: failed_requests.append(
            f"{request.method} {request.url} :: {request.failure}"))
        page.on("pageerror", lambda error: console_errors.append(f"pageerror: {error}"))

        self.stub_generation()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector("#step-workbench.active", timeout=15000)

        print("\n[1] workbench shell")
        self.check(page.locator("#canvas-viewport").is_visible(), "canvas viewport is visible")
        self.check(page.locator("#conversation-list").is_visible(), "chat panel is visible")
        self.check(page.locator("#workbench-inspector").is_visible(), "inspector is visible")
        self.check(page.locator("#canvas-empty").is_visible(), "empty state is shown")

        print("\n[2] canvas elements")
        page.click("#btn-canvas-note")
        box = self.canvas_box()
        page.mouse.click(box["x"] + 140, box["y"] + 140)
        self.check(self.node_count() == 1, "note is created on the canvas")
        self.check(page.locator("#canvas-empty").is_hidden(), "empty state hides with content")

        page.click("#btn-canvas-draw")
        page.mouse.move(box["x"] + 260, box["y"] + 160)
        page.mouse.down()
        page.mouse.move(box["x"] + 330, box["y"] + 210, steps=8)
        page.mouse.up()
        self.check(self.node_count() == 2, "freehand stroke is created")

        page.click("#btn-canvas-pan")
        note = page.locator("#canvas-world .canvas-node.note")
        before = note.bounding_box()
        handle = page.locator("#canvas-world .canvas-node.note .note-handle")
        grip = handle.bounding_box()
        page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
        page.mouse.down()
        page.mouse.move(grip["x"] + grip["width"] / 2 + 120, grip["y"] + grip["height"] / 2 + 60, steps=10)
        page.mouse.up()
        after = note.bounding_box()
        self.check(abs(after["x"] - before["x"]) > 20, "selected element can be dragged")

        page.click("#btn-canvas-undo")
        undone = note.bounding_box()
        self.check(abs(undone["x"] - before["x"]) < 4, "undo restores the previous position")
        page.click("#btn-canvas-redo")
        redone = note.bounding_box()
        self.check(abs(redone["x"] - after["x"]) < 4, "redo restores the moved position")

        page.keyboard.press("Delete")
        self.check(self.node_count() == 1, "keyboard delete removes the selection")

        print("\n[3] chat")
        page.fill("#chat-input", "one blue hero with an orange cape")
        page.click("#btn-chat-send")
        page.wait_for_selector(".chat-preview", timeout=15000)
        self.check(page.locator(".chat-preview").count() >= 2, "chat shows the generated preview set")
        self.check(page.locator("#conversation-list .chat-message.user").count() == 1,
                   "user message is recorded in the conversation")

        page.click(".chat-preview-actions button:has-text('放入画布')")
        self.check(self.node_count() == 2, "preview can be dropped on the canvas from chat")

        print("\n[4] prompt polish")
        page.fill("#chat-input", "blue kitten")
        page.click("#btn-chat-polish")
        page.wait_for_function(
            "() => { const b = document.querySelector('#btn-chat-polish');"
            " const m = document.querySelector('#chat-polish-message');"
            " return m && m.textContent.length > 0 && !b.disabled; }",
            timeout=15000)
        message = page.inner_text("#chat-polish-message")
        self.check(bool(message), f"polish reports a status: {message}")
        self.check(page.input_value("#chat-input") == "blue kitten",
                   "polish never overwrites the original prompt silently")
        self.check(not page.locator("#btn-chat-polish").is_disabled(),
                   "polish button is usable again after the request")
        if not page.locator("#chat-polish-preview").is_hidden():
            page.click("#btn-polish-apply")
            self.check(page.input_value("#chat-input") != "blue kitten",
                       "applying the suggestion updates the prompt")

        print("\n[5] voice fallback")
        page.click("#btn-chat-voice")
        voice_status = page.inner_text("#voice-status")
        self.check(bool(voice_status), f"voice control reports a status: {voice_status}")
        self.check(page.input_value("#chat-input") != "", "voice control keeps the typed prompt")
        page.click("#btn-chat-voice")
        self.check(page.locator("#btn-chat-voice").inner_text().strip() == "语音",
                   "voice control can be stopped again")

        print("\n[6] save and restore")
        page.fill("#workbench-project-title", "QA project")
        page.click("#btn-workbench-save")
        page.wait_for_timeout(1500)
        projects = page.evaluate("async () => (await (await fetch('/api/projects')).json()).projects")
        saved = [item for item in projects if item.get("name") == "QA project"]
        self.check(bool(saved), "project is stored on the local backend")
        if saved:
            detail = page.evaluate(
                "async (id) => (await (await fetch('/api/projects/' + id)).json())",
                saved[0]["id"])
            self.check(len(detail.get("canvas", {}).get("elements", [])) >= 1,
                       "canvas elements are persisted with the project")
            self.check(len(detail.get("messages", [])) >= 2,
                       "conversation is persisted with the project")

        print("\n[7] delivery panel")
        software = page.inner_text("#workbench-software-status")
        self.check(bool(software), f"software detection reports a status: {software}")
        self.check(page.locator("#workbench-software-list .software-row").count() > 0,
                   "software list is rendered")
        available = page.locator("#workbench-software-list .software-row.available button")
        if available.count():
            available.first.click()
            confirm = page.locator("#workbench-software-list .delivery-confirm")
            self.check(confirm.count() == 1, "opening asks for confirmation first")
            text = confirm.inner_text() if confirm.count() else ""
            self.check("Bambu" in text or "xTool" in text,
                       f"confirmation names the target software: {text.splitlines()[0] if text else ''}")
            self.check("STL" in text or "PNG" in text,
                       "confirmation names the file that will be handed over")
            confirm.locator("button:has-text('取消')").click()
            self.check(page.locator("#workbench-software-list .delivery-confirm").count() == 0,
                       "cancelling closes the confirmation without opening anything")

        print("\n[8] software path correction")
        editor = page.locator("#workbench-software-list .software-path-editor").first
        self.check(editor.count() == 1, "every software row offers a path editor")
        path_input = editor.locator(".software-path-input")
        self.check(path_input.count() == 1, "the path editor has an input for the executable")
        original_value = path_input.input_value()
        path_input.fill("")
        editor.locator("button:has-text('保存路径')").click()
        page.wait_for_timeout(800)
        status = page.inner_text("#workbench-software-status")
        self.check("路径" in status, f"an empty path is rejected with a readable message: {status}")
        path_input.fill(original_value)
        editor.locator("button:has-text('恢复自动检测')").click()
        page.wait_for_timeout(800)
        self.check(page.locator("#workbench-software-list .software-path-editor").count() > 0,
                   "the path editor survives a reset to automatic detection")

        print("\n[9] startup status")
        startup = page.locator("#workbench-startup-status")
        if startup.is_hidden():
            self.check(True, "no startup warning is shown when every service is available")
        else:
            self.check(bool(startup.inner_text().strip()),
                       "the startup notice explains what is unavailable")

        print("\n[10] responsive layout")
        for width, height in ((320, 720), (768, 900), (1024, 800), (1440, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            self.check(overflow <= 2, f"{width}px viewport has no horizontal overflow")
            self.check(page.locator("#canvas-viewport").bounding_box()["width"] > 100,
                       f"{width}px viewport keeps a usable canvas")
            page.screenshot(path=str(out_dir / f"workbench-{width}.png"), full_page=False)

        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / "workbench-full.png"), full_page=False)

        print("\n[11] 3D viewer")
        self.check_viewer_renders(out_dir)

        print("\n[12] console and network")
        ignored = [entry for entry in console_errors if "favicon" in entry.lower()]
        real_errors = [entry for entry in console_errors if entry not in ignored]
        self.check(not real_errors, f"no console errors ({real_errors[:3]})")
        real_failures = [entry for entry in failed_requests if "favicon" not in entry.lower()]
        self.check(not real_failures, f"no failed requests ({real_failures[:3]})")

    @staticmethod
    def _console_handler(sink):
        def handler(message):
            if message.type == "error":
                sink.append(f"{message.type}: {message.text}")
                print(f"  CONSOLE ERROR  {message.text}")
        return handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--out", default=str(WORKTREE / "logs" / "browser-qa"))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        runner = WorkbenchQA(page, args.base)
        try:
            runner.run(out_dir)
        finally:
            browser.close()

    print("\n" + "=" * 60)
    if runner.failures:
        print(f"FAILED {len(runner.failures)} check(s):")
        for failure in runner.failures:
            print(f"  - {failure}")
        return 1
    print("All browser checks passed.")
    print(f"Screenshots: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
