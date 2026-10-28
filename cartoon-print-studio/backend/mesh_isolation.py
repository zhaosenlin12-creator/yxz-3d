"""Keep the local mesh builders out of the API server process.

Both local engines (TripoSR and Hunyuan3D) pull multi-gigabyte models
into memory.  On a machine that is already busy, that allocation can
exceed the Windows commit limit -- and the kernel does not raise a
catchable Python exception in that case, it simply kills the process.
When that process is the API server, every open chat turn dies with it
and the visitor is left staring at a frozen screen.

Running the builders in a child process means the worst case is a dead
worker instead of a dead server.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(BACKEND_DIR, "mesh_worker.py")

# Probing costs a couple of seconds (torch has to be imported), and the
# answer only changes when the installation changes -- so keep it around
# for a minute instead of asking on every page load.
_PROBE_CACHE: dict[str, tuple[float, dict]] = {}
_PROBE_TTL_SECONDS = 60.0


class LocalMeshError(RuntimeError):
    """The local builder failed or was killed; the server is still fine."""


def _run_worker(
    mode: str,
    runner: str,
    payload: dict,
    *,
    timeout_s: int,
    log_dir: str,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="cartoon-mesh-") as scratch:
        payload_path = os.path.join(scratch, "payload.json")
        result_path = os.path.join(scratch, "result.json")
        with open(payload_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

        env = dict(os.environ)
        # The worker imports the runners from this folder.
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = BACKEND_DIR + (os.pathsep + existing if existing else "")
        env["PYTHONUNBUFFERED"] = "1"

        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL
        log_handle = None
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, f"mesh-worker-{runner}-{int(time.time())}.log")
                log_handle = open(log_path, "ab")
                stdout_target = log_handle
                stderr_target = log_handle
            except Exception:
                log_handle = None

        try:
            process = subprocess.Popen(
                [sys.executable, WORKER, mode, runner, payload_path, result_path],
                cwd=BACKEND_DIR,
                env=env,
                stdout=stdout_target,
                stderr=stderr_target,
            )
            try:
                code = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
                raise LocalMeshError(f"本地 3D 生成超过 {timeout_s} 秒未完成，已停止")
        finally:
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass

        result: dict = {}
        if os.path.isfile(result_path):
            try:
                with open(result_path, "r", encoding="utf-8") as fh:
                    result = json.load(fh)
            except Exception:
                result = {}

        if not result.get("ok"):
            detail = result.get("error") or ""
            if not detail:
                # No result file: the worker was killed before it could
                # report -- almost always the memory limit.
                detail = f"本地 3D 进程异常退出（代码 {code}）"
            raise LocalMeshError(detail)

        info = result.get("info") or {}
        if not isinstance(info, dict):
            raise LocalMeshError("本地 3D 返回的数据无法识别")
        return info


def probe_local_mesh(runner: str, *, timeout_s: int = 180, log_dir: str = "") -> dict:
    """Ask a local engine whether it could run, without loading any weights.

    Never raises: a broken engine simply reports itself as unavailable.
    """
    now = time.monotonic()
    cached = _PROBE_CACHE.get(runner)
    if cached and (now - cached[0]) < _PROBE_TTL_SECONDS:
        return cached[1]

    try:
        info = _run_worker("probe", runner, {}, timeout_s=timeout_s, log_dir=log_dir)
    except LocalMeshError as exc:
        info = {"available": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - a probe must never break a page
        info = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    _PROBE_CACHE[runner] = (now, info)
    return info


def run_local_mesh(
    runner: str,
    image_paths: Any,
    output_dir: str,
    *,
    timeout_s: int = 900,
    log_dir: str = "",
    **kwargs: Any,
) -> dict:
    """Build a mesh in a child process and return the runner's result dict.

    Raises LocalMeshError when the worker fails, times out or is killed.
    """
    os.makedirs(output_dir, exist_ok=True)

    payload = {
        "image_paths": image_paths,
        "output_dir": output_dir,
        "kwargs": kwargs,
    }
    return _run_worker("build", runner, payload, timeout_s=timeout_s, log_dir=log_dir)
