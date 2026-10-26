"""Inpaint the atlas triangles owned by UV-selected mesh components.

This writes a review-only candidate and leaves the source VRM untouched.
The selected component geometry stays in place; only its base-colour texels
are continued from the surrounding atlas.

Usage:
  python scripts/repair_yxz_uv_components.py source.vrm candidate.vrm \
    --uv 0.2670376,0.9741349
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb, write_glb  # noqa: E402
from remove_yxz_uv_components import connected_faces, read_accessor


COMPONENT_TYPES = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def replace_image(document, binary, image_name, encoded):
    image = next(
        item for item in document["images"]
        if item.get("name") == image_name
    )
    blobs = []
    for view in document["bufferViews"]:
        start = view.get("byteOffset", 0)
        blobs.append(binary[start:start + view["byteLength"]])
    blobs[image["bufferView"]] = encoded

    chunks = []
    offset = 0
    for view, blob in zip(document["bufferViews"], blobs):
        padding = (-offset) % 4
        if padding:
            chunks.append(b"\x00" * padding)
            offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        chunks.append(blob)
        offset += len(blob)
    document["buffers"][0]["byteLength"] = offset
    image["mimeType"] = "image/png"
    return b"".join(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--uv", action="append", required=True)
    parser.add_argument("--max-faces", type=int, default=1000)
    parser.add_argument("--dilate", type=int, default=2)
    parser.add_argument("--radius", type=float, default=5)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()

    document, binary = read_glb(args.source)
    mesh_index, primitive_index, primitive = max(
        (
            (
                mesh_index,
                primitive_index,
                primitive,
            )
            for mesh_index, mesh in enumerate(document.get("meshes", []))
            for primitive_index, primitive in enumerate(mesh.get("primitives", []))
            if "POSITION" in primitive.get("attributes", {})
        ),
        key=lambda row: document["accessors"][
            row[2]["attributes"]["POSITION"]
        ]["count"],
    )

    positions = read_accessor(
        document, binary, primitive["attributes"]["POSITION"])
    uvs = read_accessor(
        document, binary, primitive["attributes"]["TEXCOORD_0"])
    indices = read_accessor(
        document, binary, primitive["indices"]).reshape(-1)
    faces = indices.reshape(-1, 3).astype(np.int64)
    face_uvs = uvs[faces].mean(axis=1)

    selected = np.zeros(len(faces), dtype=bool)
    for raw_seed in args.uv:
        seed = np.array([float(value) for value in raw_seed.split(",")])
        face_index = int(np.argmin(np.linalg.norm(face_uvs - seed, axis=1)))
        component = connected_faces(faces, face_index)
        if len(component) > args.max_faces:
            raise SystemExit(
                f"refusing component with {len(component)} faces at {raw_seed}"
            )
        if selected[component].any():
            raise SystemExit(f"overlapping UV component at {raw_seed}")
        selected[component] = True
        vertices = np.unique(faces[component])
        print(
            f"YXZ_UV_PAINT seed={raw_seed} face={face_index} "
            f"faces={len(component)} uv={uvs[vertices].min(axis=0).tolist()}.."
            f"{uvs[vertices].max(axis=0).tolist()}"
        )

    color_image = next(
        item for item in document.get("images", [])
        if item.get("name", "").startswith("Color_")
    )
    view = document["bufferViews"][color_image["bufferView"]]
    start = view.get("byteOffset", 0)
    image_bytes = binary[start:start + view["byteLength"]]
    original_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    original = np.asarray(original_image).copy()
    height, width = original.shape[:2]

    mask_image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask_image)
    uv_faces = uvs[faces[selected]]
    for triangle in uv_faces:
        points = [
            (
                int(round(float(uv[0]) * (width - 1))),
                int(round((1.0 - float(uv[1])) * (height - 1))),
            )
            for uv in triangle
        ]
        draw.polygon(points, fill=255)

    mask = np.asarray(mask_image)
    if args.dilate > 0:
        size = args.dilate * 2 + 1
        mask = cv2.dilate(mask, np.ones((size, size), dtype=np.uint8))
    repaired = cv2.inpaint(original, mask, args.radius, cv2.INPAINT_TELEA)
    covered = int(np.count_nonzero(mask))
    print(f"YXZ_UV_PAINT texels={covered}")

    if args.preview:
        ys, xs = np.nonzero(mask)
        x0, x1 = max(0, int(xs.min()) - 24), min(width, int(xs.max()) + 25)
        y0, y1 = max(0, int(ys.min()) - 24), min(height, int(ys.max()) + 25)
        before = original[y0:y1, x0:x1]
        after = repaired[y0:y1, x0:x1]
        strip = np.concatenate([before, after], axis=1)
        Image.fromarray(strip).resize(
            (strip.shape[1] * 5, strip.shape[0] * 5),
            Image.Resampling.NEAREST,
        ).save(args.preview)
        print(f"YXZ_UV_PAINT_PREVIEW {args.preview}")

    encoded = io.BytesIO()
    Image.fromarray(repaired).save(encoded, format="PNG", optimize=False)
    packed = replace_image(
        document, binary, color_image["name"], encoded.getvalue())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(args.output, document, packed)
    print(f"YXZ_UV_PAINT_CANDIDATE {args.output}")


if __name__ == "__main__":
    main()
