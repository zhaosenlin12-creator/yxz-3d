"""Hunyuan3D-2 mini runner for Cartoon Print Studio.

Replacement for TripoSR when higher quality 3D is needed.
Hunyuan3D-2 mini (3.5B params) fits in 6GB VRAM with bfloat16 + low octree.
"""
from __future__ import annotations
import os, time, threading, glob
from typing import List, Optional

# Resolve project root dynamically so the module works in any install dir.
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CARTOON_ROOT") or (os.path.dirname(_HERE) if os.path.basename(_HERE) == "backend" else _HERE)
os.environ.setdefault("HF_HOME", os.path.join(ROOT, "models"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import sys as _sys
import progress as _pg
if os.path.isdir(os.path.join(ROOT, "models", "rmbg-1.4")):
    _sys.path.insert(0, os.path.join(ROOT, "models", "rmbg-1.4"))
_sys.path.insert(0, os.path.dirname(_HERE))

# --- Heavy deps (torch + hy3dgen) are lazy-loaded so the module can be
# imported on installs that ship without GPU tooling. ---
torch = None
GenHunyuan3DDiTPipeline = None
SimplifyMesh = None
MeshDecodeModel = None
Hunyuan3DDiTFlowMatchingPipeline = None
_HEAVY_OK = False
_HEAVY_ERR = "not loaded yet"

def _ensure_packages():
    """Check the minimal runtime used by the manual Hunyuan loader.

    The installed hy3dgen package no longer exports several old pipeline
    symbols, so importing only the package here keeps availability checks
    truthful while ``warmup`` imports the supported components it needs.
    """
    global torch, _HEAVY_OK, _HEAVY_ERR
    if _HEAVY_OK or _HEAVY_ERR != "not loaded yet":
        return _HEAVY_OK
    try:
        import torch as _t
        import hy3dgen  # noqa: F401
        torch = _t
        _HEAVY_OK = True
        _HEAVY_ERR = ""
    except Exception as _e:
        _HEAVY_OK = False
        _HEAVY_ERR = str(_e)
        print(f"[hunyuan_runner] heavy deps unavailable: {_e}", flush=True)
    return _HEAVY_OK




_PIPE = None
_LOCK = threading.Lock()
_CKPT_PATH = None
_CFG_PATH = None


def _find_local_ckpt():
    base = os.path.expanduser(r"~\.cache\huggingface\hub\models--tencent--Hunyuan3D-2mini\snapshots")
    if not os.path.isdir(base):
        return None
    for snap in glob.glob(os.path.join(base, "*")):
        c = os.path.join(snap, "hunyuan3d-dit-v2-mini", "model.fp16.safetensors")
        if os.path.isfile(c):
            return c
    return None




def _safe_to(module, device, dtype):
    """Replace module.to() when meta tensors are involved."""
    import torch
    import torch.nn as nn
    if not isinstance(module, nn.Module):
        # not a Module (e.g. ImageProcessorV2) - just call .to() directly
        return module.to(device) if hasattr(module, "to") else module
    for name, p in list(module.named_parameters(recurse=True)):
        if p.device.type == "meta":
            new = nn.Parameter(torch.empty(p.shape, device=device, dtype=dtype or p.dtype))
            parent = module
            parts = name.split(".")
            for q in parts[:-1]:
                parent = getattr(parent, q)
            setattr(parent, parts[-1], new)
    for name, b in list(module.named_buffers(recurse=True)):
        if b.device.type == "meta":
            new = torch.empty(b.shape, device=device, dtype=dtype or b.dtype)
            parent = module
            parts = name.split(".")
            for q in parts[:-1]:
                parent = getattr(parent, q)
            setattr(parent, parts[-1], new)
    return module.to(device, dtype)

def _find_local_config():
    base = os.path.expanduser(r"~\.cache\huggingface\hub\models--tencent--Hunyuan3D-2mini\snapshots")
    if not os.path.isdir(base):
        return None
    for snap in glob.glob(os.path.join(base, "*")):
        c = os.path.join(snap, "hunyuan3d-dit-v2-mini", "config.yaml")
        if os.path.isfile(c):
            return c
    return None


def warmup():
    """Load weights into a Pipeline without triggering the buggy __init__ .to()."""
    global _PIPE, _CKPT_PATH, _CFG_PATH
    if _PIPE is not None:
        return True
    _ensure_packages()
    import torch, yaml, safetensors.torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dgen.shapegen.pipelines import instantiate_from_config
    import hy3dgen.shapegen.pipelines as _hp
    ckpt_path = _find_local_ckpt()
    cfg_path = _find_local_config()
    if not ckpt_path or not cfg_path:
        print("[hunyuan] model files missing in cache; not loaded")
        return False

    print("[hunyuan] loading weights via safetensors + manual init ...")
    t0 = time.time()
    with open(cfg_path, "r") as f:
        config = yaml.safe_load(f)
    sf = safetensors.torch.load_file(ckpt_path, device="cpu")
    parsed = {}
    for k, v in sf.items():
        n = k.split(".")[0]
        rest = k[len(n) + 1:]
        parsed.setdefault(n, {})[rest] = v

    # Manually instantiate and load weights per component
    vae = instantiate_from_config(config["vae"])
    vae.load_state_dict(parsed["vae"])
    model = instantiate_from_config(config["model"])
    model.load_state_dict(parsed["model"])
    conditioner = instantiate_from_config(config["conditioner"])
    if "conditioner" in parsed:
        conditioner.load_state_dict(parsed["conditioner"])
    image_processor = instantiate_from_config(config["image_processor"])
    scheduler = instantiate_from_config(config["scheduler"])

    # Bypass Pipeline.__init__() since its self.to(device) breaks on torch 2.5+
    import torch as _t
    pipe = Hunyuan3DDiTFlowMatchingPipeline.__new__(Hunyuan3DDiTFlowMatchingPipeline)
    pipe.vae = _safe_to(vae, "cuda", torch.float16)
    pipe.model = _safe_to(model, "cuda", torch.float16)
    pipe.conditioner = _safe_to(conditioner, "cuda", torch.float16)
    pipe.image_processor = _safe_to(image_processor, "cuda", torch.float16)
    pipe.scheduler = scheduler
    pipe.kwargs = {}
    pipe.device = _t.device("cuda")
    pipe.dtype = torch.float16
    pipe.model_cpu_offload_seq = "conditioner->model->vae"   # __init__ would set this
    pipe._exclude_from_cpu_offload = []

    _PIPE = pipe
    _CKPT_PATH = ckpt_path
    _CFG_PATH = cfg_path
    print(f"[hunyuan] loaded in {time.time()-t0:.1f}s")
    return True


def is_available() -> bool:
    """Quick check whether torch + the Hunyuan3D packages are importable.
    Keeps the server startup quiet on installs that ship without torch.
    """
    return get_status()["available"]


def get_status() -> dict:
    """Return a truthful, lightweight readiness report for the UI."""
    if _PIPE is not None:
        return {"available": True, "ready": True, "reason": "loaded"}
    try:
        import torch
        if not torch.cuda.is_available():
            return {"available": False, "ready": False, "reason": "CUDA GPU unavailable"}
        if not _find_local_ckpt() or not _find_local_config():
            return {"available": False, "ready": False, "reason": "local model files missing"}
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: F401
        return {"available": True, "ready": False, "reason": "model loading on first use"}
    except Exception as exc:
        return {"available": False, "ready": False, "reason": str(exc)}


def unload():
    """Free Hunyuan3D weights from GPU so TripoSR can run on 6GB cards."""
    global _PIPE
    if _PIPE is None:
        return
    try:
        for attr in ("model", "vae", "conditioner"):
            obj = getattr(_PIPE, attr, None)
            if obj is None: continue
            try: obj.to("cpu")
            except Exception: pass
    except Exception as e:
        print(f"[hunyuan] unload warning: {e}")
    _PIPE = None
    try:
        import torch as _t
        _t.cuda.empty_cache()
    except Exception: pass
    print("[hunyuan] unloaded")


def is_ready():
    return _PIPE is not None


def generate_3d(image_paths, output_dir, *,
                num_inference_steps=5,
                octree_resolution=64,
                mc_level=0.0):
    """image_paths: str or list. Returns dict with mesh paths."""
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    if _PIPE is None:
        warmup()
    if _PIPE is None:
        # last-resort fallback: load now
        warmup()
    if _PIPE is None:
        raise RuntimeError("Hunyuan3D-2 mini is not loaded - model files missing")
    os.makedirs(output_dir, exist_ok=True)
    from PIL import Image
    # Server passes session_id via env var PROGRESS_SID so we can write progress events.
    import os as _os_progress_helper
    _pg_sid = _os_progress_helper.environ.get("PROGRESS_SID", "")
    from PIL import Image
    # Background removal: Hunyuan expects RGBA with transparent bg; RGB previews need it.
    try:
        from rmbg_remove import remove_bg as _rmbg
        from PIL import ImageFilter
        import numpy as _np
        _raw = _rmbg(Image.open(image_paths[0]).convert("RGB"))
        # Soften the alpha mask so marching cubes finds a clean iso-surface.
        _a = _raw.split()[-1].filter(ImageFilter.GaussianBlur(8))
        _arr = (_np.array(_a).astype(_np.float32) / 255.0)
        _soft = (_arr * 255).astype(_np.uint8)
        _raw.putalpha(Image.fromarray(_soft, "L"))
        img = _raw
    except Exception as _e:
        print(f"[hunyuan] bg removal failed ({_e}); using plain RGBA", flush=True)
        img = Image.open(image_paths[0]).convert("RGBA")
    import torch
    with _LOCK:
        torch.cuda.empty_cache()
        # Free up TripoSR (~1.5GB) before inference to stay under 6GB VRAM
        try:
            import triposr_runner as _tr
            _tr.unload()
        except Exception:
            pass
        import torch as _t
        _t.cuda.empty_cache()
        # Adaptive iso: diffusion logits can sit above/below 0 depending on input.
        # Try a series of mc_level values from the requested one downward.
        last_err = None
        mesh = None
        # Sweep BOTH directions around the requested iso. Default Hunyuan is ~0;
        # cartoon / sparse shapes often need POSITIVE values (less surface).
        _levels = [mc_level + 0.05, mc_level + 0.10, mc_level + 0.15,
                   mc_level, mc_level - 0.01, mc_level - 0.03, mc_level - 0.07, mc_level - 0.15]
        n_levels = len(_levels)
        for _li, _lv in enumerate(_levels):
            if _pg_sid:
                _pg.Progress(_pg_sid, "3d-hunyuan").emit(f"diffusion-{_li+1}/{n_levels}", 20 + _li*8, f"扩散采样 {num_inference_steps} 步 (mc={_lv:.2f})")
            t0 = time.time()
            try:
                _out = _PIPE(image=img,
                             num_inference_steps=num_inference_steps,
                             octree_resolution=octree_resolution,
                             mc_level=_lv)
                inference_s = time.time() - t0
                print(f"[hunyuan] _out type={type(_out).__name__}", flush=True)
                try:
                    if isinstance(_out, (list, tuple)):
                        print(f"[hunyuan] _out len={len(_out)}", flush=True)
                        for _i, _v in enumerate(_out):
                            print(f"[hunyuan] _out[{_i}] type={type(_v).__name__}", flush=True)
                            if hasattr(_v, "vertices"):
                                print(f"[hunyuan] _out[{_i}].vertices={len(_v.vertices)}", flush=True)
                            elif hasattr(_v, "geometries"):
                                print(f"[hunyuan] _out[{_i}] has {len(_v.geometries)} geometries", flush=True)
                        mesh = _out[0]
                    elif hasattr(_out, "vertices"):
                        mesh = _out
                    elif isinstance(_out, dict):
                        print(f"[hunyuan] _out keys={list(_out.keys())}", flush=True)
                        mesh = _out.get("mesh") or _out.get("vertices")
                    else:
                        mesh = _out
                except Exception as _diag_e:
                    print(f"[hunyuan] diag error: {_diag_e}", flush=True)
                    mesh = _out[0] if isinstance(_out, (list, tuple)) else _out
                if mesh is not None and hasattr(mesh, "vertices") and len(mesh.vertices) > 100:
                    print(f"[hunyuan] inference {inference_s:.1f}s mc_level={_lv} verts={len(mesh.vertices)}", flush=True)
                    break
                else:
                    v = len(mesh.vertices) if (mesh is not None and hasattr(mesh, "vertices")) else None
                    print(f"[hunyuan] mc_level={_lv} insufficient verts={v} (mesh={type(mesh).__name__ if mesh is not None else None})", flush=True)
                    mesh = None
            except Exception as e:
                last_err = e
                print(f"[hunyuan] mc_level={_lv} failed: {e}", flush=True)
                continue
        if mesh is None:
            if _pg_sid:
                _pg.Progress(_pg_sid, "3d-hunyuan").fail("多次 iso 都没找到表面，请换一张图重试")
            raise RuntimeError(f"Hunyuan3D produced no surface across multiple mc_levels. last_err={last_err}")
        inference_s = time.time() - t0
        print(f"[hunyuan] inference {inference_s:.1f}s, verts={len(mesh.vertices) if hasattr(mesh,'vertices') else '?'}")

    import trimesh
    if isinstance(mesh, trimesh.Scene):
        parts = list(mesh.geometry.values())
        if len(parts) == 1:
            mesh = parts[0]
        else:
            mesh = trimesh.util.concatenate(parts)
    mesh.apply_translation(-mesh.centroid)
    if max(mesh.extents) > 0:
        mesh.apply_scale(100.0 / max(mesh.extents))

    glb_path = os.path.join(output_dir, "mesh.glb")
    obj_path = os.path.join(output_dir, "mesh.obj")
    stl_path = os.path.join(output_dir, "mesh.stl")
    mesh.export(glb_path)
    mesh.export(obj_path)
    mesh.export(stl_path)
    if _pg_sid:
        _pg.Progress(_pg_sid, "3d-hunyuan").done(f"导出完成 ({len(mesh.faces)} 面)")

    return {
        "faces": len(mesh.faces),
        "extents_mm": mesh.extents.tolist(),
        "mesh_glb": glb_path,
        "mesh_obj": obj_path,
        "mesh_stl": stl_path,
        "engine": "hunyuan3d-2mini",
        "inference_s": inference_s,
        "params": {"num_inference_steps": num_inference_steps, "octree_resolution": octree_resolution},
    }


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("usage: hunyuan_runner.py <image.png> [steps] [octree]")
        sys.exit(1)
    img = sys.argv[1]
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    octree = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    out = ROOT + r"\data\_hunyuan_smoke"
    info = generate_3d(img, out, num_inference_steps=steps, octree_resolution=octree)
    print(json.dumps(info, ensure_ascii=False, indent=2))
