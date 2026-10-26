"""Find the painted smile, and find out where it sits on the mouth plate.

The plate lies on the face and carries the face's own atlas, so the red
smile is drawn on whichever surface happens to be in front of it.  If
the plate's hole runs through the middle of that smile, then every
viseme tears the smile in half: the half on the plate travels with the
plate and the half on the face stays behind, and the two halves are
never together again.

This finds the red texels in the atlas, and finds the plate vertices
that sample them, so the plate can be built with its hole clear of the
paint instead of across it.

Usage:
    python scripts/probe_yxz_mouth_paint.py <model.vrm>
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


def image_of(asset: Asset, index: int) -> np.ndarray:
    """The atlas as an RGB array, row 0 at the top."""
    image = asset.document["images"][index]
    view = asset.document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    blob = bytes(asset.binary[start:start + view["byteLength"]])
    picture = Image.open(io.BytesIO(blob)).convert("RGB")
    return np.asarray(picture).astype(np.int16)


def main() -> None:
    path = Path(sys.argv[1])
    asset = Asset(path)
    document = asset.document
    meshes = document["meshes"]

    body_index = next(
        i for i, mesh in enumerate(meshes)
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(
        i for i, mesh in enumerate(meshes) if mesh.get("name") == "YXZ_Mouth")

    body_material = document["materials"][body_index and 0 or 0]
    body_material = next(
        material for material in document["materials"]
        if str(material.get("name", "")).startswith("tripo_material"))
    texture_index = body_material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    picture = image_of(asset, texture_index)
    height, width = picture.shape[:2]

    red = picture[:, :, 0]
    green = picture[:, :, 1]
    blue = picture[:, :, 2]
    mask = (red > 90) & (red > green + 35) & (red > blue + 35)
    ys, xs = np.nonzero(mask)
    report = {
        "atlas": [width, height],
        "redTexels": int(mask.sum()),
    }
    if len(xs):
        # glTF puts v=0 at the bottom of the image.
        report["redUvBox"] = {
            "uMin": round(float(xs.min() / width), 4),
            "uMax": round(float(xs.max() / width), 4),
            "vMin": round(float(1.0 - ys.max() / height), 4),
            "vMax": round(float(1.0 - ys.min() / height), 4),
        }
        report["redUvCentre"] = [
            round(float((xs.min() + xs.max()) / 2 / width), 4),
            round(float(1.0 - (ys.min() + ys.max()) / 2 / height), 4),
        ]

    mouth = meshes[mouth_index]
    primitive = mouth["primitives"][0]
    attributes = primitive["attributes"]
    positions = asset.accessor(attributes["POSITION"]).astype(np.float64)
    uvs = asset.accessor(attributes["TEXCOORD_0"]).astype(np.float64)

    px = np.clip((uvs[:, 0] * width).astype(int), 0, width - 1)
    py = np.clip(((1.0 - uvs[:, 1]) * height).astype(int), 0, height - 1)
    sampled = picture[py, px]
    on_red = (
        (sampled[:, 0] > 90)
        & (sampled[:, 0] > sampled[:, 1] + 35)
        & (sampled[:, 0] > sampled[:, 2] + 35))
    report["plateVertices"] = int(positions.shape[0])
    report["plateVerticesOnRed"] = int(on_red.sum())
    if on_red.any():
        report["plateRedBox"] = {
            "xMin": round(float(positions[on_red, 0].min()), 4),
            "xMax": round(float(positions[on_red, 0].max()), 4),
            "yMin": round(float(positions[on_red, 1].min()), 4),
            "yMax": round(float(positions[on_red, 1].max()), 4),
            "zMin": round(float(positions[on_red, 2].min()), 4),
            "zMax": round(float(positions[on_red, 2].max()), 4),
        }
        report["plateRedCentre"] = [
            round(float(positions[on_red, 0].mean()), 4),
            round(float(positions[on_red, 1].mean()), 4),
            round(float(positions[on_red, 2].mean()), 4),
        ]

    report["plateBox"] = {
        "xMin": round(float(positions[:, 0].min()), 4),
        "xMax": round(float(positions[:, 0].max()), 4),
        "yMin": round(float(positions[:, 1].min()), 4),
        "yMax": round(float(positions[:, 1].max()), 4),
        "zMin": round(float(positions[:, 2].min()), 4),
        "zMax": round(float(positions[:, 2].max()), 4),
    }
    report["plateUvBox"] = {
        "uMin": round(float(uvs[:, 0].min()), 4),
        "uMax": round(float(uvs[:, 0].max()), 4),
        "vMin": round(float(uvs[:, 1].min()), 4),
        "vMax": round(float(uvs[:, 1].max()), 4),
    }

    # The face itself: where does the paint of the smile actually sit?
    body_primitive = meshes[body_index]["primitives"][0]
    body_attributes = body_primitive["attributes"]
    body_positions = asset.accessor(body_attributes["POSITION"]).astype(np.float64)
    body_uvs = asset.accessor(body_attributes["TEXCOORD_0"]).astype(np.float64)
    bpx = np.clip((body_uvs[:, 0] * width).astype(int), 0, width - 1)
    bpy = np.clip(((1.0 - body_uvs[:, 1]) * height).astype(int), 0, height - 1)
    bsampled = picture[bpy, bpx]
    body_red = (
        (bsampled[:, 0] > 90)
        & (bsampled[:, 0] > bsampled[:, 1] + 35)
        & (bsampled[:, 0] > bsampled[:, 2] + 35))
    # Keep the smile, not the trim on the visor: the mouth is the red
    # that is close to the mouth in the atlas.
    window = (
        (body_uvs[:, 0] > 0.38) & (body_uvs[:, 0] < 0.58)
        & (body_uvs[:, 1] > 0.66) & (body_uvs[:, 1] < 0.82))
    near = window
    smile = body_red & near
    report["faceRedTexels"] = int(body_red.sum())
    report["faceSmileTexels"] = int(smile.sum())
    if smile.any():
        report["faceSmileBox"] = {
            "xMin": round(float(body_positions[smile, 0].min()), 4),
            "xMax": round(float(body_positions[smile, 0].max()), 4),
            "yMin": round(float(body_positions[smile, 1].min()), 4),
            "yMax": round(float(body_positions[smile, 1].max()), 4),
            "zMin": round(float(body_positions[smile, 2].min()), 4),
            "zMax": round(float(body_positions[smile, 2].max()), 4),
        }
        report["faceSmileCentre"] = [
            round(float(body_positions[smile, 0].mean()), 4),
            round(float(body_positions[smile, 1].mean()), 4),
            round(float(body_positions[smile, 2].mean()), 4),
        ]

    # A picture of the atlas around the mouth, so the smile can be seen
    # against the plate's own patch of it.
    u0, u1 = 0.40, 0.56
    v0, v1 = 0.66, 0.82
    columns = 72
    rows = 30
    art = []
    for row in range(rows):
        line = []
        for column in range(columns):
            u = u0 + (u1 - u0) * column / (columns - 1)
            v = v1 - (v1 - v0) * row / (rows - 1)
            px = min(width - 1, max(0, int(u * width)))
            py = min(height - 1, max(0, int((1.0 - v) * height)))
            r, g, b = picture[py, px]
            if r > 90 and r > g + 35 and r > b + 35:
                line.append("#")
            elif r > 150 and g > 150 and b > 150:
                line.append(".")
            else:
                line.append(" ")
        art.append("".join(line))
    report["atlasWindow"] = {"u": [u0, u1], "v": [v0, v1]}
    report["plateUvBoxInWindow"] = {
        "uMin": round((0.4594 - u0) / (u1 - u0) * (columns - 1)),
        "uMax": round((0.502 - u0) / (u1 - u0) * (columns - 1)),
        "vMin": round((v1 - 0.7563) / (v1 - v0) * (rows - 1)),
        "vMax": round((v1 - 0.7175) / (v1 - v0) * (rows - 1)),
    }
    report["atlasArt"] = art

    print("YXZ_MOUTH_PAINT " + json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
