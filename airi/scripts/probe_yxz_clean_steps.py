"""Count the connected islands after each step of the cleaning pass.

The clean script welds the scan, dissolves the degenerate faces the weld
creates and then makes the normals consistent.  One of those three is
shattering the character: the source mesh is a couple of hundred pieces,
and after the clean it is twelve thousand, nine tenths of which are
three-triangle scraps.  Those scraps are what the viewer reads as a
broken, shattered surface.

This runs the same three operations one at a time and reports the island
count after each, so the guilty step is named rather than guessed.

Usage:
  blender -b -P scripts/probe_yxz_clean_steps.py -- \
    --source <glb> [--threshold 0.0015]
"""

from __future__ import annotations

import json
import sys

import bpy
import bmesh


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def island_count(mesh) -> tuple[int, list[int]]:
    """Connected components, and how many faces each one has."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    unseen = set(bm.faces)
    sizes = []
    while unseen:
        seed = unseen.pop()
        stack = [seed]
        count = 0
        while stack:
            face = stack.pop()
            count += 1
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour in unseen:
                        unseen.discard(neighbour)
                        stack.append(neighbour)
        sizes.append(count)
    bm.free()
    sizes.sort()
    tiny = sum(1 for size in sizes if size <= 4)
    return len(sizes), [len(sizes), tiny]


def report(tag: str, mesh) -> None:
    total, stats = island_count(mesh)
    print("YXZ_STEP %s verts=%d faces=%d islands=%d tiny=%d"
          % (tag, len(mesh.vertices), len(mesh.polygons), total, stats[1]))


def flush(body) -> None:
    """Leave edit mode so the edit cage is written back to the mesh.

    Every edit-mode operator works on the cage, and the cage is only
    written into `mesh` when edit mode ends.  Measuring the mesh while
    still in edit mode therefore reports the state from before the
    operator ran, which is how this probe first came to say that the
    clean changed nothing.
    """
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")


def main() -> None:
    source = value_after("--source") or value_after("--glb")
    threshold = float(value_after("--threshold", 0.0015))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    report("import", body.data)

    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    flush(body)
    report("weld", body.data)

    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.dissolve_degenerate(threshold=1e-6)
    flush(body)
    report("dissolve", body.data)

    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    flush(body)
    report("consistent", body.data)

    bpy.ops.object.mode_set(mode="OBJECT")
    print("YXZ_STEPS " + json.dumps({"threshold": threshold}))


if __name__ == "__main__":
    main()
