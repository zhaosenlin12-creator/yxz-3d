"""Background removal using BriaRMBG (RMBG-1.4). Local weights, no internet needed at runtime.

This module is optional: when torch or the bundled model weights are not
available the module still imports successfully. Callers must check
`is_available()` before calling `remove_bg()`.
"""
import os, sys
try:
    import torch  # noqa: F401
    _TORCH_OK = True
except Exception:
    torch = None  # type: ignore
    _TORCH_OK = False
import numpy as np
from PIL import Image

# Resolve project root relative to this file so the module works from any
# install directory (PyInstaller --onedir, dev checkout, or system install).
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE) if os.path.basename(_HERE) == "backend" else _HERE
ROOT = _PROJECT_ROOT
RMBG_DIR = os.path.join(ROOT, "models", "rmbg-1.4")

if _TORCH_OK and os.path.isdir(RMBG_DIR):
    if RMBG_DIR not in sys.path:
        sys.path.insert(0, RMBG_DIR)
    try:
        from briarmbg import BriaRMBG  # noqa: F401
        from utilities import preprocess_image, postprocess_image  # noqa: F401
        _RMBG_OK = True
    except Exception:
        BriaRMBG = None  # type: ignore
        preprocess_image = None  # type: ignore
        postprocess_image = None  # type: ignore
        _RMBG_OK = False
else:
    BriaRMBG = None  # type: ignore
    preprocess_image = None  # type: ignore
    postprocess_image = None  # type: ignore
    _RMBG_OK = False

_MODEL = None

def is_available() -> bool:
    return _TORCH_OK and _RMBG_OK


def get_model():
    global _MODEL
    if _MODEL is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _MODEL = BriaRMBG.from_pretrained(RMBG_DIR).to(device).eval()
    return _MODEL


def remove_bg(img: Image.Image, input_size=(1024, 1024)) -> Image.Image:
    """img: PIL RGB. Returns PIL RGBA with transparent bg."""
    net = get_model()
    device = next(net.parameters()).device
    orig = np.array(img.convert("RGB"))
    h, w = orig.shape[:2]
    t = preprocess_image(orig, list(input_size)).to(device)
    with torch.no_grad():
        out = net(t)
    mask = postprocess_image(out[0][0], [h, w])  # (H,W) uint8
    rgba = img.convert("RGBA")
    rgba.putalpha(Image.fromarray(mask))
    return rgba


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_smoke_sd.png")
    dst = os.path.splitext(src)[0] + "_nobg.png"
    img = Image.open(src)
    out = remove_bg(img)
    out.save(dst)
    print("saved", dst, out.size)
