"""Take the loose pieces of the scan off the character's face.

The scan folded pieces of the surface over themselves, and a few of those
folds ended up lying on the face rather than around it.  One of them is a
flat sheet resting on the cheek under the eye, to the side of the smile:
on screen it is a ragged white tongue that runs out past the edge of the
face, and it is the last thing on the model that reads as broken.

Finding it is the work.  Colour does not identify it, because it is
painted the same white as the rest of the face.  Position does not
identify it either, because it lies *on* the face rather than beside it,
and a ray fired into the head from it hits the face almost at once --
which is how an earlier version of this script found it, and also how it
ate the entire chin along with it.

What does identify it is the atlas.  The scan's own packing gives every
piece of the model its own patch of the texture, and a scrap that is
lying loose has a patch to itself, well away from the patch its
neighbours use.  So the scrap is named by the rectangle of the atlas it
owns, and the rectangle is checked against a rendering of the model
before it is used, because a rectangle that covers part of the cheek is
not a rectangle that can be deleted.

Usage:
  blender -b -P scripts/remove_yxz_debris.py -- \
    --source <glb> --output <glb>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np


# The pieces of the scan that lie on the face, as rectangles of the base
# colour atlas.  Each one was picked off a rendering of the model with the
# region it owns picked out in colour, so the rectangle is known to cover
# the scrap and nothing else.
#
# The order matters: the first is a flat sheet of the helmet's own trim,
# folded back on itself and left resting on the cheek under the eye, to
# the side of the smile.  It runs out past the edge of the face, so on
# screen it is a ragged white tongue in front of the cheek.
ISLANDS = [
    (0.898, 0.560, 0.948, 0.645),
]

# A scrap, not a face.  Anything larger is refused rather than removed.
MAX_FACES = 2000


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def faces_in_islands(bm, uv_layer, islands):
    """The faces whose own patch of the atlas is one of the islands."""
    picked = []
    for face in bm.faces:
        cu = sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops)
        cv = sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops)
        for u0, v0, u1, v1 in islands:
            if u0 <= cu <= u1 and v0 <= cv <= v1:
                picked.append(face)
                break
    return picked


def remove_debris(mesh, islands=None, max_faces=MAX_FACES):
    """Delete the loose sheets, and say exactly what was taken."""
    if mesh.uv_layers.active is None:
        return {"skipped": "no uv layer"}

    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.active

    picked = faces_in_islands(bm, uv_layer, islands or ISLANDS)
    if not picked:
        bm.free()
        return {"skipped": "no loose sheet on the face"}
    if len(picked) > max_faces:
        bm.free()
        return {"refused": "%d faces is not a scrap" % len(picked)}

    cloud = np.array([list(face.calc_center_median()) for face in picked])
    bmesh.ops.delete(bm, geom=list(picked), context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    return {
        "removedFaces": len(picked),
        "low": [round(float(value), 4) for value in cloud.min(axis=0)],
        "high": [round(float(value), 4) for value in cloud.max(axis=0)],
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
    report = remove_debris(body.data)
    print("YXZ_DEBRIS " + json.dumps(report))


if __name__ == "__main__":
    main()
