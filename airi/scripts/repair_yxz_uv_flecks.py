"""Give the stray faces the colour of the surface they are on.

The scan is a mosaic of pieces that were fused into one shell, and the
pictures that were baked onto those pieces do not always line up with
where the pieces ended up.  A face that belongs to the white of the
shell can end up sitting on the navy of the visor, still carrying the
white's place in the atlas, and on screen the visor is freckled with
white.  The face is not a stray chip -- it is welded into the visor and
cannot be taken away without leaving a hole -- so the only way to make
it read is to give it the colour of the surface it is actually on.

The test for "this face does not belong here" needs no knowledge of the
design at all: a face whose colour is nothing like the colour of the
faces around it is out of place.  The neighbours are the faces nearest
to it in space, and their median colour is the colour of the surface it
is sitting on -- the median rather than the mean because one stray face
among nine good ones should not drag the answer.

The face is then given a place in the atlas to match.  Where the face
shares a corner with a face that is where it belongs, that corner's
place is copied, and the face takes the texture of its surroundings
exactly.  Where it shares nothing, the nearest face that is where it
belongs is used instead, and the whole face is given that one colour.

Usage:
  blender -b -P scripts/repair_yxz_uv_flecks.py -- \
    --source <glb> --output <glb> [--tolerance 0.22] [--neighbours 10]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils.kdtree import KDTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def load_atlas():
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


def face_colour(atlas, uv_layer, face):
    samples = []
    for loop in face.loops:
        uv = loop[uv_layer].uv
        x = int(min(max(uv.x, 0.0), 1.0) * (atlas.shape[1] - 1))
        y = int(min(max(uv.y, 0.0), 1.0) * (atlas.shape[0] - 1))
        samples.append(atlas[y, x][:3])
    if not samples:
        return np.zeros(3, dtype=np.float32)
    return np.mean(np.array(samples, dtype=np.float32), axis=0)


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    tolerance = float(value_after("--tolerance", "0.22"))
    neighbours = int(value_after("--neighbours", "10"))
    report_only = "--report-only" in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    atlas = load_atlas()
    if atlas is None:
        print("YXZ_UVFIX no atlas")
        bm.free()
        return

    faces = list(bm.faces)
    centres = [face.calc_center_median() for face in faces]
    colours = np.array(
        [face_colour(atlas, uv_layer, face) for face in faces],
        dtype=np.float32)

    tree = KDTree(len(centres))
    for index, centre in enumerate(centres):
        tree.insert(centre, index)
    tree.balance()

    stray = []
    for index in range(len(faces)):
        near = [item[1] for item in tree.find_n(centres[index], neighbours + 1)]
        around = [j for j in near if j != index]
        if not around:
            continue
        median = np.median(colours[around], axis=0)
        if float(np.max(np.abs(colours[index] - median))) > tolerance:
            stray.append(index)

    # The place in the atlas to copy, for every face that is where it
    # belongs.  A corner's place is taken from another face that shares
    # that corner, so the copy is exact where an exact copy is possible.
    good = sorted(set(range(len(faces))) - set(stray))
    corner_place = {}
    for index in good:
        for loop in faces[index].loops:
            key = loop.vert.index
            if key not in corner_place:
                corner_place[key] = (loop[uv_layer].uv.copy(), index)

    good_tree = KDTree(len(good))
    for index in good:
        good_tree.insert(centres[index], index)
    good_tree.balance()

    fixed_by_corner = 0
    fixed_by_face = 0
    for index in stray:
        face = faces[index]
        for loop in face.loops:
            place = corner_place.get(loop.vert.index)
            if place is not None:
                loop[uv_layer].uv = place[0]
                fixed_by_corner += 1
                continue
            _, near, _ = good_tree.find(face.calc_center_median())
            donor = faces[near]
            points = [[item[uv_layer].uv.x, item[uv_layer].uv.y]
                      for item in donor.loops]
            uv = np.mean(np.array(points, dtype=np.float64), axis=0)
            loop[uv_layer].uv = (float(uv[0]), float(uv[1]))
            fixed_by_face += 1

    report = {
        "faces": len(faces),
        "strayFaces": len(stray),
        "fixedByCorner": fixed_by_corner,
        "fixedByFace": fixed_by_face,
        "tolerance": tolerance,
    }

    if not report_only:
        bm.to_mesh(body.data)
        body.data.update()
        bpy.ops.object.select_all(action="DESELECT")
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLB",
            use_selection=True,
            export_materials="EXPORT",
            export_texcoords=True,
            export_normals=True,
            export_apply=False,
            export_animations=True,
            export_animation_mode="ACTIONS",
            export_skins=True,
            export_morph=True,
            export_yup=True,
            export_draco_mesh_compression_enable=False,
        )

    bm.free()
    print("YXZ_UVFIX " + json.dumps(report))


if __name__ == "__main__":
    main()
