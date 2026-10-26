"""Lay the head's own triangles out in texture space.

A mark on the character has to be repaired on the texels that show it,
and the only reliable way to find those texels is to look at the head in
the space of the atlas: every triangle is drawn where its own texture
coordinates say it belongs, and it is painted with the colour the atlas
has there.  What comes out is a picture of the head that has been cut
open and flattened, which makes the visor's marks obvious and puts a
texel coordinate on every one of them.

Usage:
  python scripts/render_yxz_uv_head.py <vrm> <out-dir> [--y-min 2.2] [--y-max 3.3]
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from glb_json import read_glb

COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_FORMAT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_accessor(document, binary, index):
    accessor = document["accessors"][index]
    components = TYPE_COMPONENTS[accessor["type"]]
    size = COMPONENT_SIZE[accessor["componentType"]]
    fmt = COMPONENT_FORMAT[accessor["componentType"]]
    view = document["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or components * size
    count = accessor["count"]
    dtype = np.dtype("<f4") if fmt == "f" else np.dtype("<" + fmt * components)
    if stride == components * size:
        flat = np.frombuffer(binary, dtype=dtype, count=count * components, offset=base)
        return flat.reshape(count, components)
    out = np.empty((count, components), dtype=dtype)
    for i in range(count):
        out[i] = struct.unpack_from("<" + fmt * components, binary, base + i * stride)
    return out


def node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4)
    matrix = np.eye(4)
    if "scale" in node:
        matrix = np.diag(list(node["scale"]) + [1.0]) @ matrix
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        rot = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1],
        ])
        matrix = rot @ matrix
    if "translation" in node:
        translate = np.eye(4)
        translate[:3, 3] = node["translation"]
        matrix = translate @ matrix
    return matrix


def world_matrix(document, index):
    chain = []
    cursor = index
    while cursor is not None:
        chain.append(cursor)
        cursor = document["nodes"][cursor].get("parent")
    matrix = np.eye(4)
    for node_index in reversed(chain):
        matrix = node_matrix(document["nodes"][node_index]) @ matrix
    return matrix


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
    w1 = ((cx - bx) * (grid_y - by) - (cy - by) * (grid_x - bx)) / area
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


def main():
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    y_min = 2.2
    y_max = 3.35
    if "--y-min" in sys.argv:
        y_min = float(sys.argv[sys.argv.index("--y-min") + 1])
    if "--y-max" in sys.argv:
        y_max = float(sys.argv[sys.argv.index("--y-max") + 1])

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

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    drawn = 0

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
            rows = (1.0 - uv[:, :, 1]) * (height - 1)
            for index in range(len(triangles)):
                raster_triangle(canvas, atlas, cols[index], rows[index])

    print("YXZ_UV_HEAD triangles=%d size=%dx%d" % (drawn, width, height))
    Image.fromarray(canvas).save(out / "uv-head.png")

    ys, xs = np.nonzero(canvas.sum(axis=2) > 0)
    if len(xs):
        print("YXZ_UV_HEAD bbox x %d..%d y %d..%d"
              % (xs.min(), xs.max(), ys.min(), ys.max()))
        Image.fromarray(canvas).crop(
            (max(0, xs.min() - 20), max(0, ys.min() - 20),
             min(width, xs.max() + 21), min(height, ys.max() + 21))
        ).save(out / "uv-head-crop.png")


if __name__ == "__main__":
    main()
