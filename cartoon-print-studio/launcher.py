"""Cartoon Print Studio launcher.

When packaged with PyInstaller, this script is the .exe entry point.
It:
  1. Starts the FastAPI backend on 127.0.0.1:8000 (in a worker thread)
  2. Opens the user's browser to the app URL
  3. Waits for Ctrl-C to shut down

Falls back to `python -m uvicorn server:app --app-dir <backend>` if direct
import isn't possible (e.g. when run from source).
"""
from __future__ import annotations
import os, sys, time, threading, webbrowser, subprocess
from pathlib import Path

# ROOT = the bundle dir (in --onedir mode this is <install>/_internal)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# In --onedir mode PyInstaller unpacks into <install>/_internal but our project
# layout (data/ stays next to the exe, and frontend/ ships inside _internal/)
# means server.py needs a few well-defined paths. We compute them here and
# expose them via env vars so server.py and the bundled backend agree.
INSTALL_ROOT = ROOT.parent if ROOT.name == "_internal" else ROOT
BACKEND = ROOT / "backend"
# frontend/ is bundled inside _internal/, so prefer that path; fall back to
# the install dir if a deployment puts frontend next to the exe instead.
_internal_frontend = ROOT / "frontend"
_install_frontend = INSTALL_ROOT / "frontend"
if _internal_frontend.is_dir():
    FRONTEND = _internal_frontend
elif _install_frontend.is_dir():
    FRONTEND = _install_frontend
else:
    FRONTEND = _install_frontend  # let the server report a clear error
DATA = INSTALL_ROOT / "data"

HOST = "127.0.0.1"
PORT = int(os.environ.get("CARTOON_PORT", "8000"))
URL = f"http://{HOST}:{PORT}/"


def _serve_dev():
    """Source-mode: spawn uvicorn as a subprocess."""
    py = sys.executable
    cmd = [py, "-m", "uvicorn", "server:app", "--host", HOST, "--port", str(PORT), "--app-dir", str(BACKEND)]
    return subprocess.Popen(cmd)


def _serve_embedded():
    """Frozen mode: run uvicorn programmatically."""
    import uvicorn  # noqa: F401
    sys.path.insert(0, str(BACKEND))
    cfg = uvicorn.Config("server:app", host=HOST, port=PORT, log_level="info")
    srv = uvicorn.Server(cfg)
    # uvicorn.Server.run() blocks, so call in a thread
    def _run():
        srv.run()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return srv


def main():
    print("=" * 60)
    print(" Cartoon Print Studio  -  卡通 3D 打印工坊")
    print("=" * 60)
    print(f" Install: {INSTALL_ROOT}")
    print(f" Backend: {BACKEND}")
    print(f" Frontend: {FRONTEND}")
    print(f" Data:    {DATA}")
    print(f" URL: {URL}")
    print()
    # Tell server.py where the install dir lives so data/frontend resolve
    # consistently regardless of where the exe was launched from.
    os.environ["CARTOON_ROOT"] = str(INSTALL_ROOT)
    os.environ["CARTOON_FRONTEND_DIR"] = str(FRONTEND)
    os.environ["CARTOON_DATA_DIR"] = str(DATA)

    if getattr(sys, "frozen", False):
        srv = _serve_embedded()
    else:
        proc = _serve_dev()
        try:
            time.sleep(2.0)
            webbrowser.open(URL)
            print(f"Opened {URL} in browser")
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
        return

    try:
        time.sleep(2.0)
        webbrowser.open(URL)
        print(f"Opened {URL} in browser")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        srv.should_exit = True


if __name__ == "__main__":
    main()
