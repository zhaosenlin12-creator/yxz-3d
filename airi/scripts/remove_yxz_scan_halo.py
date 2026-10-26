"""Take the scan's own halo off the character's head.

The scan did record a halo, but only two arcs of it: the parts of the
ring that were far enough from the head to be reconstructed, and the
top of the ring was not, so what came back is a hoop with a bite taken
out of it.  Those two arcs sit above the crown of the helmet, and they
were the only thing in the file that did.

The character wears a halo now -- a ring of its own, built with its own
light -- and the scan's arcs sit inside it and cross it, so on screen
there are two halos: a clean blue ellipse with a broken teal crescent
lying through it.  That reads as a mistake, and it is the last thing
between the scan and a clean character.

The arcs are found by geometry, not by colour.  A shell is taken away
when the whole of it is above the crown of the helmet and it is out at
the radius the halo ring sits at.  The crown is the constraint: nothing
that belongs to the body is above it except the raised hand, and the
hand is well below the line -- it is beside the head, not over it.

The line has to be low enough to catch the arcs in full.  The ring is
tilted, so the arc that came back hangs down the sides of the helmet:
it starts at the crown and reaches down to z = 0.306, well below the
crown itself at z = 0.387.  With the line at 0.405 the arc was cut in
half -- the top of it went, the three torn shards that stand proud of
the helmet stayed, and the helmet was left wearing them.  Every shell
of the helmet itself starts below z = 0.30, so the line can sit at
0.30 and still not touch the head.

Usage:
  blender -b -P scripts/remove_yxz_scan_halo.py -- \
    --source <glb> --output <glb> [--min-z 0.30] [--min-radius 0.08]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh


def value_after(name: str, default=None):
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


def bounds(group):
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for face in group:
        for vertex in face.verts:
            for axis in range(3):
                value = vertex.co[axis]
                if value < lo[axis]:
                    lo[axis] = value
                if value > hi[axis]:
                    hi[axis] = value
    return lo, hi


def remove_scan_halo(mesh, min_z: float, min_radius: float):
    """Take away every shell that floats above the crown of the helmet."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    groups = shells(bm)
    body = max(groups, key=len)

    doomed = []
    taken = []
    for number, group in enumerate(groups):
        if group is body:
            continue
        lo, hi = bounds(group)
        # The whole shell has to be over the crown.  A shell that reaches
        # down into the helmet is part of the helmet, whatever colour it
        # is, and taking it would put a hole in the head.
        if lo[2] <= min_z:
            continue
        # And it has to be out at the radius the halo ring sits at, so a
        # stray triangle over the crown is left where it is.
        radius = max(
            (vertex.co[0] ** 2 + vertex.co[1] ** 2) ** 0.5
            for face in group
            for vertex in face.verts
        )
        if radius < min_radius:
            continue
        doomed.extend(group)
        taken.append({
            "shell": number,
            "faces": len(group),
            "zMin": round(lo[2], 4),
            "zMax": round(hi[2], 4),
            "radius": round(radius, 4),
        })

    if not doomed:
        bm.free()
        return {"removedFaces": 0, "removedShells": 0, "shells": []}

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
    min_z = float(value_after("--min-z", 0.30))
    min_radius = float(value_after("--min-radius", 0.08))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    report = remove_scan_halo(body.data, min_z, min_radius)
    report["minZ"] = min_z
    print("YXZ_SCAN_HALO " + json.dumps(report))
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")


if __name__ == "__main__":
    main()
