"""Smart background removal: detect dominant background color (corner sampling),
then build an alpha mask from distance/similarity to it. Works on textured bg too.
"""
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


def _corner_bg_color(arr: np.ndarray, margin: int = 8) -> np.ndarray:
    """Sample 4 corners to estimate background color (RGB)."""
    h, w = arr.shape[:2]
    m = margin
    samples = np.concatenate([
        arr[:m, :m].reshape(-1, 4),
        arr[:m, w - m:].reshape(-1, 4),
        arr[h - m:, :m].reshape(-1, 4),
        arr[h - m:, w - m:].reshape(-1, 4),
    ])
    return np.median(samples[..., :3], axis=0)


def remove_background_smart(img: Image.Image, tolerance: float = 28.0, feather_px: int = 2) -> Image.Image:
    """img: PIL RGB or RGBA. Returns RGBA with smart-removed bg."""
    arr = np.array(img.convert("RGBA")).copy()
    bg = _corner_bg_color(arr).astype(np.float32)
    rgb = arr[..., :3].astype(np.float32)
    # Per-pixel color distance from bg
    diff = np.sqrt(((rgb - bg) ** 2).sum(axis=-1))
    # Make mask: where diff > tolerance => subject
    mask = diff > tolerance
    alpha = (mask.astype(np.float32) * 255).astype(np.uint8)
    # Feather alpha edges with a small distance transform
    try:
        if feather_px > 0:
            inv = ~mask
            dist = distance_transform_edt(mask).astype(np.float32)
            soft = np.where(dist < feather_px, (dist / feather_px * 255.0).clip(0, 255), alpha)
            alpha = soft.astype(np.uint8)
    except Exception:
        pass
    arr[..., 3] = alpha
    return Image.fromarray(arr, mode="RGBA")


def remove_white_background(img: Image.Image, threshold: int = 235, feather: int = 3) -> Image.Image:
    arr = np.array(img.convert("RGBA")).copy()
    rgb = arr[..., :3].astype(np.int16)
    near_white = np.all(rgb >= threshold, axis=-1)
    alpha = np.where(near_white, 0, 255).astype(np.uint8)
    arr[..., 3] = alpha
    return Image.fromarray(arr, mode="RGBA")


def remove_background(img: Image.Image) -> Image.Image:
    """Main entry: pick white-bg or smart based on image characteristics."""
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    m = 8
    corners = np.concatenate([
        arr[:m, :m].reshape(-1, 3),
        arr[:m, w - m:].reshape(-1, 3),
        arr[h - m:, :m].reshape(-1, 3),
        arr[h - m:, w - m:].reshape(-1, 3),
    ]).astype(np.int16)
    med = np.median(corners, axis=0)
    is_white_bg = np.all(med >= 235)
    if is_white_bg:
        return remove_white_background(img, threshold=235)
    return remove_background_smart(img, tolerance=28.0, feather_px=2)


if __name__ == "__main__":
    import sys, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "data", "_smoke_sd.png")
    dst = os.path.splitext(src)[0] + "_nobg.png"
    out = remove_background(Image.open(src))
    out.save(dst)
    print("saved", dst, out.size)
