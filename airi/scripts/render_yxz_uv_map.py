"""Lay a YXZ asset's triangles out in texture space, with no browser.

The stage renders the character through the browser, so every picture of
it depends on the pose the character happened to be in when the shutter
went off.  That is fine for looking at the character and useless for
looking at a *mark*: the same texel lands on a different pixel from one
run to the next.  This renders the same file with no pose in it at all.

Every triangle is drawn where its own texture coordinates say it belongs
and painted with the colour the atlas has there, so the picture is the
head cut open and flattened.  What comes out shows the marks and puts a
texel coordinate on every one of them.

`--flat` paints the triangles a single colour instead, which shows the
geometry on its own: a pale shape with a torn edge is a tear in the
texture, and a hole with nothing behind it is a hole in the mesh.

Usage:
  python scripts/render_yxz_uv_map.py <vrm> <out.png> \
    [--y-min 0.08] [--y-max 0.43] [--flat]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from glb_json import read_glb
from render_yxz_uv_head import read_accessor, world_matrix


def raster_triangle(canvas, atlas, cols, rows):
    """Paint one triangle into the flat layout."""
    height, width = canvas.shape[:2]
    x0 = int(max(0, np.floor(cols.min())))
    x1 = int(min(width - 1, np.ceil(cols.max())))
    y0 = int(max(0, np.floor(rows.min())))
    y1 = int(min(height - 1, np.ceil(rows.max())))
    if x1 < x0 or y1 < y0:
        return
    ax, ay = cols[0], rows[0]
    bx, by = cols[1], rows[1]
    cx, cy = cols[2], rows[2]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(area) < 1e-9:
        return
    grid_x, grid_y = np.meshgrid(
        np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    w0 = ((bx - ax) * (grid_y - ay) - (by - ay) * (grid_x - ax)) / area
    w1 = ((cx - bx) * (grid_y - by) - (by - cy) * (grid_x - bx)) / area
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
    if not inside.any():
        return
    sample_x = np.clip(
        (w0 * ax + w1 * bx + w2 * cx).round().astype(int), 0, width - 1)
    sample_y = np.clip(
        (w0 * ay + w1 * by + w2 * cy).round().astype(int), 0, height - 1)
    region = canvas[y0:y1 + 1, x0:x1 + 1]
    region[inside] = atlas[sample_y[inside], sample_x[inside]]
    canvas[y0:y1 + 1, x0:x1 + 1] = region


def main() -> None:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    y_min = float(sys.argv[sys.argv.index("--y-min") + 1]) if "--y-min" in sys.argv else 0.08
    y_max = float(sys.argv[sys.argv.index("--y-max") + 1]) if "--y-max" in sys.argv else 0.43
    flat = "--flat" in sys.argv

    document, binary = read_glb(source)

    atlas = None
    for image in document.get("images", []):
        if image.get("name", "").startswith("Color_"):
            view = document["bufferViews"][image["bufferView"]]
            start = view.get("byteOffset", 0)
            atlas = np.asarray(Image.open(
                io.BytesIO(binary[start:start + view["byteLength"]])).convert("RGB"))
            break
    if atlas is None:
        raise SystemExit("no base colour atlas in " + str(source))
    height, width = atlas.shape[:2]

    # The stage loads the atlas with the texture's own orientation, so a
    # texture coordinate of v reads the same row of the image the shader
    # reads.  The layout is therefore the atlas as it is, and a mark can
    # be read straight off the picture.
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    drawn = 0
    flat_atlas = np.full_like(atlas, 232)

    for node_index, node in enumerate(document["nodes"]):
        if "mesh" not in node:
            continue
        matrix = world_matrix(document, node_index)
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            attributes = primitive.get("attributes", {})
            if "TEXCOORD_0" not in attributes or "POSITION" not in attributes:
                continue
            positions = read_accessor(
                document, binary, attributes["POSITION"]).astype(float)
            uvs = read_accessor(
                document, binary, attributes["TEXCOORD_0"]).astype(float)
            if primitive.get("indices") is not None:
                indices = read_accessor(
                    document, binary, primitive["indices"]).reshape(-1).astype(int)
            else:
                indices = np.arange(len(positions))
            homogeneous = np.concatenate(
                [positions, np.ones((len(positions), 1))], axis=1)
            world = (matrix @ homogeneous.T).T[:, :3]

            triangles = indices.reshape(-1, 3)
            centre = world[triangles].mean(axis=1)
            keep = (centre[:, 1] >= y_min) & (centre[:, 1] <= y_max)
            triangles = triangles[keep]
            if not len(triangles):
                continue
            drawn += len(triangles)

            uv = uvs[triangles]
            cols = uv[:, :, 0] * (width - 1)
            rows = uv[:, :, 1] * (height - 1)
            for index in range(len(triangles)):
                if flat:
                    raster_triangle(canvas, flat_atlas, cols[index], rows[index])
                else:
                    raster_triangle(canvas, atlas, cols[index], rows[index])

    print("YXZ_UV_MAP triangles=%d size=%dx%d" % (drawn, width, height))
    Image.fromarray(canvas).save(out)
    ys, xs = np.nonzero(canvas.sum(axis=2) > 0)
    if len(xs):
        print("YXZ_UV_MAP bbox x %d..%d y %d..%d"
              % (xs.min(), xs.max(), ys.min(), ys.max()))


if __name__ == "__main__":
    main()
