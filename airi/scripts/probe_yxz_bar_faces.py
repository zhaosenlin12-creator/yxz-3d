"""
 * Show the faces that draw the bar on the visor.
 *
 * The bar is a small piece of the head standing in front of the visor.
 * Its faces are known by number -- the numbers come from the live page,
 * where a ray through the bar says which triangle it landed on -- and
 * this paints them and photographs the head, so that the piece can be
 * seen for what it is before anything is removed.
 *
 * It also photographs the head with the piece taken out, which is the
 * picture that says whether removing it is an improvement.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_bar_faces.py -- \
 *     --glb <glb> --faces <json> --out <dir> [--yaw 0]
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


def render(objects, out_path, centre, scale, yaw, size=900):
    scene = bpy.context.scene
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
    base = Vector((0.0, -1.0, 0.0))
    turned = base * np.cos(yaw) + Vector((1.0, 0.0, 0.0)) * np.sin(yaw)
    cam.location = Vector(centre) + turned * 2.0
    look = (Vector(centre) - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.2
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.2, 0.4)
    fill = bpy.data.lights.new("fill", type="AREA")
    fill.energy = 90.0
    fill.size = 2.0
    fill_obj = bpy.data.objects.new("fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = Vector(turned) * -1.6 + Vector((0.0, 0.0, centre[2] + 0.4))
    fill_obj.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)


def load(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    return body


def main() -> None:
    glb = value_after("--glb")
    faces_file = value_after("--faces")
    out = Path(value_after("--out")).resolve()
    yaw = float(value_after("--yaw", "0"))
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(json.loads(Path(faces_file).read_text()))

    # Where the bar is, so the camera can be put on it.
    body = load(glb)
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    points = np.array([
        tuple(vert.co)
        for face in bm.faces
        if face.index in wanted
        for vert in face.verts
    ])
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    centre = ((lo + hi) / 2).tolist()
    extent = hi - lo
    print("YXZ_BAR_FACES bbox " + json.dumps({
        "min": lo.tolist(), "max": hi.tolist(), "extent": extent.tolist(),
        "count": len(wanted),
    }))
    bm.free()

    # The whole head, with the bar's faces painted.
    body = load(glb)
    mesh = body.data
    # A second copy of the mesh, painted, so that the bar can be seen in
    # place rather than only in the hole it leaves.
    painted_mesh = mesh.copy()
    marked = bpy.data.objects.new("marked", painted_mesh)
    bpy.context.scene.collection.objects.link(marked)
    bm = bmesh.new()
    bm.from_mesh(painted_mesh)
    bm.faces.ensure_lookup_table()
    doomed = [face for face in bm.faces if face.index not in wanted]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(painted_mesh)
    bm.free()

    for target, colour in ((body, (0.80, 0.82, 0.85, 1.0)),
                           (marked, (0.96, 0.10, 0.40, 1.0))):
        target.data.materials.clear()
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = colour
        shader.inputs["Roughness"].default_value = 0.75
        target.data.materials.append(material)

    for angle in (0, 90, 180, 270):
        render([body, marked], out / f"marked-{angle}.png", [0.0, 0.0, 0.05], 0.75, np.radians(angle))
        print(f"YXZ_BAR_RENDERED marked-{angle}.png")

    # And the same model with the bar's faces taken out.
    body = load(glb)
    mesh = body.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    doomed = [face for face in bm.faces if face.index in wanted]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(mesh)
    bm.free()

    for target, colour in ((body, (0.80, 0.82, 0.85, 1.0)),):
        target.data.materials.clear()
        material = bpy.data.materials.new("flat")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = colour
        shader.inputs["Roughness"].default_value = 0.75
        target.data.materials.append(material)
    for angle in (0, 90, 180, 270):
        render([body], out / f"without-bar-{angle}.png", [0.0, 0.0, 0.05], 0.75, np.radians(angle))
        print(f"YXZ_BAR_RENDERED without-bar-{angle}.png")


if __name__ == "__main__":
    main()
