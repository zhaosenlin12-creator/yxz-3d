"""Generate the YXZ body mesh from the reference art with Hunyuan3D-2.

The upstream AIRI runtime wants a rigged VRM.  Rigging only works on a
clean body, and a body only comes out of a scan or a reconstruction, so
this is step one of the rebuild: the reference render in, a manifold mesh
out, in the exported frame (Y up, the character facing +Z).

The weights are Hunyuan3D-2 (Tencent) rather than the mini distillation the
backend ships, because the mini cannot hold a raised arm together: the
character in the reference is waving, and the wave is the whole silhouette.

  python run_shape.py --image <png> --out <dir> [--steps 30] [--octree 256]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import torch
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent
                       / "cartoon-print-studio" / "backend"))


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt-dir", default=r"D:\cache\hf\hunyuan3d-2\hunyuan3d-dit-v2-0")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--octree", type=int, default=256)
    ap.add_argument("--mc-level", type=float, default=0.0)
    ap.add_argument("--scale", type=float, default=1.7,
                    help="height of the exported body in metres")
    return ap.parse_args()


def _safe_to(module, device, dtype):
    """Move a module to the device, replacing meta tensors on the way.

    The upstream pipeline builds part of its graph on the meta device, so a
    plain .to() leaves half the weights unloaded.
    """
    import torch.nn as nn
    if not isinstance(module, nn.Module):
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


def build_pipeline(ckpt_dir: Path):
    from hy3dgen.shapegen.pipelines import instantiate_from_config
    from hy3dgen.shapegen.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    from safetensors.torch import load_file

    config = yaml.safe_load((ckpt_dir / "config.yaml").read_text(encoding="utf-8"))
    state = load_file(str(ckpt_dir / "model.fp16.safetensors"), device="cpu")
    parsed: dict = {}
    for key, value in state.items():
        head = key.split(".")[0]
        parsed.setdefault(head, {})[key[len(head) + 1:]] = value

    vae = instantiate_from_config(config["vae"])
    vae.load_state_dict(parsed["vae"])
    model = instantiate_from_config(config["model"])
    model.load_state_dict(parsed["model"])
    conditioner = instantiate_from_config(config["conditioner"])
    if "conditioner" in parsed:
        conditioner.load_state_dict(parsed["conditioner"])
    image_processor = instantiate_from_config(config["image_processor"])
    scheduler = instantiate_from_config(config["scheduler"])

    pipe = Hunyuan3DDiTFlowMatchingPipeline.__new__(Hunyuan3DDiTFlowMatchingPipeline)
    pipe.vae = _safe_to(vae, "cuda", torch.float16)
    pipe.model = _safe_to(model, "cuda", torch.float16)
    pipe.conditioner = _safe_to(conditioner, "cuda", torch.float16)
    pipe.image_processor = _safe_to(image_processor, "cuda", torch.float16)
    pipe.scheduler = scheduler
    pipe.kwargs = {}
    pipe.device = torch.device("cuda")
    pipe.dtype = torch.float16
    pipe.model_cpu_offload_seq = "conditioner->model->vae"
    pipe._exclude_from_cpu_offload = []
    return pipe


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[shape] loading {args.ckpt_dir}", flush=True)
    t0 = time.time()
    pipe = build_pipeline(Path(args.ckpt_dir))
    print(f"[shape] pipeline ready in {time.time() - t0:.1f}s", flush=True)

    image = Image.open(args.image).convert("RGBA")
    print(f"[shape] image {image.size} alpha={image.getchannel('A').getextrema()}", flush=True)

    # The diffusion logits sit above or below zero depending on the input,
    # and a single iso value is a coin flip.  Sweep outwards from the
    # requested one until a surface comes out.
    levels = [args.mc_level + d for d in (0.05, 0.10, 0.0, -0.01, -0.03, -0.07, -0.15)]
    mesh = None
    used = None
    for level in levels:
        torch.cuda.empty_cache()
        started = time.time()
        try:
            produced = pipe(image=image,
                            num_inference_steps=args.steps,
                            octree_resolution=args.octree,
                            mc_level=level)
        except Exception as exc:  # noqa: BLE001
            print(f"[shape] mc_level={level} failed: {exc}", flush=True)
            continue
        candidate = produced[0] if isinstance(produced, (list, tuple)) else produced
        vertex_data = getattr(candidate, "vertices", None)
        verts = len(vertex_data) if vertex_data is not None else 0
        print(f"[shape] mc_level={level} verts={verts} in {time.time() - started:.1f}s", flush=True)
        if verts > 100:
            mesh = candidate
            used = level
            break
    if mesh is None:
        raise SystemExit("[shape] no surface came out of any iso level")

    import trimesh
    if isinstance(mesh, trimesh.Scene):
        parts = list(mesh.geometry.values())
        mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)

    # Centre on the body and stand it on the ground: feet at y=0, the
    # character facing +Z, which is the frame the runtime's look-at and the
    # author's own rig scripts both assume.
    mesh.apply_translation(-mesh.centroid)
    bounds = mesh.bounds
    height = float(bounds[1][1] - bounds[0][1])
    if height > 0:
        mesh.apply_scale(args.scale / height)
    mesh.apply_translation([0.0, -float(mesh.bounds[0][1]), 0.0])

    glb = out / "body.glb"
    mesh.export(glb)
    mesh.export(out / "body.obj")
    print(f"[shape] wrote {glb} verts={len(mesh.vertices)} faces={len(mesh.faces)} "
          f"mc={used} extents={mesh.extents.tolist()}", flush=True)


if __name__ == "__main__":
    main()