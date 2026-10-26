"""Name the faces that make up the visible shards.

The red in the shatter render says *where* the character is broken.  This
turns that into *what*, so a shard can be removed by naming the piece of
the scan it is rather than by the rectangle of the screen it happens to
occupy on one frame.

Picking it in the running app cannot do it, and neither can a ray cast in
Blender: a shard is turned away from the camera, so a ray fired into it
passes straight through and reports whatever is behind it, which is clean.
Every pick lands on the body and every pick comes back clean.

What works is to stop firing rays and start projecting.  Every face in the
model is projected into the camera's picture, and the faces that land on a
red pixel are sorted by how near they are.  The first one is what the
camera is actually looking at at that pixel, and for a red pixel that is
the shard -- the ray cast cannot say so because it never sees the shard,
and the projection can because the shard is nearer than anything else
there.

The shards come back as a list of face indices, which is written beside
the picture and printed beside it, so the list can be looked at before it
is trusted.

Usage:
  blender -b -P scripts/probe_yxz_shardpick.py -- \
    --glb <glb> --mask <shatter-seen.png> --front 1,0 --out <png>
"""

from __future__ import annotations

import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector


FRONT = [1.0, 0.0]
RESOLUTION = 900


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def aim_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world():
    """A camera in the same place the probe's other renders put it."""
    world = bpy.data.worlds.new("probe")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        1.0, 1.0, 1.0, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", data)
    bpy.context.scene.collection.objects.link(camera)
    data.lens = 85.0
    camera.location = Vector((FRONT[0] * 6.0, FRONT[1] * 6.0, 1.30))
    bpy.context.scene.camera = camera
    aim_at(camera, (0.0, 0.0, 0.22))

    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    bpy.context.view_layer.update()
    return scene, camera


def read_mask(path):
    """The pixels the shatter render marked red."""
    image = bpy.data.images.load(path)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    frame = pixels.reshape(height, width, 4)[::-1]
    bpy.data.images.remove(image)
    red = (frame[:, :, 0] > 0.5) & (frame[:, :, 1] < 0.35) & (frame[:, :, 2] < 0.35)
    return red


def project(body, camera, scene):
    """Where the centre of every face lands, and how far away it is.

    This is the camera's own maths rather than a helper's, so the pixel
    that is read off a picture and the pixel a face lands on are the same
    pixel by construction.  `check_projection` proves it against Blender's
    own helper before anything is counted.

    The picture's scale is read off the camera's own view frame rather than
    worked out from the lens and the sensor, because those two do not
    describe the picture on their own: the sensor's fit, the aspect of the
    render and any shift all go into it.  `view_frame` hands back the four
    corners of the picture already placed and already scaled, so the scale
    is read off a corner rather than derived, and a face that lands on a
    pixel here lands on that same pixel in the render.

    A polygon's loops run one after another with no gaps between them, so
    the per-face sums are a segmented reduction over the loop array and the
    whole mesh is measured in one pass rather than face by face.
    """
    mesh = body.data
    matrix = np.array(camera.matrix_world.inverted())
    coords = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    local = np.hstack([coords, np.ones((len(coords), 1))]) @ matrix.T

    starts = np.empty(len(mesh.polygons), dtype=np.int64)
    totals = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)
    loops = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", loops)

    per_loop = local[loops]
    safe_totals = np.where(totals > 0, totals, 1)
    centre_x = np.add.reduceat(per_loop[:, 0], starts) / safe_totals
    centre_y = np.add.reduceat(per_loop[:, 1], starts) / safe_totals
    centre_z = np.add.reduceat(per_loop[:, 2], starts) / safe_totals

    depth = -centre_z
    safe = np.where(depth > 1e-6, depth, 1e-6)
    frame = camera.data.view_frame(scene=scene)
    wide = max(frame, key=lambda corner: abs(corner.x))
    tall = max(frame, key=lambda corner: abs(corner.y))
    # The frame's corners are already half a picture wide, so a corner at
    # half a picture and at its own depth gives the distance one whole
    # picture spans at a depth of one.
    scale_x = 0.5 * abs(wide.z) / max(abs(wide.x), 1e-9)
    scale_y = 0.5 * abs(tall.z) / max(abs(tall.y), 1e-9)
    py = (0.5 - (centre_y / safe) * scale_y) * RESOLUTION
    px = (0.5 + (centre_x / safe) * scale_x) * RESOLUTION
    return px, py, depth, starts, totals, loops, coords


