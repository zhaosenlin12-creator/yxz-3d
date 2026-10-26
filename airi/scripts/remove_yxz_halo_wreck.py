"""Take the scan's broken halo off the character's head.

The character wears a halo, and the scan did not record one.  What came
back instead was a wide crescent of dark blue, broken into a couple of
hundred pieces, lying in a band across the crown of the head, with a
few dozen of the pieces shattered into loose triangles.

The halo is built properly now -- as a ring of its own, with a light of
its own -- but the wreck of the old one was never taken away, and it is
the wreck that is on screen: a dark band across the top of the head with
a confetti of pale triangles over it.  It is the single worst thing
about the character, and it is what makes the head read as shattered
rather than as a helmet.

The wreck is found by the patch of the atlas it owns.  The scan's
packing gives every piece of the model a rectangle of the texture to
itself, so a piece of the wreck is a piece of geometry whose own
rectangle sits in the wreck's part of the texture.  A piece is taken
away whole, by its own rectangle, so nothing that merely shares the
texture with the wreck is disturbed.

The wreck is not simply "the dark band", either: the same band of
texture holds the helmet's own trim, and the pieces of the wreck that
are pale -- the confetti -- are pale because they are the *inside* of
the band, lit from behind.  The rectangles below were read off a
rendering of the model with each shell picked out in a colour of its
own, so each one is known to cover a piece of the wreck and nothing
else.

Usage:
  blender -b -P scripts/remove_yxz_halo_wreck.py -- \
    --source <glb> --output <glb>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh


# The rectangles of the base colour atlas that the wreck of the halo
# owns.  Each was measured on the model itself.
#
# The first is the wide dark band that crosses the crown.  The second and
# third are the two big crescents the band was cut into.  The fourth is
# the far end of the band, where it passes behind the head.  The fifth
# is the confetti: the pale shattered pieces over the left of the band.
# The last three are the smaller pieces of the band that the join
# picked out on the right.
WRECK = [
    (0.5453, 0.1778, 0.7641, 0.2630),
    (0.1096, 0.4422, 0.1988, 0.5822),
    (0.0518, 0.0022, 0.1314, 0.0635),
    (0.0513, 0.7893, 0.0884, 0.8518),
    (0.5231, 0.0466, 0.5888, 0.1360),
    (0.1529, 0.8139, 0.2608, 0.9106),
    (0.5502, 0.7389, 0.6652, 0.8054),
    (0.0562, 0.7602, 0.1350, 0.8503),
]


# A shell that owns a patch of the texture has a small one.  A shell
# whose faces are spread over the whole texture owns no patch at all --
# it is the kind of shell the scan produced when a piece of the surface
# was stitched on without a place of its own to go, and it must not be
# mistaken for a piece of the wreck just because it covers the wreck's
# patch as well as everything else.
MAX_PATCH_AREA = 0.02


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
    bm.faces.ensure_lookup_table()
    groups = []
    unvisited = set(bm.faces)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        groups.append(group)
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def rect_of(group, uv_layer):
    us = []
    vs = []
    for face in group:
        for loop in face.loops:
            us.append(loop[uv_layer].uv.x)
            vs.append(loop[uv_layer].uv.y)
    return (min(us), min(vs), max(us), max(vs))


def overlap(a, b):
    """How much of the smaller rectangle is covered by the larger."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return shared / min(area_a, area_b)


def remove_wreck(mesh):
    """Take away the shells whose own patch of the atlas is the wreck."""
    if mesh.uv_layers.active is None:
        return {"skipped": "no uv layer"}

    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.active
    groups = shells(bm)
    body = max(groups, key=len)

    doomed = []
    taken = []
    for number, group in enumerate(groups):
        if group is body:
            continue
        rect = rect_of(group, uv_layer)
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        if area > MAX_PATCH_AREA:
            continue
        for patch in WRECK:
            if overlap(rect, patch) >= 0.5:
                doomed.extend(group)
                taken.append({
                    "shell": number,
                    "faces": len(group),
                    "rect": [round(value, 4) for value in rect],
                })
                break

    if not doomed:
        bm.free()
        return {"skipped": "no wreck on the head"}

    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return {
        "removedFaces": len(doomed),
        "removedShells": len(taken),
        "shells": taken[:40],
    }


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    report = remove_wreck(body.data)
    print("YXZ_WRECK " + json.dumps(report))
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")


if __name__ == "__main__":
    main()
