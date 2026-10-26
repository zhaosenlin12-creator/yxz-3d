"""Paint the inside of the mouth into the atlas, and give the plate its
own paint.

The plate that carries the mouth is a ring: its inner edge is the mouth
opening and it reaches out to a fixed edge on the muzzle.  When the
mouth opens, what shows through the hole is the face underneath -- and
the face underneath is painted with the muzzle's own colour, which is
the colour of a closed mouth, not the colour of the inside of one.

So the inside of the mouth is painted into the atlas, where the face
itself carries it.  The region painted is the union of every shape the
mouth can take: every opening the plate can have, plus a little more,
so that a wide mouth never shows the muzzle's colour at its edge.  The
painted region is found in three dimensions and then projected onto the
face's own texture coordinates, which is where the face is actually
painted, so what the viewer sees through the hole is what was painted.

The plate itself cannot use that atlas any more: the paint under it
has just been turned into the inside of a mouth, and the plate would
wear it like a moustache.  So the plate is given its own texture, a
copy of the muzzle's paint taken before the mouth was painted into it.
The copy is put on a canvas that is entirely made of that same paint,
so that the plate's edge does not pick up anything from its
neighbours when the texture is minified.

    python scripts/patch_yxz_mouth_texture.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face  # noqa: E402
from rebuild_yxz_mouth import (  # noqa: E402
    SHAPES, SEGMENTS, heightmap, sample_surface)


# The colour of the inside of a mouth: near black at the back, a warm
# dark red where the light still reaches it.
MOUTH_DEEP = np.array([30, 8, 12], dtype=np.float64)
MOUTH_INK = np.array([62, 18, 24], dtype=np.float64)

# How far past the opening the paint reaches, so that a mouth which
# opens wider than the painted region still shows the inside.
MARGIN = 0.0020

# The size of the plate's own texture.
PLATE_TEXTURE = 512


def body_texture(asset: Asset):
    """The body's atlas, as an image."""
    document = asset.document
    material = next(
        material for material in document["materials"]
        if str(material.get("name", "")).startswith("tripo_material"))
    texture = document["textures"][
        material["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    image = document["images"][texture["source"]]
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    blob = bytes(asset.binary[start:start + view["byteLength"]])
    picture = Image.open(io.BytesIO(blob)).convert("RGB")
    return picture, np.asarray(picture).copy()


def inside_any(offsets: np.ndarray) -> np.ndarray:
    """Which points around the mouth are inside the mouth."""
    dx = offsets[:, 0]
    dy = offsets[:, 1]
    covered = np.zeros(len(offsets), dtype=bool)
    for width, height, shift in SHAPES.values():
        covered |= ((dx / (width + MARGIN)) ** 2
                    + ((dy - shift) / (height + MARGIN)) ** 2) <= 1.0
    return covered


def depth_in_mouth(offsets: np.ndarray) -> np.ndarray:
    """How deep inside the mouth each point lies, for the shading."""
    dx = offsets[:, 0]
    dy = offsets[:, 1]
    depth = np.full(len(offsets), np.inf)
    for width, height, shift in SHAPES.values():
        depth = np.minimum(
            depth, (dx / width) ** 2 + ((dy - shift) / height) ** 2)
    return depth


def spread(field: np.ndarray, rounds: int) -> np.ndarray:
    """Fill the gaps in a field from the values around them."""
    for _ in range(rounds):
        unknown = np.isnan(field)
        if not unknown.any():
            break
        filled = field.copy()
        filled[1:, :] = np.fmin(filled[1:, :], field[:-1, :])
        filled[:-1, :] = np.fmin(filled[:-1, :], field[1:, :])
        filled[:, 1:] = np.fmin(filled[:, 1:], field[:, :-1])
        filled[:, :-1] = np.fmin(filled[:, :-1], field[:, 1:])
        field = np.where(unknown, filled, field)
    return field


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])

    asset = Asset(source)
    document = asset.document
    meshes = document["meshes"]

    body_index = next(
        i for i, mesh in enumerate(meshes)
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = next(
        i for i, mesh in enumerate(meshes) if mesh.get("name") == "YXZ_Mouth")
    plate_material = next(
        i for i, material in enumerate(document["materials"])
        if material.get("name") == "YXZ_MouthPlate")

    picture, pixels = body_texture(asset)
    height, width = pixels.shape[:2]

    mouth = meshes[mouth_index]
    primitive = mouth["primitives"][0]
    attributes = primitive["attributes"]
    base = asset.accessor(attributes["POSITION"]).astype(np.float64)
    uvs = asset.accessor(attributes["TEXCOORD_0"]).astype(np.float64)
    centre = base[:SEGMENTS].mean(axis=0)

    # --- the plate's own paint ------------------------------------------
    #
    # Taken before the mouth is painted, so the plate keeps the muzzle's
    # colour and the edge where it starts is still invisible.
    # The atlas is read the way glTF reads it: the first row of the
    # picture is the row the texture coordinate v = 0 points at.  Flip
    # that and the paint lands on the far side of the face.
    plate_x = uvs[:, 0] * width
    plate_y = uvs[:, 1] * height
    pad = 8
    x0 = max(0, int(np.floor(plate_x.min())) - pad)
    x1 = min(width, int(np.ceil(plate_x.max())) + pad)
    y0 = max(0, int(np.floor(plate_y.min())) - pad)
    y1 = min(height, int(np.ceil(plate_y.max())) + pad)
    canvas = picture.crop((x0, y0, x1, y1)).resize(
        (PLATE_TEXTURE, PLATE_TEXTURE), Image.BILINEAR)
    offset_x = (PLATE_TEXTURE - (x1 - x0)) // 2
    offset_y = (PLATE_TEXTURE - (y1 - y0)) // 2
    canvas.paste(picture.crop((x0, y0, x1, y1)), (offset_x, offset_y))
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)

    view = asset.append_view(out.getvalue())
    image_index = len(document["images"])
    document["images"].append({
        "bufferView": view, "mimeType": "image/png",
        "name": "YXZ_MouthPlateTex"})
    texture_index = len(document["textures"])
    document["textures"].append({"sampler": 0, "source": image_index})
    document["materials"][plate_material][
        "pbrMetallicRoughness"]["baseColorTexture"] = {"index": texture_index}

    new_uvs = np.empty_like(uvs)
    new_uvs[:, 0] = (plate_x - x0 + offset_x) / PLATE_TEXTURE
    new_uvs[:, 1] = (plate_y - y0 + offset_y) / PLATE_TEXTURE
    spec = document["accessors"][attributes["TEXCOORD_0"]]
    added = asset.add_accessor(new_uvs, "VEC2", 34962)
    spec["bufferView"] = document["accessors"][added]["bufferView"]
    spec.pop("byteOffset", None)
    spec["componentType"] = 5126
    spec["type"] = "VEC2"
    spec["count"] = len(new_uvs)
    print("YXZ_MOUTH_TEX plate paint %dx%d at %d,%d of a %d texture"
          % (x1 - x0, y1 - y0, offset_x, offset_y, PLATE_TEXTURE))

    # --- the inside of the mouth ----------------------------------------
    face = Face(asset, body_index)
    reach = float(np.abs(base - centre).max()) + 0.06
    candidates = face.near(centre, reach)
    print("YXZ_MOUTH_TEX candidates %d" % len(candidates))

    step = 0.0008
    xs = np.arange(centre[0] - 0.046, centre[0] + 0.046, step)
    ys = np.arange(centre[1] - 0.032, centre[1] + 0.032, step)
    grid_x, grid_y = np.meshgrid(xs, ys)
    points = np.column_stack([
        grid_x.reshape(-1), grid_y.reshape(-1),
        np.full(grid_x.size, centre[2])])
    offsets = points[:, :2] - centre[:2]
    covered = inside_any(offsets)
    depth = depth_in_mouth(offsets)
    points = points[covered]
    depth = depth[covered]
    print("YXZ_MOUTH_TEX points inside the mouth %d" % len(points))

    # The mouth is painted where the face itself is painted, so the
    # points are put on the face with the same down-ray the plate uses.
    xs, ys, depth_map, hit = heightmap(
        face, centre, 0.058, 0.044, 0.0002, candidates)
    _, _, uvs_on_face = sample_surface(
        face, xs, ys, hit, points[:, 0], points[:, 1])
    face_x = uvs_on_face[:, 0] * width
    face_y = uvs_on_face[:, 1] * height
    face_ix = np.clip(np.round(face_x).astype(int), 0, width - 1)
    face_iy = np.clip(np.round(face_y).astype(int), 0, height - 1)

    # The depth of the mouth is spread over the atlas as a field, so
    # that the paint can be shaded rather than flooded.
    field = np.full((height, width), np.nan)
    for row in range(len(depth)):
        y = face_iy[row]
        x = face_ix[row]
        if np.isnan(field[y, x]) or depth[row] < field[y, x]:
            field[y, x] = depth[row]
    field = spread(field, 6)

    painted = np.isfinite(field)
    ys_painted, xs_painted = np.nonzero(painted)
    print("YXZ_MOUTH_TEX painted %d pixels, x %d..%d y %d..%d"
          % (len(xs_painted), xs_painted.min(), xs_painted.max(),
             ys_painted.min(), ys_painted.max()))

    values = field[painted]
    shade = np.clip((values - 0.15) / 0.85, 0.0, 1.0)[:, None]
    colour = MOUTH_DEEP[None, :] * (1.0 - shade) + MOUTH_INK[None, :] * shade
    pixels[painted] = np.clip(colour, 0, 255).astype(np.uint8)
    picture = Image.fromarray(pixels)

    audit = Path("docs/yxz-audit")
    audit.mkdir(parents=True, exist_ok=True)
    picture.crop((x0 - 40, y0 - 40, x1 + 40, y1 + 40)).resize(
        (2 * (x1 - x0 + 80), 2 * (y1 - y0 + 80)), Image.NEAREST).save(
            audit / "mouth-region-painted.png")

    out = io.BytesIO()
    picture.save(out, format="PNG", optimize=True)
    encoded = out.getvalue()

    material = next(
        material for material in document["materials"]
        if str(material.get("name", "")).startswith("tripo_material"))
    texture = document["textures"][
        material["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    body_image = document["images"][texture["source"]]
    body_view = document["bufferViews"][body_image["bufferView"]]
    start = body_view.get("byteOffset", 0)
    room = body_view["byteLength"]
    if len(encoded) <= room:
        # The new atlas fits in the space the old one had, so it can be
        # written over it without disturbing anything else.
        body_view["byteLength"] = len(encoded)
        asset.binary[start:start + len(encoded)] = encoded
    else:
        # It does not fit, so it is given a place of its own at the end
        # of the file rather than written over what is there.
        body_image["bufferView"] = asset.append_view(encoded)
        print("YXZ_MOUTH_TEX atlas moved to the end of the file")
    print("YXZ_MOUTH_TEX atlas %d bytes (was %d)" % (len(encoded), room))
    body_image["mimeType"] = "image/png"

    asset.save(target)
    print("YXZ_MOUTH_TEX wrote %s" % target)


if __name__ == "__main__":
    main()