def check_projection(body, camera, scene, px, py, starts, totals, loops, coords):
    """Blender's own projection, against this one."""
    from bpy_extras.object_utils import world_to_camera_view
    mesh = body.data
    for face_index in range(0, len(mesh.polygons),
                            max(1, len(mesh.polygons) // 12)):
        start = starts[face_index]
        total = totals[face_index]
        vertex = loops[start]
        theirs = world_to_camera_view(scene, camera, Vector(coords[vertex].tolist()))
        print("YXZ_PROJECT face %d mine %.2f %.2f helper %.2f %.2f" % (
            face_index, px[face_index], py[face_index],
            theirs.x * RESOLUTION, (1.0 - theirs.y) * RESOLUTION))


def flat_material(name, colour):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = colour + (1.0,)
    emission.inputs["Strength"].default_value = 1.0
    tree.links.new(emission.outputs["Emission"], out.inputs["Surface"])
    return mat


def main() -> None:
    global FRONT
    front = value_after("--front")
    if front:
        FRONT = [float(v) for v in front.split(",")]

    source = os.path.abspath(value_after("--glb"))
    mask_path = os.path.abspath(value_after("--mask"))
    out = os.path.abspath(value_after("--out"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    scene, camera = setup_world()
    px, py, depth, starts, totals, loops, coords = project(body, camera, scene)
    check_projection(body, camera, scene, px, py, starts, totals, loops, coords)

    mask = read_mask(mask_path)
    mesh = body.data
    facing = np.empty(len(mesh.polygons) * 3, dtype=np.float64)
    mesh.polygons.foreach_get("normal", facing)
    facing = facing.reshape(-1, 3)
    toward = facing[:, 0] * FRONT[0] + facing[:, 1] * FRONT[1]

    ix = np.round(px).astype(np.int64)
    iy = np.round(py).astype(np.int64)
    inside = (ix >= 0) & (ix < RESOLUTION) & (iy >= 0) & (iy < RESOLUTION)
    key = np.where(inside, iy * RESOLUTION + ix, -1)

    wanted = np.nonzero(mask.ravel())[0]
    if wanted.size == 0:
        print("YXZ_SHARDPICK " + json.dumps({"redPixels": 0}))
        return

    # For every pixel of the mask, the nearest face that lands on it.  The
    # sort puts the faces in pixel order and, within a pixel, in order of
    # their distance, so the first face listed under a pixel is the one the
    # camera is looking at there.
    order = np.lexsort((depth, key))
    sorted_key = key[order]
    first = np.ones(len(sorted_key), dtype=bool)
    first[1:] = sorted_key[1:] != sorted_key[:-1]
    wanted_set = np.zeros(RESOLUTION * RESOLUTION, dtype=bool)
    wanted_set[wanted] = True
    nearest = {}
    for position in np.nonzero(first)[0]:
        pixel = sorted_key[position]
        if pixel < 0 or not wanted_set[pixel]:
            continue
        face = order[position]
        if toward[face] < 0.0:
            nearest[int(pixel)] = int(face)

    picked = sorted(set(nearest.values()))
    if not picked:
        print("YXZ_SHARDPICK " + json.dumps({
            "redPixels": int(wanted.size), "pickedFaces": 0}))
        return

    uv = mesh.uv_layers.active
    us = []
    vs = []
    points = []
    for face_index in picked:
        start = starts[face_index]
        total = totals[face_index]
        for offset in range(start, start + total):
            us.append(uv.data[offset].uv.x)
            vs.append(uv.data[offset].uv.y)
            points.append(coords[loops[offset]])

    cloud = np.array(points)

    # The shards are several separate pieces that happen to sit in the same
    # places, so they are grouped before they are measured: a box drawn
    # around all of them together would be most of the character, and a box
    # is the thing a removal is written as.
    clusters = []
    unvisited = set(picked)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            start = starts[current]
            total = totals[current]
            corners = set(loops[offset]
                           for offset in range(start, start + total))
            for other in list(unvisited):
                other_start = starts[other]
                other_total = totals[other]
                other_corners = set(
                    loops[offset]
                    for offset in range(other_start, other_start + other_total))
                if corners & other_corners:
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        clusters.append(sorted(group))
    clusters.sort(key=len, reverse=True)

    cluster_report = []
    for group in clusters:
        group_points = []
        for face_index in group:
            start = starts[face_index]
            total = totals[face_index]
            for offset in range(start, start + total):
                group_points.append(coords[loops[offset]])
        group_cloud = np.array(group_points)
        cluster_report.append({
            "faces": len(group),
            "low": [round(float(c), 4) for c in group_cloud.min(axis=0)],
            "high": [round(float(c), 4) for c in group_cloud.max(axis=0)],
        })
        print("YXZ_SHARD_GROUP " + json.dumps(cluster_report[-1]))

    report = {
        "redPixels": int(wanted.size),
        "pickedPixels": len(nearest),
        "pickedFaces": len(picked),
        "clusters": cluster_report,
        "uv": [round(min(us), 4), round(min(vs), 4),
               round(max(us), 4), round(max(vs), 4)] if us else None,
        "low": [round(float(c), 4) for c in cloud.min(axis=0)],
        "high": [round(float(c), 4) for c in cloud.max(axis=0)],
    }
    print("YXZ_SHARDPICK " + json.dumps(report))

    with open(os.path.splitext(out)[0] + ".json", "w") as handle:
        json.dump({"faces": picked, "report": report}, handle)

    # The same faces are painted back onto the model, so the list can be
    # looked at before it is trusted.
    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.66, 0.68, 0.71)))
    body.data.materials.append(flat_material("shard", (1.0, 0.05, 0.35)))
    for face_index in picked:
        mesh.polygons[face_index].material_index = 1

    data = bpy.data.lights.new("key", type="SUN")
    data.energy = 0.0
    light = bpy.data.objects.new("key", data)
    bpy.context.scene.collection.objects.link(light)
    light.location = Vector((FRONT[0], FRONT[1], 0.0))
    aim_at(light, (0.0, 0.0, 0.0))
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
