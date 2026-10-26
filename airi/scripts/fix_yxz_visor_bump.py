"""Take the scan's leftover eye-bump off the visor.

The scan recorded the character's face twice over: once as a head with
a painted eye on it, and once as a dark visor panel laid over the top
of that head.  The panel is in front, and it hides the face, but the
eye underneath is a bump, and where the bump rises past the panel it
comes through.

What comes through is a crescent of the painted eye -- the pale blue
of the eye and the white of its highlight -- and on screen it is a bar
of light across the middle of the visor with a torn edge.  It reads as
a scratch, or as a reflection that has broken, and either way it is
the one thing on the character that looks like a mistake.

So the bump is put back where it belongs.  The vertices in the middle
of the bump are moved back into the head, by less and less as they
approach the edge of it, so the surface stays closed and the panel
always wins.  And the eye that was painted on the bump is painted over
with the visor's own blue, so that even a thread of it showing is the
colour it was hiding.

The eyes the character is seen with are the rig's own eyes, which are
separate pieces of geometry in front of the panel; nothing here
touches them.

Usage:
  blender -b -P scripts/fix_yxz_visor_bump.py -- \
    --source <glb> --output <glb>
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

import bpy
import bmesh
import numpy as np


# How far the middle of the bump is pushed back into the head.  The
# bump stands about thirteen millimetres proud of the panel, so this
# has to be more than that to put it behind.
PUSH_BACK = 0.022

# The visor panel's own blue, which the painted eye is covered with.
VISOR_BLUE = (36, 71, 113)


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def triangle(mask, width, height, a, b, c):
    min_x = max(0, int(min(a[0], b[0], c[0])))
    max_x = min(width - 1, int(max(a[0], b[0], c[0])))
    min_y = max(0, int(min(a[1], b[1], c[1])))
    max_y = min(height - 1, int(max(a[1], b[1], c[1])))
    if min_x > max_x or min_y > max_y:
        return
    ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
    px = xs + 0.5
    py = ys + 0.5
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-9:
        return
    w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
    w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -0.002) & (w1 >= -0.002) & (w2 >= -0.002)
    mask[min_y:max_y + 1, min_x:max_x + 1] |= inside


def main() -> None:
    source = value_after("--source")
    output = value_after("--output")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    colour = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            colour = image
            break
    width, height = colour.size
    pixels = np.empty(height * width * 4, dtype=np.float32)
    colour.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    top_down = pixels[::-1]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    def atlas_colour(face):
        us = [loop[uv_layer].uv.x for loop in face.loops]
        vs = [loop[uv_layer].uv.y for loop in face.loops]
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        x = min(width - 1, max(0, int(u * width)))
        y = min(height - 1, max(0, int((1.0 - v) * height)))
        return top_down[y, x, :3]

    # The painted eye: a pale blue patch on the front of the face, with
    # a white highlight in it.  Only the one on the head is of interest;
    # the rig's own eyes are separate geometry and are not touched.
    cyan_faces = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if centre.y > -0.24 or centre.z < 0.02:
            continue
        r, g, b = (float(value) for value in atlas_colour(face))
        if b > 0.70 and g > 0.60 and r < 0.70 and b - r > 0.18:
            cyan_faces.append(face)

    if not cyan_faces:
        print("YXZ_BUMP no painted eye on the face")
        bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")
        return

    # The bump is the one nearest the middle of the face: that is the
    # one the visor panel was laid over.
    face_centre = np.array([0.0, -0.29, 0.133])
    seed = min(
        cyan_faces,
        key=lambda face: float(np.linalg.norm(
            np.array(face.calc_center_median()) - face_centre)),
    )
    # Grow over the faces that touch, so the whole of the painted eye is
    # found and not just the bit nearest the seed.
    painted = []
    seen = {seed}
    queue = deque([seed])
    while queue:
        face = queue.popleft()
        painted.append(face)
        for edge in face.edges:
            for other in edge.link_faces:
                if other in seen or other not in cyan_faces:
                    continue
                seen.add(other)
                queue.append(other)

    # The whole of the eye, including the white highlight in it, which
    # is the brightest thing on the face and the first thing to show.
    us = []
    vs = []
    for face in painted:
        for loop in face.loops:
            us.append(loop[uv_layer].uv.x)
            vs.append(loop[uv_layer].uv.y)
    u0, u1 = min(us) - 0.004, max(us) + 0.004
    v0, v1 = min(vs) - 0.004, max(vs) + 0.004
    for face in bm.faces:
        if face in painted:
            continue
        centre = face.calc_center_median()
        if float(np.linalg.norm(np.array(centre) - face_centre)) > 0.07:
            continue
        fu = [loop[uv_layer].uv.x for loop in face.loops]
        fv = [loop[uv_layer].uv.y for loop in face.loops]
        u = sum(fu) / len(fu)
        v = sum(fv) / len(fv)
        if u0 <= u <= u1 and v0 <= v <= v1:
            painted.append(face)

    painted_set = set(painted)
    # The texels the painted eye owns.
    texels = np.zeros((height, width), dtype=bool)
    for face in painted:
        points = [
            (loop[uv_layer].uv.x * width, (1.0 - loop[uv_layer].uv.y) * height)
            for loop in face.loops
        ]
        for index in range(1, len(points) - 1):
            triangle(texels, width, height, points[0], points[index], points[index + 1])

    # How far each vertex of the bump is from the edge of it, measured in
    # steps across the bump's own faces, so the push can fade out at the
    # edge and leave the surface closed.
    adjacency = {}
    for face in painted:
        verts = [vert for vert in face.verts]
        for index, vert in enumerate(verts):
            other = verts[(index + 1) % len(verts)]
            adjacency.setdefault(vert, set()).add(other)
            adjacency.setdefault(other, set()).add(vert)
    # A vertex on the rim of the bump is one that also belongs to a face
    # that is not part of the bump.
    edge = set()
    for face in bm.faces:
        if face in painted_set:
            continue
        for vert in face.verts:
            if vert in adjacency:
                edge.add(vert)
    interior = [vert for vert in adjacency if vert not in edge]
    depth = {vert: 0 for vert in edge}
    queue = deque(edge)
    while queue:
        vert = queue.popleft()
        for other in adjacency.get(vert, ()):
            if other not in depth:
                depth[other] = depth[vert] + 1
                queue.append(other)
    for vert in interior:
        steps = min(1.0, depth.get(vert, 0) / 5.0)
        vert.co -= vert.normal * (PUSH_BACK * steps)

    # And the paint on it is painted over with the visor's own blue.
    flat = pixels.reshape(-1, 4)
    ys, xs = np.nonzero(texels)
    rows = height - 1 - ys
    index = rows * width + xs
    flat[index, 0] = VISOR_BLUE[0] / 255.0
    flat[index, 1] = VISOR_BLUE[1] / 255.0
    flat[index, 2] = VISOR_BLUE[2] / 255.0
    colour.pixels.foreach_set(flat.ravel())
    try:
        colour.pack()
    except RuntimeError:
        pass

    bm.to_mesh(body.data)
    bm.free()
    body.data.update()

    report = {
        "faces": len(painted),
        "interiorVerts": len(interior),
        "texels": int(texels.sum()),
        "pushBack": PUSH_BACK,
    }
    print("YXZ_BUMP " + json.dumps(report))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


main()
