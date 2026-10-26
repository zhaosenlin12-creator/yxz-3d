"""Turn the patches of the shell that face the wrong way back around.

The character is a scan, and a scan is stitched from many pieces.  Where
two pieces overlapped, one of them was often kept inside out.  A face
turned away from the camera is not drawn at all, so the piece stops
existing on screen while it is still there in the file: the boot reads as
an open cage, the shin as a torn strip, and the whole figure reads as
shattered rather than as a solid toy.

Blender's own pass for this cannot be used here.  It decides which way is
outside by firing a ray along each normal and seeing whether it comes back
out, and the shell has tears in it, so the ray leaves through a hole,
never comes back, and the patch is judged to be facing out already.  That
is the same leak that lets a hole look like a hole and a folded surface
look like a hole: both are places the mesh is not closed.

So the camera is the judge instead.  A ray is cast the way the page casts
it, and a face that is looked straight at and refused is wrong by
definition.  Those faces are then grown across shared edges to cover the
whole piece they belong to, because the rays land on a grid and only mark
the side of a patch that happens to face front.  Growth stops at a face
the camera was already able to draw, which is the edge of the patch.

Nothing here moves a vertex.  The pieces are already in the right place --
they are wound the wrong way round, so reversing them makes a surface that
was always there finally show up.  The result is measured rather than
assumed: the same rays are cast before and after, and a pass that does not
take refused surface away has guessed wrong.

Usage:
  blender -b -P scripts/fix_yxz_winding.py -- \
    --source <glb> --output <glb> [--step 0.004] [--hops 6]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict, deque

import bmesh
import bpy
import numpy as np
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def bounds(objects):
    low = Vector((1e9, 1e9, 1e9))
    high = Vector((-1e9, -1e9, -1e9))
    for obj in objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], world[axis])
                high[axis] = max(high[axis], world[axis])
    return low, high


def cast_camera(objects, step):
    """Ask the scene what the camera would be shown, face by face."""
    low, high = bounds(objects)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eye = Vector((high.x + 2.0, 0.0, 0.0))
    direction = Vector((-1.0, 0.0, 0.0))
    seen = {}
    for z in np.arange(low.z, high.z + step, step):
        for y in np.arange(low.y, high.y + step, step):
            origin = Vector((eye.x, float(y), float(z)))
            result = scene.ray_cast(depsgraph, origin, direction)
            if not result[0]:
                continue
            key = (result[4].name, result[3])
            facing = result[2].dot(direction) < 0.0
            # One face can be landed on from several directions, so the
            # first answer is kept and the measurement stays repeatable.
            seen.setdefault(key, facing)
    return seen


def tally(seen):
    drawn = sum(1 for facing in seen.values() if facing)
    return drawn, len(seen) - drawn


def flip_patch(obj, refused, drawn, hops):
    """Grow the refused faces out to the edge of the piece they sit in."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangles = list(mesh.loop_triangles)

    triangles_of_polygon = defaultdict(list)
    for triangle in triangles:
        triangles_of_polygon[triangle.polygon_index].append(triangle.index)

    by_edge = defaultdict(list)
    for triangle in triangles:
        keys = sorted(triangle.vertices)
        for corner in range(3):
            pair = (keys[corner], keys[(corner + 1) % 3])
            by_edge[pair].append(triangle.index)

    chosen = set()
    for polygon in refused:
        chosen.update(triangles_of_polygon.get(polygon, ()))

    queue = deque((triangle, 0) for triangle in sorted(chosen))
    while queue:
        triangle, depth = queue.popleft()
        if depth >= hops:
            continue
        keys = sorted(triangles[triangle].vertices)
        for corner in range(3):
            pair = (keys[corner], keys[(corner + 1) % 3])
            for neighbour in by_edge.get(pair, ()):
                if neighbour in chosen:
                    continue
                # The camera was able to draw this one, so it is the edge of
                # the patch rather than part of it.
                if triangles[neighbour].polygon_index in drawn:
                    continue
                chosen.add(neighbour)
                queue.append((neighbour, depth + 1))

    polygons = {triangles[triangle].polygon_index for triangle in chosen}
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    for face in bm.faces:
        if face.index in polygons:
            face.normal_flip()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(polygons)


def main():
    source = value_after("--source")
    output = value_after("--output")
    step = float(value_after("--step", "0.004"))
    hops = int(value_after("--hops", "6"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]

    seen = cast_camera(meshes, step)
    drawn_before, refused_before = tally(seen)

    refused = defaultdict(set)
    drawn = defaultdict(set)
    for (name, polygon), facing in seen.items():
        target = drawn if facing else refused
        target[name].add(polygon)

    flipped = 0
    for obj in meshes:
        count = flip_patch(obj, refused.get(obj.name, set()),
                           drawn.get(obj.name, set()), hops)
        print("PATCH " + json.dumps({"mesh": obj.name, "polygons": count}))
        flipped += count

    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()
    drawn_after, refused_after = tally(cast_camera(meshes, step))
    print("WINDING " + json.dumps({
        "refusedBefore": refused_before, "refusedAfter": refused_after,
        "drawnBefore": drawn_before, "drawnAfter": drawn_after,
        "flippedPolygons": flipped, "hops": hops}))
    bpy.ops.export_scene.gltf(filepath=output, export_format="GLB")


main()
