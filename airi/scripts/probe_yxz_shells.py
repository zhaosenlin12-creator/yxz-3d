"""Split the welded YXZ body into its shells and photograph each one.

Welding the scan collapses it into three continuous shells, and a lot of
the "shattered" look comes from one of them being a stray sheet that
lies across the face instead of being part of it.  The shells cannot be
told apart from a vertex count, so each one is rendered on its own, from
the front and from above, and the numbers that describe it are printed
beside the pictures.

Usage:
  blender -b -P scripts/probe_yxz_shells.py -- \
    --glb <glb> --out <dir> [--threshold 0.0015]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """The connected components of a bmesh, as lists of faces."""
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


def describe(bm, group):
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    area = 0.0
    for face in group:
        area += face.calc_area()
        for vertex in face.verts:
            for i in range(3):
                lo[i] = min(lo[i], vertex.co[i])
                hi[i] = max(hi[i], vertex.co[i])
    extent = hi - lo
    widths = sorted(extent)
    return {
        "faces": len(group),
        "area": round(area, 6),
        "min": [round(v, 4) for v in lo],
        "max": [round(v, 4) for v in hi],
        "extent": [round(v, 4) for v in extent],
        "slenderness": round(widths[0] / widths[2], 4) if widths[2] > 1e-9 else None,
    }


def render(objects, out_path, center, scale, size=700, up=False):
    scene = bpy.context.scene
    # Only the lights and the camera are replaced; the meshes being
    # photographed are the caller's and must survive the call.
    for obj in list(scene.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in objects:
        if obj.name not in scene.collection.objects:
            scene.collection.objects.link(obj)

    cam_data = bpy.data.cameras.new("probe")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("probe", cam_data)
    scene.collection.objects.link(cam)
    if up:
        cam.location = Vector((center[0], center[1], 2.0))
        cam.rotation_euler = (0.0, 0.0, 0.0)
    else:
        cam.location = Vector((center[0], center[1], 2.0))
        cam.rotation_euler = (0.0, 0.0, 0.0)
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

    mesh = body.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    groups = shells(bm)
    groups.sort(key=lambda group: -len(group))
    print("YXZ_SHELLS " + str(len(groups)))

    # A colour per shell, so one picture says what all of them are.
    palette = [0xE6194B, 0x3CB44B, 0x4363D8, 0xF58231, 0x911EB4, 0x46F0F0]
    copies = []
    for index, group in enumerate(groups):
        info = describe(bm, group)
        print("YXZ_SHELL %d %s" % (index, json.dumps(info)))

        # A copy of just this shell, so it can be photographed on its own.
        copy = mesh.copy()
        copy.name = "shell%d" % index
        keep = set(f.index for f in group)
        keep_bm = bmesh.new()
        keep_bm.from_mesh(copy)
        doomed = [f for f in keep_bm.faces if f.index not in keep]
        bmesh.ops.delete(keep_bm, geom=doomed, context="FACES")
        keep_bm.to_mesh(copy)
        keep_bm.free()
        obj = bpy.data.objects.new("shell%d" % index, copy)
        bpy.context.scene.collection.objects.link(obj)
        copies.append((obj, palette[index % len(palette)]))

        center = [
            (info["min"][i] + info["max"][i]) / 2 for i in range(3)
        ]
        span = max(info["extent"])
        render([obj], out / ("shell%d-front.png" % index),
               (center[0], center[1]), max(span * 1.3, 0.05))
        print("YXZ_SHELL_RENDERED %d" % index)

    # The same shells in one frame, each in its own colour.
    for obj, colour in copies:
        obj.data.materials.clear()
        material = bpy.data.materials.new("shell")
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
            ((colour >> 16) & 255) / 255.0,
            ((colour >> 8) & 255) / 255.0,
            (colour & 255) / 255.0,
            1.0,
        )
        material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
        obj.data.materials.append(material)
    bpy.data.objects.remove(body, do_unlink=True)
    render([obj for obj, _ in copies], out / "shells-front.png", (0.0, 0.0), 1.05)
    print("YXZ_SHELL_RENDERED all")

    print("YXZ_SHELL_SUMMARY " + json.dumps([describe(bm, g) for g in groups]))
    bm.free()


if __name__ == "__main__":
    main()
