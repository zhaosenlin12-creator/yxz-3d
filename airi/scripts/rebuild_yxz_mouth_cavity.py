"""
Give the mouth an interior that fills it, in every shape it opens to.

What the mouth looked like: a long dark ribbon with a pale streak down
the middle of it and a fork torn off one end, which read as a crack in
the face rather than as a mouth.  The reason is now measured rather
than guessed.

The plate that carries the mouth is the face's own surface, lifted a
tenth of a millimetre, with a hole cut in it; the hole is what the
visemes open and close.  The dish behind it was built by copying the
plate's surface and pushing it back a fraction of a millimetre -- which
is the mistake.  The plate's surface is the scanned muzzle, and the
muzzle is not smooth: it has four soft lobes about ten millimetres deep
and a lower lip that turns over a seven millimetre cliff.  A dish that
follows that surface follows the cliff, and its own triangles are torn
across it, which is the fork and the tear.

The fix is to stop copying the surface.  The dish is built from the hole's
own rim instead: the same 144 points that edge the hole, tucked a
fraction under the plate and carried back into a shallow bowl.  That
bowl is smooth by construction, because nothing in it comes from the
scan's relief, and it cannot tear, because there is no cliff in it to
tear across.

And because the rim moves when the mouth opens, the dish has to move
with it.  So the dish is given the same nine viseme shapes the plate
has, and each one is built from that shape's own rim.  The dish is then
always exactly the size of the hole in front of it: the hole can open
as wide as it likes and the interior is already there to fill it.

The colour is a gradient rather than a flat tone, because a flat tone
is what makes a hole read as a hole.  It goes from a warm lip colour at
the edge of the mouth to the dark of a throat in the middle, and the
light does the rest.

    python scripts/rebuild_yxz_mouth_cavity.py <in.vrm> <out.vrm>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset  # noqa: E402


# The plate's own grid: a ring of the hole's rim, then rings out to a
# fixed edge.  The rim is the first SEGMENTS vertices.
SEGMENTS = 144

# The dish's rings, from the rim inwards, as a fraction of the way to the
# middle.  The last one stops short of the middle and is closed by a fan,
# so that no ring collapses onto a point and leaves degenerate faces.
RINGS = (0.0, 0.18, 0.36, 0.54, 0.72, 0.88)

# How far past the rim the dish's edge tucks under the plate, as a
# fraction of the rim's own radius.  Without it there is a hairline gap
# between the hole and the dish, and what shows through that gap is the
# pale inside of the muzzle.
#
# This is a fraction and not a number of millimetres, and the difference
# is the whole bug.  The rim of a closed mouth is a very flat shape --
# sixty millimetres across and two deep -- so an outset of a fixed
# number of millimetres does not tuck the edge under the plate by that
# many millimetres: the outset is applied along the rim's own radius,
# and the radius of a flat shape is almost zero in the direction that
# matters, so the dish's short axis is inflated by the whole of it.  A
# twelve millimetre outset turned a two millimetre slit into a
# twenty-six millimetre lens, eighty-four millimetres wide, and that
# lens is what was lying across the face like a sheet of red plastic.
OUTSET = 0.012

# How far behind the plate's edge the dish's edge sits, in metres.  The
# plate is a sheet with no thickness, so its edge is where the face ends
# and the hole begins; the dish has to be behind that edge or it shows
# through as a dark line round the mouth.
#
# "Behind" is towards the model's own positive z, and the sign matters:
# the mouth's plate is modelled with the face looking down the negative z
# axis, so a dish that is built a few millimetres towards the negative z
# is not inside the mouth at all -- it is a red sheet lying on the front
# of the face, which is what the last build of this looked like.
#
# It also has to be small.  The inside of the muzzle is only five
# millimetres behind the plate, so a dish that is set back further than
# that has gone through the inside of the head and comes out on the far
# side of the mouth.
SETBACK = 0.0015

# How much deeper the middle of the dish is than its own edge.
DEPTH = 0.0018

# The colour of the inside of a mouth: a warm lip at the edge and the
# dark of a throat in the middle.
LIP = np.array([172.0, 56.0, 60.0])
THROAT = np.array([40.0, 11.0, 15.0])

# What the mouth looks like where the light does not reach it.
SHADE = (0.44, 0.14, 0.16)


def rim_normals(rim: np.ndarray) -> np.ndarray:
    """The outward normal of the rim, in the plane of the mouth.

    The rim is a ring of points around the hole, and the dish's edge has
    to sit outside that ring all the way round -- by the same amount,
    measured square to the ring.  A radial direction would not do it:
    the radius of a flat shape and its normal are different directions
    except at the ends, so a radial push slides along the ring instead
    of away from it, and by a different amount at every point.
    """
    xy = rim[:, :2]
    centre = xy.mean(axis=0)
    tangent = np.roll(xy, -1, axis=0) - np.roll(xy, 1, axis=0)
    lengths = np.linalg.norm(tangent, axis=1, keepdims=True)
    lengths[lengths < 1e-9] = 1.0
    tangent = tangent / lengths
    normal = np.column_stack([tangent[:, 1], -tangent[:, 0]])
    # Point it away from the middle of the mouth, whatever way round the
    # ring was wound.
    pointing = np.sum((xy - centre) * normal, axis=1, keepdims=True)
    normal = normal * np.where(pointing < 0, -1.0, 1.0)
    return normal


def dish_from_rim(rim: np.ndarray) -> np.ndarray:
    """The interior that fills the hole whose rim this is."""
    centre = rim.mean(axis=0)
    outward = rim_normals(rim)
    radius = float(np.max(np.linalg.norm(rim[:, :2] - centre[:2], axis=1)))
    tuck = OUTSET * radius

    rings = []
    for step in RINGS:
        scale = 1.0 - step
        xy = centre[:2] + (rim[:, :2] - centre[:2]) * scale
        xy = xy + outward * (tuck * (1.0 - step))
        z = rim[:, 2] + SETBACK + DEPTH * step * step
        rings.append(np.column_stack([xy, z]))

    middle = np.array([[centre[0], centre[1],
                        rim[:, 2].mean() + SETBACK + DEPTH * RINGS[-1] ** 2]])
    return np.concatenate(rings + [middle], axis=0)


def dish_indices() -> np.ndarray:
    """The faces of the dish: rings joined, and the middle closed off."""
    triangles = []
    for ring in range(len(RINGS) - 1):
        lower = ring * SEGMENTS
        upper = lower + SEGMENTS
        for segment in range(SEGMENTS):
            following = (segment + 1) % SEGMENTS
            a = lower + segment
            b = lower + following
            c = upper + following
            d = upper + segment
            triangles.extend([a, c, b, a, d, c])
    middle = len(RINGS) * SEGMENTS
    last = (len(RINGS) - 1) * SEGMENTS
    for segment in range(SEGMENTS):
        following = (segment + 1) % SEGMENTS
        triangles.extend([last + segment, middle, last + following])
    return np.array(triangles, dtype=np.int64)


def dish_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """The dish's normals, facing out of the mouth."""
    faces_of = triangles.reshape(-1, 3)
    corners = points[faces_of]
    faces = np.cross(corners[:, 1] - corners[:, 0],
                     corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(faces, axis=1, keepdims=True)
    faces = faces / np.maximum(lengths, 1e-20)
    # The dish is a bowl: the side that is seen is the concave one, and
    # its normal points forward, towards whoever is looking at the mouth.
    forward = faces[:, 2] > 0
    faces[~forward] *= -1.0
    summed = np.zeros_like(points)
    np.add.at(summed, faces_of[:, 0], faces)
    np.add.at(summed, faces_of[:, 1], faces)
    np.add.at(summed, faces_of[:, 2], faces)
    lengths = np.linalg.norm(summed, axis=1, keepdims=True)
    return summed / np.maximum(lengths, 1e-20)


def dish_uvs(points: np.ndarray) -> np.ndarray:
    """Where each point of the dish lands on its texture."""
    horizontal = points[:, 0]
    span = max(horizontal.max() - horizontal.min(), 1e-6)
    u = (horizontal - horizontal.min()) / span
    depth = np.concatenate(
        [np.full(SEGMENTS, step) for step in RINGS]
        + [np.array([RINGS[-1]])])
    return np.column_stack([u, depth])


def mouth_texture() -> bytes:
    """The inside of a mouth, as a picture.

    The horizontal axis is across the mouth and the vertical axis is how
    far back into it a point is, so the picture is a lip colour at the
    bottom and a throat at the top.  The corners are a shade deeper,
    because a mouth is deeper at its ends than a flat gradient says.
    """
    width, height = 64, 64
    u = np.linspace(0.0, 1.0, width)[None, :]
    v = np.linspace(0.0, 1.0, height)[:, None]
    colour = LIP[None, None, :] * (1.0 - v[:, :, None]) \
        + THROAT[None, None, :] * v[:, :, None]
    corner = 1.0 - 0.22 * np.abs(u - 0.5) * 2.0
    colour = colour * corner[:, :, None]
    image = Image.fromarray(
        np.clip(colour, 0, 255).astype(np.uint8), mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])

    asset = Asset(source)
    document = asset.document
    plate_index = next(
        i for i, mesh in enumerate(document["meshes"])
        if mesh.get("name") == "YXZ_Mouth")
    cavity_index = next(
        i for i, mesh in enumerate(document["meshes"])
        if mesh.get("name") == "YXZ_MouthCavity")

    plate = document["meshes"][plate_index]
    primitive = plate["primitives"][0]
    names = plate.get("extras", {}).get("targetNames", [])
    base = asset.accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    states = {"": base}
    for name, target_spec in zip(names, primitive.get("targets", [])):
        delta = asset.accessor(target_spec["POSITION"]).astype(np.float64)
        states[name] = base + delta

    print("YXZ_CAVITY plate states: %s" % ", ".join(sorted(states)))

    # The dish for each shape, and the shape the plate's own morph
    # targets ask for.
    triangles = dish_indices()
    dishes = {}
    for name, points in states.items():
        dish = dish_from_rim(points[:SEGMENTS])
        dishes[name] = dish
        print("YXZ_CAVITY %-10s %d points, rim z %.4f..%.4f" % (
            name or "Basis", len(dish),
            points[:SEGMENTS, 2].min(), points[:SEGMENTS, 2].max()))

    rest = dishes[""]
    normals = dish_normals(rest, triangles)
    uvs = dish_uvs(rest)

    # The dish is carried by the same bone as the plate, which is the
    # head: it is on the face, and it is on the face's bone.
    joints = np.zeros((len(rest), 4), dtype=np.uint16)
    joints[:, 0] = 18
    weights = np.zeros((len(rest), 4), dtype=np.float32)
    weights[:, 0] = 1.0

    # The texture.
    #
    # A previous build of this script left its own picture behind in the
    # file, and rebuilding on top of that stacks another copy of it every
    # time.  The cavity's texture is the last one in the file, so
    # dropping it here and appending the new one below leaves every other
    # material's texture index exactly where it was.
    textures = document.get("textures", [])
    images = document.get("images", [])
    if textures and textures[-1].get("name") == "YXZ_MouthCavityTex":
        source = textures.pop().get("source")
        if source is not None and source == len(images) - 1:
            images.pop(source)
    picture = mouth_texture()
    view = asset.append_view(picture)
    document.setdefault("images", []).append({
        "bufferView": view,
        "mimeType": "image/png",
        "name": "YXZ_MouthCavityTex",
    })
    document.setdefault("textures", []).append({
        "source": len(document["images"]) - 1,
        "name": "YXZ_MouthCavityTex",
    })

    cavity = document["meshes"][cavity_index]
    cavity_primitive = cavity["primitives"][0]
    material = document["materials"][cavity_primitive["material"]]
    material["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
    material["pbrMetallicRoughness"]["baseColorTexture"] = {
        "index": len(document["textures"]) - 1,
    }
    mtoon = material.setdefault("extensions", {}).setdefault(
        "VRMC_materials_mtoon", {})
    mtoon["colorFactor"] = [1.0, 1.0, 1.0, 1.0]
    mtoon["color"] = list(mtoon["colorFactor"])
    mtoon["shadeColorFactor"] = [SHADE[0], SHADE[1], SHADE[2], 1.0]
    mtoon["shadingToonyFactor"] = 0.55
    mtoon["rimLightingMixFactor"] = 0.0
    mtoon["parametricRimColorFactor"] = [0.0, 0.0, 0.0]
    mtoon["reflectanceFactor"] = 0.0

    cavity_primitive["attributes"] = {
        "POSITION": asset.add_accessor(rest, "VEC3", 34962),
        "NORMAL": asset.add_accessor(normals, "VEC3", 34962),
        "TEXCOORD_0": asset.add_accessor(uvs, "VEC2", 34962),
        "JOINTS_0": asset.add_accessor(joints, "VEC4", 34962),
        "WEIGHTS_0": asset.add_accessor(weights, "VEC4", 34962),
    }
    cavity_primitive["indices"] = asset.add_accessor(triangles, "SCALAR", 34963)

    # The same nine shapes the plate has, in the same order, so that the
    # dish is always the size of the hole in front of it.
    targets = []
    for name in names:
        delta = dishes[name] - rest
        targets.append({
            "POSITION": asset.add_accessor(delta, "VEC3", 34962),
            "NORMAL": asset.add_accessor(np.zeros_like(delta), "VEC3", 34962),
        })
    cavity_primitive["targets"] = targets
    cavity["weights"] = [0.0] * len(names)
    cavity.setdefault("extras", {})["targetNames"] = list(names)

    # The viseme expressions now drive the dish as well as the plate.
    expressions = document["extensions"]["VRMC_vrm"]["expressions"]["preset"]
    cavity_node = next(
        i for i, node in enumerate(document["nodes"])
        if node.get("name") == "YXZ_MouthCavity")
    for index, name in enumerate(names):
        expression = expressions.get(name)
        if expression is None:
            continue
        binds = expression.setdefault("morphTargetBinds", [])
        if not any(bind.get("node") == cavity_node for bind in binds):
            binds.append({"node": cavity_node, "index": index, "weight": 1.0})

    asset.save(target)
    print("YXZ_CAVITY wrote %s" % target)


if __name__ == "__main__":
    main()
