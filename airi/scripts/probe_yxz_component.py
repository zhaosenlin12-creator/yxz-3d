"""Find the piece of geometry a face belongs to, and how big that piece is.

The scraps on the character are loose pieces of the scan: separate sheets
that are not attached to anything, each with its own patch of the texture
map.  A rectangle of the map will not find one, because the patch of a
scrap is not a rectangle -- it is whatever shape the packing gave it, and
cutting a rectangle out of it cuts a hole in whatever it was lying on.

Reachability does find one.  A loose piece is a connected component of
its own, and a component can be taken away whole, which is the only
thing that is safe to do with a scrap: take all of it, or take none of it.

Usage:
  blender -b -P scripts/probe_yxz_component.py -- \
    --glb <glb> --face <index> [--out <png>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def component_of(bm, seed):
    """The set of faces reachable from a face through shared edges."""
    seed_index = seed.index
    group = [seed]
    seen = {seed_index}
    stack = [seed]
    while stack:
        face = stack.pop()
        for edge in face.edges:
            for other in edge.link_faces:
                if other.index in seen:
                    continue
                seen.add(other.index)
                group.append(other)
                stack.append(other)
    return group


def main() -> None:
    glb = value_after("--glb")
    face_index = value_after("--face")
    uv_point = value_after("--uv")
    out = value_after("--out")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    if uv_point:
        # The face index a browser reports is the index in the deployed
        # file, and the rig and the VRM writer both renumber, so the
        # texture coordinate is the join that survives.
        u, v = [float(part) for part in uv_point.split(",")]
        best = None
        best_distance = 1e9
        layer = bm.loops.layers.uv.active
        for face in bm.faces:
            cu = sum(loop[layer].uv.x for loop in face.loops) / len(face.loops)
            cv = sum(loop[layer].uv.y for loop in face.loops) / len(face.loops)
            distance = (cu - u) ** 2 + (cv - v) ** 2
            if distance < best_distance:
                best_distance = distance
                best = face
        face_index = best.index
        print("YXZ_COMPONENT_UV_LOOKUP face=%d distance=%.5f"
              % (face_index, best_distance ** 0.5))
    else:
        face_index = int(face_index)

    if face_index >= len(bm.faces):
        print("YXZ_COMPONENT out-of-range faces=%d" % len(bm.faces))
        bm.free()
        return

    group = component_of(bm, bm.faces[face_index])
    cloud = np.array([list(face.calc_center_median()) for face in group])
    uvs = np.array([
        [
            sum(loop[bm.loops.layers.uv.active].uv.x for loop in face.loops) / len(face.loops),
            sum(loop[bm.loops.layers.uv.active].uv.y for loop in face.loops) / len(face.loops),
        ]
        for face in group
    ])

    print("YXZ_COMPONENT faces=%d" % len(group))
    print("YXZ_COMPONENT low=%s high=%s"
          % ([round(float(value), 4) for value in cloud.min(axis=0)],
             [round(float(value), 4) for value in cloud.max(axis=0)]))
    print("YXZ_COMPONENT_UV low=%s high=%s"
          % ([round(float(value), 4) for value in uvs.min(axis=0)],
             [round(float(value), 4) for value in uvs.max(axis=0)]))

    if out:
        keep = set(face.index for face in group)
        copy = body.data.copy()
        piece = bmesh.new()
        piece.from_mesh(copy)
        piece.faces.ensure_lookup_table()
        bmesh.ops.delete(
            piece,
            geom=[face for face in piece.faces if face.index not in keep],
            context="FACES",
        )
        piece.to_mesh(copy)
        piece.free()
        obj = bpy.data.objects.new("piece", copy)
        bpy.context.scene.collection.objects.link(obj)
        for target, colour in ((obj, (0.96, 0.10, 0.40, 1.0)),
                               (body, (0.78, 0.80, 0.83, 1.0))):
            target.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            shader = material.node_tree.nodes["Principled BSDF"]
            shader.inputs["Base Color"].default_value = colour
            shader.inputs["Roughness"].default_value = 0.7
            target.data.materials.append(material)

        middle = Vector([float(value) for value in cloud.mean(axis=0)])
        span = max(float((cloud.max(axis=0) - cloud.min(axis=0)).max()) * 2.2, 0.12)
        cam_data = bpy.data.cameras.new("piece")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = span
        cam = bpy.data.objects.new("piece", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        look = (middle - Vector((1.0, -1.0, 0.35))).normalized()
        cam.location = middle + look * 2.0
        cam.rotation_euler = (-look).to_track_quat("-Z", "Y").to_euler()
        scene = bpy.context.scene
        scene.camera = cam

        key = bpy.data.lights.new("key", type="SUN")
        key.energy = 3.0
        key_obj = bpy.data.objects.new("key", key)
        scene.collection.objects.link(key_obj)
        key_obj.rotation_euler = (0.9, 0.2, 0.4)
        fill = bpy.data.lights.new("fill", type="AREA")
        fill.energy = 50.0
        fill.size = 2.0
        fill_obj = bpy.data.objects.new("fill", fill)
        scene.collection.objects.link(fill_obj)
        fill_obj.location = middle + Vector((-1.2, -1.4, 0.4))
        fill_obj.rotation_euler = (1.1, 0.0, -0.6)

        scene.render.resolution_x = 900
        scene.render.resolution_y = 900
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("YXZ_COMPONENT_RENDERED " + str(out))

    bm.free()


if __name__ == "__main__":
    main()
