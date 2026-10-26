"""Overlay a candidate skeleton on the YXZ source mesh and render it.

The joint positions cannot be read off a point cloud, so they are proposed
and then looked at: markers on every joint, a rod along every bone, and the
mesh behind them.  If a rod does not lie inside the limb it is supposed to
drive, the chain is wrong.

  blender -b -P scripts/probe_yxz_bones.py -- --source <glb> --out <dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


# The candidate chain, in the source Tripo frame: the character faces +X,
# its own left is +Y.  The left arm is the one raised in a wave, the right
# arm hangs down holding a book.
CHAIN = {
    "spine": ((0.04, 0.0, -0.19), (0.04, 0.0, -0.13)),
    "chest": ((0.04, 0.0, -0.06), (0.04, 0.0, -0.015)),
    "neck": ((0.04, 0.0, -0.04), (0.04, 0.0, 0.0)),
    "head": ((0.04, 0.0, 0.0), (0.04, 0.0, 0.36)),
    "leftShoulder": ((0.0, 0.045, 0.045), (0.02, 0.140, 0.020)),
    "leftUpperArm": ((0.02, 0.140, 0.020), (0.075, 0.195, -0.075)),
    "leftLowerArm": ((0.075, 0.195, -0.075), (0.165, 0.285, -0.020)),
    "leftHand": ((0.165, 0.285, -0.020), (0.198, 0.325, 0.035)),
    "rightShoulder": ((0.0, -0.045, 0.045), (0.015, -0.140, 0.020)),
    "rightUpperArm": ((0.015, -0.140, 0.020), (0.030, -0.165, -0.070)),
    "rightLowerArm": ((0.030, -0.165, -0.070), (0.075, -0.175, -0.160)),
    "rightHand": ((0.075, -0.175, -0.160), (0.105, -0.185, -0.215)),
}


def rod_colour(name):
    if name.startswith("left"):
        return (1.0, 0.1, 0.1, 1.0)
    if name.startswith("right"):
        return (0.1, 0.4, 1.0, 1.0)
    return (1.0, 0.85, 0.1, 1.0)


def marker(name, head, tail):
    """A rod between two joints, so the chain can be seen on the mesh."""
    head = Vector(head)
    tail = Vector(tail)
    direction = tail - head
    length = direction.length
    if length < 1e-6:
        return
    material = bpy.data.materials.new("rod_" + name)
    material.diffuse_color = rod_colour(name)
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.008,
                                         depth=length,
                                         location=(head + tail) / 2)
    rod = bpy.context.object
    rod.name = "rod_" + name
    rod.rotation_mode = "QUATERNION"
    rod.rotation_quaternion = direction.to_track_quat("Z", "Y")
    rod.data.materials.append(material)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8,
                                         radius=0.017, location=head)
    joint = bpy.context.object
    joint.name = "joint_" + name
    joint.data.materials.append(material)


def main() -> None:
    source = value_after("--source")
    out_dir = Path(value_after("--out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 760
    scene.render.resolution_y = 980
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_cavity = True
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.06, 0.08, 1)
    scene.world = world

    for name, (head, tail) in CHAIN.items():
        marker(name, head, tail)

    meshes = [o for o in scene.objects
              if o.type == "MESH" and not o.name.startswith(("rod_", "joint_"))]
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for corner in meshes[0].bound_box:
        for i in range(3):
            lo[i] = min(lo[i], corner[i])
            hi[i] = max(hi[i], corner[i])
    centre = Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    height = max(hi[i] - lo[i] for i in range(3))
    focus = bpy.data.objects.new("Focus", None)
    focus.location = centre
    scene.collection.objects.link(focus)
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.15
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    track = cam.constraints.new("TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam
    for name, direction in (("front", Vector((1, 0, 0))),
                            ("side", Vector((0, -1, 0)))):
        cam.location = centre + direction * height * 3
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"bones_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_BONES_VIEW " + scene.render.filepath)


if __name__ == "__main__":
    main()
