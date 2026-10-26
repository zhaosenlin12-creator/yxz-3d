"""Find the sheets folded back onto the face, and show what was found.

The scan folded pieces of the helmet's trim back on themselves and left
them lying across the cheeks.  On screen they are the bright white flaps
with a hard straight edge that cut across the face, and they are the
reason the character reads as broken rather than as a model.

They are also the reason a ray cast into the model finds nothing there.
A flap folded back presents its back to the camera, and the scan's
surfaces are single sided, so the ray passes straight through the flap
and hits the cheek behind it -- or misses the face entirely.  Picking
the debris by clicking on it in the running app therefore reports the
cheek, never the flap.  What the flap actually is, is a face whose
normal has been turned away from the front while its own geometry still
sits out in front of the visor.

So the flaps are found by direction rather than by position: inside the
face, a surface that is turned back on itself.  The ones that are
genuinely part of the helmet -- the inside of the ear cups, the liner
behind the visor -- are turned away too, so the search is bounded to the
front of the head and the result is rendered, because a list of faces
only means something once it has been looked at.

Usage:
  blender -b -P scripts/probe_yxz_flaps.py -- \
    --glb <glb> --out <png> [--flip] [--x0 a] [--x1 b] [--z0 c] [--z1 d]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector


# Where the face is.  The measured frame puts the front of the character
# on +X, so "in front of the face" is a large X and "turned away from the
# camera" is a normal with a small or negative X.
DEFAULT_X = (0.10, 0.32)
DEFAULT_Z = (-0.02, 0.20)
DEFAULT_Y = (-0.24, 0.02)

# Which way the character is facing, in the frame this probe reads the
# scan in.  Set from the command line by `--front x,y` once it is known.
FRONT = [1.0, 0.0]


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def find_flaps(bm, x_range, y_range, z_range, flipped):
    """The faces in front of the face that are turned back on themselves."""
    picked = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if not (x_range[0] <= centre.x <= x_range[1]):
            continue
        if not (y_range[0] <= centre.y <= y_range[1]):
            continue
        if not (z_range[0] <= centre.z <= z_range[1]):
            continue
        normal = Vector(face.normal)
        if normal.length < 1e-6:
            continue
        normal.normalize()
        # A surface turned away from the camera is one whose normal
        # points back along the front axis.
        depth = normal.x * FRONT[0] + normal.y * FRONT[1]
        away = depth < 0.0
        if flipped:
            away = depth > 0.0
        if away:
            picked.append(face)
    return picked


def report(flaps, uv_layer):
    us, vs, pts = [], [], []
    for face in flaps:
        us.append(sum(l[uv_layer].uv.x for l in face.loops) / len(face.loops))
        vs.append(sum(l[uv_layer].uv.y for l in face.loops) / len(face.loops))
        pts.append(list(face.calc_center_median()))
    if not us:
        return {"faces": 0}
    pts = np.array(pts)
    return {
        "faces": len(flaps),
        "uvLow": [round(min(us), 4), round(min(vs), 4)],
        "uvHigh": [round(max(us), 4), round(max(vs), 4)],
        "xyzLow": [round(float(v), 4) for v in pts.min(axis=0)],
        "xyzHigh": [round(float(v), 4) for v in pts.max(axis=0)],
    }


def setup_world():
    """A grey world and a camera out in front of the face.

    The scene is not cleared: the character that was imported is the
    thing being looked at.
    """
    world = bpy.data.worlds.new("probe")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.05, 0.05, 0.06, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", data)
    bpy.context.scene.collection.objects.link(camera)
    data.lens = 85.0
    camera.location = Vector((FRONT[0] * 6.0, FRONT[1] * 6.0, 1.30))
    bpy.context.scene.camera = camera
    direction = Vector((0.0, 0.0, 0.22)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # A silhouette is not a reading: without light the probe can only say
    # where the character is, not which of its surfaces turned back.
    for name, location, energy in (
            ("key", (FRONT[0] * 2.0 - 1.0, FRONT[1] * 2.0 - 2.0, 2.4), 320.0),
            ("fill", (FRONT[0] * -2.2 + 1.2, FRONT[1] * -2.2 + 1.0, 0.6), 120.0),
            ("rim", (FRONT[0] * -3.0, FRONT[1] * -3.0, 1.8), 160.0)):
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = energy
        data.size = 2.0
        light = bpy.data.objects.new(name, data)
        light.location = Vector(location)
        bpy.context.scene.collection.objects.link(light)
        light.rotation_euler = (
            Vector((0.0, 0.0, 0.2)) - light.location
        ).to_track_quat("-Z", "Y").to_euler()

    # The render operator updates the dependency graph on its own, so the
    # picture comes out right either way.  Anything that reads the camera's
    # matrix directly -- a projection, a ray cast -- does not, and would
    # go on using an identity matrix and report every point as being
    # behind the lens.
    bpy.context.view_layer.update()

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            bpy.context.scene.render.engine = engine
            break
        except TypeError:
            continue


def flat_material(name, colour):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = colour
    bsdf.inputs["Roughness"].default_value = 0.55
    return mat


def pick_uv(body, picks):
    """Report the atlas patch under each given pixel of the probe render.

    Picking in the running app cannot find a folded sheet: the sheet is
    turned away from the camera, so the ray passes straight through it and
    reports the cheek behind.  Picking here has the same fault, so this
    does not ray cast at all.  It projects the centre of every face into
    the camera and reports the ones that land on the pixel, nearest
    first.  A folded sheet is normally the frontmost thing at the pixel
    even when it is back facing, so the nearest of them is the one wanted.
    """
    scene = bpy.context.scene
    setup_world()
    # The same size as the render the pixels were read off.
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    width = scene.render.resolution_x
    height = scene.render.resolution_y
    camera = scene.camera
    uv_layer = body.data.uv_layers.active
    depsgraph = bpy.context.evaluated_depsgraph_get()
    atlas = None
    for image in bpy.data.images:
        if image.name.startswith("Color") or "base_color" in image.name.lower():
            atlas = image
            break
    pixels = None
    size = None
    if atlas is not None:
        pixels = np.empty(len(atlas.pixels), dtype=np.float32)
        atlas.pixels.foreach_get(pixels)
        size = atlas.size
    # The corners of the camera's own view frame, in camera space.  Every
    # projection is worked out from these rather than from a helper, so
    # the pixel that is read off the render and the ray that is fired are
    # the same ray by construction.
    # `view_frame` hands back four corners whose order is not written
    # down anywhere, so they are sorted into a known one: top of the
    # picture first, then left to right within each row.
    frame = sorted(camera.data.view_frame(scene=scene),
                   key=lambda corner: (round(corner.y, 6), corner.x))
    top_left, top_right, bottom_left, bottom_right = frame
    rotation = camera.matrix_world.to_3x3()

    for raw in picks:
        px, py = (float(value) for value in raw.split(","))
        # Pixels are counted from the top left; the camera helper counts
        # from the bottom left in the same 0..1 space.
        u = px / width
        v = 1.0 - py / height
        across_top = top_left.lerp(top_right, u)
        across_bottom = bottom_left.lerp(bottom_right, u)
        point = across_top.lerp(across_bottom, v)
        origin = camera.matrix_world.translation
        direction = (rotation @ point).normalized()

        rows = []
        hit, location, normal, index, obj, _ = scene.ray_cast(
            depsgraph, origin, direction)
        if hit and obj == body:
            face = body.data.polygons[index]
            uv = uv_layer.data[face.loop_start].uv
            row = {
                "uv": [round(uv.x, 5), round(uv.y, 5)],
                "world": [round(c, 4) for c in location],
                "normal": [round(c, 3) for c in normal],
            }
            if pixels is not None:
                width, height = size
                px = min(width - 1, max(0, int(uv.x * width)))
                py = min(height - 1, max(0, int(uv.y * height)))
                texel = pixels.reshape(height, width, 4)[py, px]
                row["atlas"] = [round(float(c), 4) for c in texel[:3]]
            rows.append(row)
        else:
            rows.append({"miss": True, "hitObject": obj.name if hit else None})
        print("YXZ_PICK %s %s" % (raw, json.dumps(rows)))


def project_points(points):
    """Say where a point in the model lands on the probe render.

    Reading a pixel off a picture by eye is how a pick ends up on the
    crown when it was meant for the chin.  This asks the camera where a
    point is instead, so the two agree by construction.
    """
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    setup_world()
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    camera = scene.camera

    for raw in points:
        x, y, z = (float(value) for value in raw.split(","))
        target = Vector((x, y, z))
        projected = world_to_camera_view(scene, camera, target)
        print("YXZ_WHERE %s -> px %.1f %.1f (behind=%s)" % (
            raw, projected.x * 900, (1.0 - projected.y) * 900, projected.z <= 0))


def show_rects(body, rects, out):
    """Paint the faces that own a rectangle of the atlas, and look at them.

    The scrap is named by the patch of the atlas it owns, and the patch
    is found by clicking on it -- which cannot be done from the running
    app, because the scrap is turned away from the camera and the ray goes
    straight through it.  It can be done here, so the rectangle is drawn
    on the model and looked at before anything is deleted by it.  A
    rectangle that also covers the cheek is a rectangle that must not be
    used, and only the picture says which is which.
    """
    import os

    boxes = []
    for raw in rects:
        values = [float(value) for value in raw.split(",")]
        boxes.append((values[0], values[1], values[2], values[3]))

    uv_layer = body.data.uv_layers.active
    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.62, 0.64, 0.68, 1.0)))
    body.data.materials.append(flat_material("scrap", (0.95, 0.05, 0.55, 1.0)))

    hit = 0
    cloud = []
    for face in body.data.polygons:
        us = [uv_layer.data[loop_index].uv.x for loop_index in face.loop_indices]
        vs = [uv_layer.data[loop_index].uv.y for loop_index in face.loop_indices]
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        inside = any(u0 <= u <= u1 and v0 <= v <= v1
                     for u0, v0, u1, v1 in boxes)
        face.material_index = 1 if inside else 0
        if inside:
            hit += 1
            cloud.append(list(face.center))

    print("YXZ_RECT " + json.dumps({
        "rects": boxes,
        "faces": hit,
        "xyzLow": [round(min(c[i] for c in cloud), 4) for i in range(3)] if cloud else None,
        "xyzHigh": [round(max(c[i] for c in cloud), 4) for i in range(3)] if cloud else None,
    }))

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_RECT_RENDER " + out)


def fill_holes(body, out):
    """Close the tears in the shell, and look at what was closed.

    The bright flat panel on the cheek is not a sheet lying on the face.
    A ray fired at it goes straight through the head and comes out at the
    back, which only happens where there is no surface at all: the visor
    is torn open there, and what shows through the tear is the white
    lining of the helmet behind it, lit and edge on.  That is why it
    reads as a piece of paper stuck to the face -- it is a hole with the
    inside of the character showing through it.

    So the tear is closed rather than the panel removed.  Only tears whose
    rim lies in front of the face are closed; the model is full of real
    openings -- the mouth, the ear cups, the gap between the arm and the
    body -- and filling every boundary in the mesh would seal the
    character inside itself.
    """
    import os

    bm = bmesh.new()
    bm.from_mesh(body.data)

    boundary = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    print("YXZ_BOUNDARY total=%d" % len(boundary))

    chosen = []
    for edge in boundary:
        centre = (edge.verts[0].co + edge.verts[1].co) / 2.0
        if not (FRONT[0] * 0.10 <= centre.x <= FRONT[0] * 0.32):
            continue
        if not (-0.26 <= centre.y <= 0.06):
            continue
        if not (-0.06 <= centre.z <= 0.22):
            continue
        chosen.append(edge)
    print("YXZ_BOUNDARY_CHOSEN %d" % len(chosen))

    for edge in chosen:
        edge.select = True
    if chosen:
        bmesh.ops.holes_fill(bm, edges=chosen, sides=0)
    for face in bm.faces:
        face.select = False
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()

    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.62, 0.64, 0.68, 1.0)))

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_FILL_RENDER " + out)


def plain_render(body, out, cull=False):
    """The model as it is, optionally with back faces thrown away.

    Two pictures of the same mesh, one culled and one not, answer a
    question no amount of picking can: is the bright panel on the cheek
    a surface facing the camera, or the inside of one facing away?  If it
    is gone from the culled picture it was never facing us, and no ray
    cast will ever have found it.
    """
    import os

    body.data.materials.clear()
    material = flat_material("shell", (0.62, 0.64, 0.68, 1.0))
    material.use_backface_culling = cull
    body.data.materials.append(material)

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_PLAIN_RENDER cull=%s %s" % (cull, out))


def report_alpha():
    """How much of the base colour atlas is not actually opaque.

    The silhouette outline is drawn from the alpha of the beauty pass: a
    pixel the character does not cover is a pixel the ink goes into, and
    a pixel it covers only halfway is treated as not covered at all.
    That is right for a character with a soft edge and wrong for one whose
    texture happens to carry a partly transparent alpha channel, because
    a leg that is 40% opaque in the atlas is 40% opaque on screen and the
    page behind the canvas shows through it.
    """
    for image in bpy.data.images:
        if not (image.name.startswith("Color")
                or "base_color" in image.name.lower()):
            continue
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        width, height = image.size
        alpha = pixels.reshape(height, width, 4)[..., 3]
        print("YXZ_ALPHA " + json.dumps({
            "image": image.name,
            "size": [width, height],
            "min": round(float(alpha.min()), 4),
            "mean": round(float(alpha.mean()), 4),
            "below25": round(float((alpha < 0.25).mean()), 4),
            "below50": round(float((alpha < 0.50).mean()), 4),
            "below90": round(float((alpha < 0.90).mean()), 4),
            "opaque": round(float((alpha > 0.99).mean()), 4),
        }))


def main() -> None:
    source = value_after("--glb")
    out = value_after("--out", "docs/yxz-diag/flaps.png")
    flipped = "--flip" in sys.argv
    front = value_after("--front")
    if front:
        parts = front.split(",")
        FRONT[0] = float(parts[0])
        FRONT[1] = float(parts[1])
    x_range = (float(value_after("--x0", DEFAULT_X[0])),
               float(value_after("--x1", DEFAULT_X[1])))
    y_range = (float(value_after("--y0", DEFAULT_Y[0])),
               float(value_after("--y1", DEFAULT_Y[1])))
    z_range = (float(value_after("--z0", DEFAULT_Z[0])),
               float(value_after("--z1", DEFAULT_Z[1])))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    corners = [body.matrix_world @ Vector(corner) for corner in body.bound_box]
    print("YXZ_BODY_BOX " + json.dumps({
        "low": [round(min(c[i] for c in corners), 4) for i in range(3)],
        "high": [round(max(c[i] for c in corners), 4) for i in range(3)],
    }))

    # A pixel is "x,y"; `--front x,y` is a direction and not a pixel, so
    # the argument it was given as is skipped by name.
    skip = value_after("--front")
    picks = [a for a in sys.argv[1:]
             if "," in a and a[0].isdigit() and a != skip]
    if picks:
        if "--where" in sys.argv:
            project_points(picks)
        else:
            pick_uv(body, picks)
        return

    rects = [a[len("rect="):] for a in sys.argv[1:] if a.startswith("rect=")]
    if rects:
        show_rects(body, rects, out)
        return
    if "--alpha" in sys.argv:
        report_alpha()
        return
    if "--fill" in sys.argv:
        fill_holes(body, out)
        return
    if "--plain" in sys.argv:
        plain_render(body, out, cull="--cull" in sys.argv)
        return

    bm = bmesh.new()
    bm.from_mesh(body.data)
    uv_layer = bm.loops.layers.uv.active
    flaps = find_flaps(bm, x_range, y_range, z_range, flipped)
    print("YXZ_FLAPS " + json.dumps(report(flaps, uv_layer), sort_keys=True))

    body.data.materials.clear()
    body.data.materials.append(flat_material("shell", (0.62, 0.64, 0.68, 1.0)))
    body.data.materials.append(flat_material("flap", (0.95, 0.05, 0.55, 1.0)))
    marked = set(flaps)
    for face in bm.faces:
        face.material_index = 1 if face in marked else 0
    bm.to_mesh(body.data)
    bm.free()

    setup_world()
    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    import os
    scene.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("YXZ_FLAP_RENDER " + out)


if __name__ == "__main__":
    main()
