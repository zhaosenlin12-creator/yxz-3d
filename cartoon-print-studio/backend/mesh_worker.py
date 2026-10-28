"""Run one local mesh build in a child process.

The local TripoSR and Hunyuan3D runners load multi-gigabyte models into
memory.  When they run inside the API server, a machine that runs out of
commit charge takes the whole server down with it: the visitor's chat
dies, the request fails with a connection reset and the supervisor has to
restart everything.

Running them in a child process keeps a memory blow-up contained.  The
worker may die, but the API server stays up and the engine chain can move
on to the next provider.

Usage:
    python mesh_worker.py build <runner> <payload.json> <result.json>
    python mesh_worker.py probe <runner> <payload.json> <result.json>

The result is written to a file rather than stdout because the runners
print progress of their own.
"""
import json
import os
import sys
import traceback


def _probe(runner: str) -> dict:
    """Report whether a local engine can run, without loading any weights.

    This also runs in the child process on purpose: importing torch and
    touching CUDA in the API server would hold a GPU context there and
    take memory away from the worker that actually builds the mesh.
    """
    if runner == "triposr":
        import triposr_runner as engine
        return {"available": bool(engine.is_available())}
    if runner == "hunyuan":
        import hunyuan_runner as engine
        return engine.get_status()
    raise ValueError(f"unknown runner: {runner}")


def _build(runner: str, payload: dict) -> dict:
    image_paths = payload.get("image_paths")
    output_dir = payload["output_dir"]
    kwargs = payload.get("kwargs") or {}

    if runner == "triposr":
        import triposr_runner as engine
        return engine.generate_3d(image_paths, output_dir, **kwargs)
    if runner == "hunyuan":
        import hunyuan_runner as engine
        return engine.generate_3d(image_paths, output_dir, **kwargs)
    raise ValueError(f"unknown runner: {runner}")


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print(
            "usage: mesh_worker.py <build|probe> <runner> <payload.json> <result.json>",
            file=sys.stderr,
        )
        return 2

    mode, runner, payload_path, result_path = argv[1], argv[2], argv[3], argv[4]
    try:
        with open(payload_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if mode == "probe":
            info = _probe(runner)
        else:
            info = _build(runner, payload)
        result = {"ok": True, "info": info}
    except BaseException as exc:  # noqa: BLE001 - the worker reports everything
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    try:
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    except Exception:
        # Nothing left to do: the parent will notice the missing file.
        return 1
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
