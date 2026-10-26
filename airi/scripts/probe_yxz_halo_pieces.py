"""Photograph the pieces the halo was torn into, one at a time.

The scan did not record a halo.  It recorded two arcs that fall on
opposite sides of the head, which the renderer then draws as a hoop
with the top bitten out of it.  Fitting a circle to that as if it
were one ring cannot work -- the two arcs were never joined, so there
is no single curve through both -- so the pieces are separated and
looked at on their own first.

Each piece is rendered alone from the front, from above and from the
side, framed to its own bounding box so its curvature can be read.

Usage:
  blender -b -P scripts/probe_yxz_halo_pieces.py -- \
    --glb <glb> --out <dir> [--threshold 0.0015]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild_yxz_halo import (  # noqa: E402
    connected_faces,
    describe_shells,
)


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def flat_material(objects, colour):
    for target in objects:
        target.data.materials.clear()
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = colour
        shader.inputs["Roughness"].default_value = 0.7
        target.data.materials.append(material)


def render(out_path, location, rotation, scale, size=700):
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new("probe")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("probe", cam_data)
    scene.collection.objects.link(cam)
    cam.location = Vector(location)
    cam.rotation_euler = rotation
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.2, 0.4)

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)


def bounds(points):
    """The axis-aligned box of a cloud, as two corner points."""
    return points.min(axis=0), points.max(axis=0)


def main() -> None:
    glb = value_after("--glb")
    out = Path(value_after("--out")).resolve()
    threshold = float(value_after("--threshold", 0.0015))
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    bpy.ops.object.mode_set(mode="OBJECT")

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    groups = connected_faces(bm)
    print("YXZ_PIECES %s" % describe_shells(groups))
    # The halo's own shards reach above the head, so the character's
    # real extent is measured on the body shell alone -- otherwise the
    # halo is sized to include itself.
    body_group = max(groups, key=len)
    body_vertices = set()
    for face in body_group:
        for vertex in face.verts:
            body_vertices.add(vertex.index)
    everything = np.array(
        [list(bm.verts[index].co) for index in sorted(body_vertices)],
        dtype=np.float64,
    )
    print("YXZ_MODEL_BOX %s %s" % (
        [round(float(v), 4) for v in everything.min(axis=0)],
        [round(float(v), 4) for v in everything.max(axis=0)],
    ))
    # The head is the one big sphere: above the waist, and the only
    # part of the character whose radius is worth naming, because that
    # is what the halo has to clear.
    head = everything[everything[:, 2] > everything[:, 2].max() * 0.55]
    middle = head.mean(axis=0)
    print("YXZ_HEAD centre=%s radius=%.4f faces_n=%d"
          % ([round(float(v), 4) for v in middle],
             float(np.mean(np.linalg.norm(head - middle, axis=1))),
             len(head)))
    groups = [sorted(face.index for face in group) for group in groups]
    bm.free()

    # The two smallest shells are the halo's two halves; the largest is
    # the character.  Each is pulled out into a mesh of its own.
    ordered = sorted(groups, key=len)
    for number, group in enumerate(ordered):
        if len(group) > 50000:
            continue
        copy = body.data.copy()
        piece = bmesh.new()
        piece.from_mesh(copy)
        wanted = set(group)
        bmesh.ops.delete(
            piece, geom=[f for f in piece.faces if f.index not in wanted],
            context="FACES",
        )
        piece.to_mesh(copy)
        piece.free()
        obj = bpy.data.objects.new("piece%d" % number, copy)
        bpy.context.scene.collection.objects.link(obj)
        flat_material([obj], (0.15, 0.85, 0.85, 1.0))
        body.select_set(False)

        points = np.array([list(v.co) for v in obj.data.vertices])
        low, high = bounds(points)
        middle = (low + high) * 0.5
        span = float(np.max(high - low)) * 1.15
        print("YXZ_PIECE%d faces=%d low=%s high=%s span=%.4f"
              % (number, len(group),
                 [round(float(v), 4) for v in low],
                 [round(float(v), 4) for v in high], span))

        # Looking down the Z axis from above, then along Y from the
        # front, then along X from the side -- all framed on the piece.
        render(out / ("piece%d-top.png" % number),
               tuple(middle + np.array([0.0, 0.0, span * 2.0])),
               (0.0, 0.0, 0.0), span)
        render(out / ("piece%d-front.png" % number),
               tuple(middle + np.array([0.0, -span * 2.0, 0.0])),
               (math.radians(90.0), 0.0, 0.0), span)
        render(out / ("piece%d-side.png" % number),
               tuple(middle + np.array([-span * 2.0, 0.0, 0.0])),
               (math.radians(90.0), 0.0, math.radians(90.0)), span)
    print("YXZ_RENDERED " + str(out))


if __name__ == "__main__":
    main()
