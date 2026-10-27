"""Render a body mesh on a metric grid, so landmarks can be measured.

The rig is placed by measurement, and a landmark measured in a picture is
only half a landmark: the front view gives the left/right and the height,
the side view gives the depth, and the two together are the point in space.
So the mesh is drawn twice, orthographically, on the same grid, with the
same vertical scale, and the numbers on the grid are metres in mesh space.

The mesh is read in the frame the runtime uses: Blender's Z-up, the
character facing -Y and its own left on +X.  A VRM 1.0 asset faces +Z by
spec, and Blender's glTF exporter maps (x, y, z) to (x, z, -y), so a
character that faces -Y here is facing +Z in the exported file.

Every view also writes a JSON map next to the PNG.  The render is
orthographic, so the mapping from pixels to mesh units is exact, and
writing it down is what turns a measurement into a number.

  blender -b -P render_grid.py -- --glb body.glb --out .run/grid [--step 0.1]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def look_at(cam, loc, target, up):
    """Aim an orthographic camera, with a fixed up axis."""
    cam.location = loc
    forward = (Vector(target) - Vector(loc)).normalized()
    cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()


def view_map(scene, cam, size, u_axis, v_axis):
    """The exact pixel-to-mesh mapping of one orthographic view."""
    def px(point):
        co = world_to_camera_view(scene, cam, Vector(point))
        return (co.x * size, (1.0 - co.y) * size)

    origin = px((0.0, 0.0, 0.0))
    unit = px(u_axis)
    span = abs(unit[0] - origin[0]) or abs(unit[1] - origin[1])
    return {
        "pixels_per_unit": span or 1.0,
        "origin_px": [origin[0], origin[1]],
        "u": list(u_axis),
        "v": list(v_axis),
        "resolution": size,
    }


def main():
    glb = value_after("--glb")
    out = Path(value_after("--out", ".run/grid"))
    step = float(value_after("--step", "0.1"))
    size = int(value_after("--size", "1100"))
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh in the file")
    points = []
    for obj in meshes:
        points.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    height = hi.z - lo.z
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2))
    print(f"YXZ_GRID bounds {lo.to_tuple()} .. {hi.to_tuple()} height={height:.3f}")

    # A flat grid on the floor, in the same units, so the numbers on it are
    # the numbers a landmark needs.
    grid = bpy.data.meshes.new("grid")
    verts, faces = [], []
    n = int((hi.x - lo.x) / step) + 2
    m = int((hi.y - lo.y) / step) + 2
    ox = lo.x - step
    oy = lo.y - step
    for i in range(n):
        verts.append((ox + i * step, oy, lo.z - step * 0.5))
        verts.append((ox + i * step, oy + (m - 1) * step, lo.z - step * 0.5))
    for i in range(n - 1):
        faces.append((2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2))
    verts2, faces2 = [], []
    for j in range(m):
        verts2.append((ox, oy + j * step, lo.z - step * 0.5))
        verts2.append((ox + (n - 1) * step, oy + j * step, lo.z - step * 0.5))
    for j in range(m - 1):
        faces2.append((2 * j, 2 * j + 1, 2 * j + 3, 2 * j + 2))
    grid.from_pydata(verts + verts2, [], faces + faces2)
    grid.update()
    grid_obj = bpy.data.objects.new("grid", grid)
    scene.collection.objects.link(grid_obj)

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.10, 0.13, 1.0)
    scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.15
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.85, 0.87, 0.9)
    scene.display.shading.show_cavity = True
    scene.render.film_transparent = False

    # The character faces -Y and its own left is +X.  The front view is
    # taken from in front of it, so the image's right is the character's
    # left; the side view is taken from its right, so the image's right is
    # the direction it faces.
    far = height * 2
    views = {
        "front": (
            Vector((centre.x, lo.y - far, centre.z)),
            Vector((centre.x, centre.y, centre.z)),
            (1.0, 0.0, 0.0), (0.0, 0.0, 1.0),
        ),
        "side": (
            Vector((lo.x - far, centre.y, centre.z)),
            Vector((centre.x, centre.y, centre.z)),
            (0.0, -1.0, 0.0), (0.0, 0.0, 1.0),
        ),
        "top": (
            Vector((centre.x, centre.y, hi.z + far)),
            Vector((centre.x, centre.y, centre.z)),
            (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
        ),
    }
    for name, (loc, target, u_axis, v_axis) in views.items():
        look_at(cam, loc, target, v_axis)
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_GRID_VIEW " + scene.render.filepath)
        map_path = out / f"{name}.json"
        map_path.write_text(
            json.dumps(view_map(scene, cam, size, u_axis, v_axis), indent=2),
            encoding="utf-8")
        print("YXZ_GRID_MAP " + str(map_path))


main()
