"""SD 1.5 inference client using diffusers (loaded once at startup).

Heavy imports (torch/diffusers) are deferred so the module can be imported
without bundling the 2 GB torch runtime when only cloud providers are used.
"""
import os, sys, time, threading

# Resolve ROOT dynamically (env override works in packaged mode)
_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CKPT = os.path.join(_ROOT, "ai", "forge-webui", "models", "Stable-diffusion", "v1-5-pruned-emaonly.safetensors")
CFG  = os.path.join(_ROOT, "ai", "forge-webui", "backend", "huggingface", "runwayml", "stable-diffusion-v1-5")

# Lazy-loaded heavy deps (only when local SD is actually requested)
_torch = None
_np = None
_PIL_Image = None

def _import_heavy():
    global _torch, _np, _PIL_Image
    if _torch is None:
        import torch as _t
        import numpy as _n
        from PIL import Image as _I
        _torch = _t; _np = _n; _PIL_Image = _I
    return _torch, _np, _PIL_Image


_PIPE = None
_LOCK = threading.Lock()


# Cartoon-friendly prompt suffix. Appended automatically.
CARTOON_SUFFIX = ", cute cartoon style, chibi figurine, solid white background, simple shapes, friendly face, 3d print friendly, full body, high quality"


def _load():
    global _PIPE
    if _PIPE is not None:
        return _PIPE
    torch, _, _ = _import_heavy()
    from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
    pipe = StableDiffusionPipeline.from_single_file(
        CKPT,
        config=CFG,
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
        local_files_only=True,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_attention_slicing()
    pipe.enable_vae_tiling()
    pipe.enable_sequential_cpu_offload()
    _PIPE = pipe
    return pipe


def warmup():
    """Load models into memory so first request is fast."""
    _load()
    return True

def is_available() -> bool:
    """Return True if torch/diffusers can be loaded here. Used by the
    server to decide whether to invoke warmup() at startup. We probe torch
    without importing it so the startup stays quiet on GPU-less installs.
    """
    try:
        import importlib
        importlib.import_module("torch")
        return True
    except Exception:
        return False



def generate(prompt: str, *, n: int = 4, seed: int = 42, steps: int = 14, height: int = 384, width: int = 384):
    """Generate n images from prompt. Returns list of (PIL.Image, seed_int)."""
    torch, _, _ = _import_heavy()
    pipe = _load()
    full = prompt.strip() + CARTOON_SUFFIX
    seeds = [seed + i for i in range(n)]
    images = []
    with _LOCK:
        t0 = time.time()
        for s in seeds:
            torch.cuda.empty_cache()
            img = pipe(
                full,
                num_inference_steps=steps,
                guidance_scale=6.5,
                height=height,
                width=width,
                generator=torch.Generator(device="cpu").manual_seed(s),
            ).images[0]
            images.append(img)
        print(f"[sd] generated {n} imgs in {time.time()-t0:.1f}s")
    return list(zip(images, seeds))


if __name__ == "__main__":
    out = generate("a cute astronaut cat", n=2)
    for i, (img, s) in enumerate(out):
        path = f"_sd_test_{i}.png"
        img.save(path)
        print("saved", path, "seed", s)
