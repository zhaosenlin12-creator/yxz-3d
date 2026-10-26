"""
 * Take the scrap of shell off the visor.
 *
 * The scan left a piece of the head hanging in front of the visor: a
 * small sheet of the helmet's own white, standing clear of the face by
 * a couple of centimetres, seen almost edge on.  Edge on, it is a
 * bright bar of light lying across the middle of the visor, and it is
 * the one thing on the character that reads as a mistake rather than
 * as a surface.
 *
 * The sheet is found by where it is rather than by what it looks
 * like: it is a shell of its own, a hand's width across, standing
 * clear of the side of the head at the height of the eyes.  The faces
 * of that shell are removed, and the texels it was wearing are
 * painted over with the visor's own blue, so that nothing it shared
 * with the helmet is left showing a pale streak where the helmet is
 * white.
 *
 * Usage:
 *   blender -b -P scripts/remove_yxz_visor_scrap.py -- \
 *     --source <glb> --output <glb> [--centre 0.2313,0.0133,0.2341] \
 *     [--radius 0.020]
 """

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


# The visor's own blue, which is what the helmet's white is painted
# over with where the scrap was wearing it.
VISOR_BLUE = (36, 71, 113)


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """The connected components of a bmesh, as lists of faces."""
    bm.faces.ensure_lookup_table()
    unseen = set(bm.faces)
    groups = []
    while unseen:
        seed = unseen.pop()
        group = [seed]
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour in unseen:
                        unseen.discard(neighbour)
                        group.append(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    return groups


def triangle(mask, width, height, a, b, c):
    min_x = max(0, int(min(a[0], b[0], c[0])))
    max_x = min(width - 1, int(max(a[0], b[0], c[0])))
    min_y = max(0, int(min(a[1], b[1], c[1])))
    max_y = min(height - 1, int(max(a[1], b[1], c[1])))
    if min_x > max_x or min_y > max_y:
        return
    ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
    px = xs + 0.5
    py = ys + 0.5
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-9:
        return
    w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
    w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -0.002) & (w1 >= -0.002) & (w2 >= -0.002)
    mask[min_y:max_y + 1, min_x:max_x + 1] |= inside


def main() -> None:
    source = value_after("--source")
    output = value_after("--output")
    centre = np.array([float(part) for part in
                       value_after("--centre", "0.2313,0.0133,0.2341").split(",")])
    radius = float(value_after("--radius", "0.020"))
    paint_only = "--paint-only" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    colour = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            colour = image
            break
    width, height = colour.size
    pixels = np.empty(height * width * 4, dtype=np.float32)
    colour.pixels.foreach_get(pixels)
    flat = pixels.reshape(-1, 4)

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    # The scrap is a flap of the head standing clear of it, so it is
    # found by where it is: a patch of the head, a hand's width across,
    # hanging a couple of centimetres proud of the side of the helmet
    # at the height of the eyes.
    doomed = set()
    for face in bm.faces:
        position = np.array(face.calc_center_median())
        if float(np.linalg.norm(position - centre)) <= radius:
            doomed.add(face)

    if not doomed:
        print("YXZ_SCRAP none found")
        bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")
        return

    texels = np.zeros((height, width), dtype=bool)
    points = np.array([
        tuple(vert.co)
        for face in doomed
        for vert in face.verts
    ])
    for face in doomed:
        corners = [
            (loop[uv_layer].uv.x * width, (1.0 - loop[uv_layer].uv.y) * height)
            for loop in face.loops
        ]
        for index in range(1, len(corners) - 1):
            triangle(texels, width, height, corners[0], corners[index], corners[index + 1])

    # The texels the scrap was wearing, painted with the visor's blue.
    ys, xs = np.nonzero(texels)
    rows = height - 1 - ys
    index = rows * width + xs
    flat[index, 0] = VISOR_BLUE[0] / 255.0
    flat[index, 1] = VISOR_BLUE[1] / 255.0
    flat[index, 2] = VISOR_BLUE[2] / 255.0
    colour.pixels.foreach_set(flat.ravel())
    try:
        colour.pack()
    except RuntimeError:
        pass

    if paint_only:
        # The flap is not taken off.  It is lying over a tear in the
        # visor panel, and it is the reason the tear is not a hole in
        # the character, so it stays and is painted with the visor's
        # own blue instead.
        bm.free()
    else:
        bmesh.ops.delete(bm, geom=list(doomed), context="FACES")
        bm.to_mesh(body.data)
        bm.free()
        body.data.update()

    print("YXZ_SCRAP " + json.dumps({
        "faces": len(doomed),
        "texels": int(texels.sum()),
        "paintOnly": paint_only,
        "min": [round(float(value), 4) for value in points.min(axis=0)],
        "max": [round(float(value), 4) for value in points.max(axis=0)],
    }))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


if __name__ == "__main__":
    main()
