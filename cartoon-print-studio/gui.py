"""Cartoon Print Studio desktop GUI shell.

Wraps the existing FastAPI backend + static HTML frontend in a native-looking
PyWebView window. Doubling the exe launches a real OS window (no browser, no
console), titled "Cartoon Print Studio", with a sane default size. Backend
shutdown is wired to window close so killing the window stops the server.
"""
from __future__ import annotations
import os, sys, time, threading, subprocess
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("CARTOON_PORT", "8000"))
URL = f"http://{HOST}:{PORT}/"

# Locate the bundle dir (in --onedir this is <install>/_internal)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL_ROOT = ROOT.parent if ROOT.name == "_internal" else ROOT
BACKEND = ROOT / "backend"
INTERNAL_FRONTEND = ROOT / "frontend"
INSTALL_FRONTEND = INSTALL_ROOT / "frontend"
if INTERNAL_FRONTEND.is_dir():
    FRONTEND = INTERNAL_FRONTEND
elif INSTALL_FRONTEND.is_dir():
    FRONTEND = INSTALL_FRONTEND
else:
    FRONTEND = INSTALL_FRONTEND
DATA = INSTALL_ROOT / "data"

# Export the same env vars the embedded server.py understands so data and
# frontend paths resolve consistently regardless of where the exe lives.
os.environ["CARTOON_ROOT"] = str(INSTALL_ROOT)
os.environ["CARTOON_FRONTEND_DIR"] = str(FRONTEND)
os.environ["CARTOON_DATA_DIR"] = str(DATA)


def _start_backend_subprocess():
    """Source-mode launcher: spawn uvicorn in a child process so it can be
    cleanly killed when the window closes."""
    py = sys.executable
    cmd = [py, "-m", "uvicorn", "server:app",
           "--host", HOST, "--port", str(PORT),
           "--app-dir", str(BACKEND), "--log-level", "info"]
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW so uvicorn doesn't pop its own console window
        creationflags = 0x08000000
    return subprocess.Popen(cmd, creationflags=creationflags)


def _start_backend_embedded():
    """Frozen-mode launcher: run uvicorn in a thread."""
    import uvicorn
    sys.path.insert(0, str(BACKEND))
    cfg = uvicorn.Config("server:app", host=HOST, port=PORT, log_level="info")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    return srv


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    """Poll the server until it answers or we time out."""
    import urllib.request, urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status < 500:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.4)
    return False


def main():
    print("=" * 60)
    print(" Cartoon Print Studio")
    print("=" * 60)
    print(f" Install:  {INSTALL_ROOT}")
    print(f" Backend:  {BACKEND}")
    print(f" Frontend: {FRONTEND}")
    print(f" Data:     {DATA}")
    print(f" URL:      {URL}")
    print()

    if getattr(sys, "frozen", False):
        srv = _start_backend_embedded()
        proc = None
    else:
        proc = _start_backend_subprocess()
        srv = None

    try:
        if not _wait_for_server(URL, timeout=30):
            print(f"[gui] backend did not become ready at {URL}", flush=True)
            if proc is not None:
                proc.terminate()
            sys.exit(1)

        # Late import: pywebview can pull in Windows COM bindings; only load
        # them once we know the backend is up so a port collision fails fast.
        import webview

        window = webview.create_window(
            title="Cartoon Print Studio",
            url=URL,
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            confirm_close=False,
            text_select=True,
        )
        webview.start()
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        if srv is not None:
            try:
                srv.should_exit = True
            except Exception:
                pass


if __name__ == "__main__":
    main()
