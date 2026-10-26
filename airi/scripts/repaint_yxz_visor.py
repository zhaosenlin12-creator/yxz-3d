"""Paint the visor as one screen.

The visor is the last thing on this character that still reads as a
shattered scan.  It is one dark screen in the design, and in the scan it
is two: the piece of the screen on one side of the face and the piece on
the other are separate pieces of the scan, and each one samples its own
part of the texture atlas.  The result on screen is a visor with two
different colours and a ragged join straight down the middle of the
face -- the join is the edge of the scan, not anything the design has.

So the screen is repainted rather than repaired:

   selection   The screen is the part of the head that is set into the
               helmet, which in the scan is a sheet lying *inside* the
               shell -- the shell is a radius of about 0.289 from the
               middle of the head and the screen is set back from it.
               Faces that are recessed and that face the front are the
               screen, and the shell around them is left alone.

   projection  The screen is unwrapped onto a flat sheet with a
               cylindrical projection about the head's vertical axis, so
               the picture on it is continuous from one side of the face
               to the other and the join disappears with the rewrapping.

   room        The atlas is a junk drawer of a hundred pieces of the
               scan, so the rectangle the screen is painted into is found
               by measuring which parts of the atlas nothing else is
               using.  Nothing is overwritten.

   paint       The screen is a dark blue with a broad soft sheen across
               its upper left and the thin bright bar the design has
               across the top of it.  The sheen is the studio light
               rather than a reflection in glass, which is what the
               scan's own version of it read as.

Usage:
  blender -b -P scripts/repaint_yxz_visor.py -- \
    --source <glb> --output <glb> [--centre 0.038,-0.001,0.094] \
    [--recessed 0.272] [--rect 1024] [--dry]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def find_room(bm, uv_layer, size, width, height):
    """A square of the atlas that nothing else is using."""
    used = np.zeros((height, width), dtype=bool)
    for face in bm.faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            x = int(uv.x * width)
            y = int((1.0 - uv.y) * height)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    xx = x + dx
                    yy = y + dy
                    if 0 <= xx < width and 0 <= yy < height:
                        used[yy, xx] = True
    # A coarse occupancy is enough: a pixel is marked if any of the nine
    # around it is used, so the rectangle keeps a margin.
    thick = used.copy()
    for _ in range(2):
        thick[1:, :] |= thick[:-1, :]
        thick[:-1, :] |= thick[1:, :]
        thick[:, 1:] |= thick[:, :-1]
        thick[:, :-1] |= thick[:, 1:]
    free = ~thick
    integral = free.cumsum(axis=0).cumsum(axis=1)
    for y in range(0, height - size, 8):
        for x in range(0, width - size, 8):
            total = integral[y + size, x + size]
            if y > 0:
                total -= integral[y - 1, x + size]
            if x > 0:
                total -= integral[y + size, x - 1]
            if y > 0 and x > 0:
                total += integral[y - 1, x - 1]
            if total == size * size:
                return x, y, size, size
    return None


def islands(bm):
    """Which piece of the scan each face belongs to."""
    bm.faces.ensure_lookup_table()
    owner = {}
    unvisited = set(bm.faces)
    number = 0
    while unvisited:
        seed = unvisited.pop()
        owner[seed.index] = number
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    owner[other.index] = number
                    frontier.append(other)
        number += 1
    return owner


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    recessed = float(value_after("--recessed", "0.272"))
    front = float(value_after("--front", "0.10"))
    low = float(value_after("--low", "0.005"))
    high = float(value_after("--high", "0.275"))
    reach = float(value_after("--reach", "1.02"))
    pieces = int(value_after("--pieces", "2"))
    rect = int(value_after("--rect", "1024"))
    dry = "--dry" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    image = None
    for candidate in bpy.data.images:
        if candidate.name.startswith("Color"):
            image = candidate
            break
    if image is None:
        raise SystemExit("no colour texture found")
    width = image.size[0]
    height = image.size[1]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    # The screen: the recessed faces that face the front of the head.
    screen = []
    for face in bm.faces:
        middle = face.calc_center_median()
        radius = (middle - centre).length
        if radius >= recessed:
            continue
        if middle.x < front:
            continue
        if middle.z < low or middle.z > high:
            continue
        angle = math.atan2(middle.y - centre.y, middle.x - centre.x)
        if abs(angle) > reach:
            continue
        screen.append(face)

    # The projection: a cylinder about the head's vertical axis.
    # Which pieces of the scan the screen is made of, so the selection can
    # be checked against what is known about the pieces.
    owner = islands(bm)
    by_island = {}
    for face in screen:
        key = owner.get(face.index, -1)
        by_island[key] = by_island.get(key, 0) + 1
    ranked = sorted(by_island.items(), key=lambda item: -item[1])
    print("YXZ_SCREEN_PIECES " + json.dumps(ranked[:8]))
    # Only the pieces that *are* the screen are repainted.  The rest of
    # what is inside the helmet's opening is the face around it -- the
    # muzzle the mouth is drawn on, and the rim of the opening -- and
    # painting any of that turns the character's face blue.
    keep = {number for number, _ in ranked[:pieces]}
    screen = [face for face in screen if owner.get(face.index, -1) in keep]
    if len(screen) < 50:
        raise SystemExit("the screen selection is too small to be right")
    angles = []
    heights = []
    for face in screen:
        for vertex in face.verts:
            co = vertex.co
            angles.append(math.atan2(co.y - centre.y, co.x - centre.x))
            heights.append(co.z)
    a0 = min(angles)
    a1 = max(angles)
    b0 = min(heights)
    b1 = max(heights)
    print("YXZ_SCREEN_KEPT %d faces  angle %.3f..%.3f  z %.4f..%.4f"
          % (len(screen), a0, a1, b0, b1))

    room = find_room(bm, uv_layer, rect, width, height)
    if room is None:
        raise SystemExit("no free rectangle of %d in the atlas" % rect)
    rx, ry, rw, rh = room
    print("YXZ_SCREEN_ROOM %d %d %d %d" % (rx, ry, rw, rh))

    u0 = (rx + 0.02 * rw) / width
    u1 = (rx + 0.98 * rw) / width
    # The atlas is written top down and read bottom up, so the top of the
    # screen is the top of the rectangle.
    v0 = (ry + 0.02 * rh) / height
    v1 = (ry + 0.98 * rh) / height

    moved = 0
    for face in screen:
        for loop in face.loops:
            co = loop.vert.co
            angle = math.atan2(co.y - centre.y, co.x - centre.x)
            height_v = co.z
            u = u0 + (angle - a0) / max(1e-6, a1 - a0) * (u1 - u0)
            v = v1 - (height_v - b0) / max(1e-6, b1 - b0) * (v1 - v0)
            loop[uv_layer].uv = (u, v)
            moved += 1
    print("YXZ_SCREEN_UVS %d" % moved)

    if dry:
        print("YXZ_SCREEN_DRY")
        return

    # The paint.
    #
    # A dark blue screen with a broad soft sheen across the upper left
    # and the thin bright bar the design has across the top of it.  The
    # sheen is soft enough that it reads as the studio light on a matte
    # screen rather than as a reflection in glass.
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)

    top = int(ry + 0.02 * rh)
    bottom = int(ry + 0.98 * rh)
    left = int(rx + 0.02 * rw)
    right = int(rx + 0.98 * rw)
    span_y = max(1, bottom - top)
    span_x = max(1, right - left)

    yy = (np.arange(span_y) / span_y)[:, None]
    xx = (np.arange(span_x) / span_x)[None, :]
    # The base of the screen: a deep blue that is a little darker at the
    # bottom, where the helmet shades it.
    base = np.zeros((span_y, span_x, 4), dtype=np.float32)
    base[..., 0] = 0.060 + 0.030 * (1.0 - yy)
    base[..., 1] = 0.100 + 0.050 * (1.0 - yy)
    base[..., 2] = 0.225 + 0.080 * (1.0 - yy)
    base[..., 3] = 1.0
    # The sheen: a broad soft brightening across the upper left.
    sheen = np.clip(1.0 - np.sqrt(((xx - 0.26) / 0.52) ** 2
                                  + ((yy - 0.20) / 0.62) ** 2), 0.0, 1.0)
    sheen = sheen ** 1.7 * 0.40
    base[..., 0] += sheen * 0.22
    base[..., 1] += sheen * 0.26
    base[..., 2] += sheen * 0.30
    # The bright bar across the top of the screen.
    bar = np.exp(-((yy - 0.145) / 0.016) ** 2)
    inside = ((xx > 0.42) & (xx < 0.60)).astype(np.float32)
    base[..., 0] += bar * inside * 0.72
    base[..., 1] += bar * inside * 0.78
    base[..., 2] += bar * inside * 0.80
    # The rim of the screen, a shade darker all the way round, so the
    # edge of it has somewhere to sit.
    edge = np.minimum(np.minimum(xx, 1.0 - xx), np.minimum(yy, 1.0 - yy))
    rim = np.clip(1.0 - edge / 0.045, 0.0, 1.0)
    base[..., :3] *= (1.0 - 0.30 * rim)[:, :, None]
    pixels[top:bottom, left:right] = base
    image.pixels.foreach_set(pixels.reshape(-1))

    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    # The image has to be written out and read back in before the model is
    # exported, because a texture that came in inside the glb is packed
    # and the exporter keeps the packed copy -- the one that was read, not
    # the one that was edited.  Reading the edited file back in as an
    # ordinary file-backed image is what makes the exporter pick it up.
    #
    # It is written as an eight bit jpeg rather than a float png: the
    # scan's atlas is eight bit and has no transparency, the model's own
    # vrm carries the atlas as a jpeg, and a png of the whole four
    # thousand by four thousand atlas is several times the size of the
    # model it belongs to.
    atlas = output.with_suffix(".jpg")
    painted = bpy.data.images.new(
        "Color_painted", width, height, alpha=True, float_buffer=False)
    painted.pixels.foreach_set(pixels.reshape(-1))
    painted.filepath_raw = str(atlas)
    painted.file_format = 'JPEG'
    painted.save()
    painted.source = 'FILE'
    painted.filepath = str(atlas)
    painted.reload()
    painted.name = image.name
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image == image:
                node.image = painted

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format='GLB',
        export_apply=False,
        export_yup=True,
        export_texcoords=True,
        export_normals=True,
        export_materials='EXPORT',
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=True,
    )
    print("YXZ_SCREEN_PAINTED " + str(output))


if __name__ == "__main__":
    main()

