"""Render the head of a YXZ asset straight from Blender, for side-by-side.

The stage renders the character through the browser, which is the only
place the shipping look can be judged, but it is also the only place the
mesh is hard to look at: the rig has been rescaled, the camera is a
perspective one and the pose is whatever the clip was parked on.  When
the question is "is this piece of geometry there at all", a plain
orthographic render of the same file settles it.

Usage:
  blender -b -P scripts/render_yxz_head.py -- \
    --glb <glb> --out <png> [--center-y 0.28] [--scale 0.55] [--size 800]
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    center_z = float(value_after("--center-z", 0.28))
    scale = float(value_after("--scale", 0.55))
    size = int(value_after("--size", 800))
    centre = value_after("--center")
    if centre:
        centre = Vector([float(part) for part in centre.split(",")])
    else:
        centre = Vector((0.0, 0.0, center_z))
    # Where to stand to look at it.  The head is turned in the rest pose,
    # so the direction that shows the face is not simply "the front".
    yaw = math.radians(float(value_after("--yaw", 0.0)))
    pitch = math.radians(float(value_after("--pitch", 0.0)))
    distance = float(value_after("--distance", 2.0))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    # Blender 5.2's glTF importer leaves an `Icosphere` behind for this VRM:
    # 42 vertices, 80 faces, a unit sphere at the origin, no material, no
    # vertex groups, no parent.  Every mesh the file declares has all three.
    # A unit sphere at the origin swallows the whole frame, so every audit
    # render made before this was a picture of a ball.
    for stray in [o for o in scene.objects if o.type == "MESH" and not o.data.materials]:
        stray_name = stray.name
        stray_mesh = stray.data
        # Removed straight from the database rather than unlinked first:
        # the importer puts its object in a child collection, and unlinking
        # it from the scene root it was never in raises.
        bpy.data.objects.remove(stray, do_unlink=True)
        bpy.data.meshes.remove(stray_mesh)
        print("YXZ_DROPPED_IMPORTER_HELPER " + stray_name)

    # A flat white shell with the base colour map on it.  The map is what
    # shows whether a piece of the design is still there; the flat white
    # shows whether the geometry is.  `--textured` keeps the model's own
    # materials instead, which is what shows whether the design is
    # arriving on the right pixels.
    if "--unlit" in sys.argv:
        # Emission does not care which way a face points, so every scrap of
        # geometry that is there comes out white.  Anything still black is a
        # real gap, not a face turned the wrong way round.
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            material = bpy.data.materials.new("unlit")
            material.use_nodes = True
            nodes = material.node_tree.nodes
            nodes.clear()
            # Not named `out`: that is the path this render is going to,
            # and shadowing it silently sends the image nowhere.
            surface = nodes.new("ShaderNodeOutputMaterial")
            emit = nodes.new("ShaderNodeEmission")
            emit.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            material.node_tree.links.new(emit.outputs["Emission"], surface.inputs["Surface"])
            obj.data.materials.append(material)
    elif "--textured" not in sys.argv:
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
                0.85, 0.85, 0.88, 1.0)
            material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
            obj.data.materials.append(material)

    cam_data = bpy.data.cameras.new("head")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = scale
    cam = bpy.data.objects.new("head", cam_data)
    scene.collection.objects.link(cam)
    # Blender is Z-up, so a front view looks along the Y axis with +Z up.
    # Which way the character faces is not assumed: the view can be
    # flipped with `--flip`.
    # The front view puts the camera at -Y looking back towards +Y; the
    # back view puts it at +Y and turns it around, so both keep +Z up.
    flip = "--flip" in sys.argv
    base = Vector((0.0, 1.0 if flip else -1.0, 0.0))
    turned = base * math.cos(yaw) + Vector((1.0, 0.0, 0.0)) * math.sin(yaw)
    cam.location = centre + turned * (distance * math.cos(pitch))
    cam.location.z += distance * math.sin(pitch)
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.9, 0.2, 0.4)
    fill = bpy.data.lights.new("fill", type="AREA")
    fill.energy = 60.0
    fill.size = 2.0
    fill_obj = bpy.data.objects.new("fill", fill)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = Vector((-1.2, 1.6 if flip else -1.6, center_z + 0.4))
    fill_obj.rotation_euler = (1.1, 0.0, -0.6)

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("YXZ_HEAD_RENDERED " + str(out))


if __name__ == "__main__":
    main()
