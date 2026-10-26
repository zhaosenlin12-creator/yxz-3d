"""Close the seams of the scan by bridging them.

The shell arrives as a patchwork.  The helmet is a dozen tiles, and
where two tiles meet the surface was *cut* rather than joined: each side
of the seam carries its own vertices, and the two sets are a fraction of
an edge length apart.  So the seam is not an edge with a hole in it --
it is a hairline slot between two surfaces that were never stitched.

Welding does not close it, and the measurement says so: the two sides of
a seam are not close enough to be merged, and a weld wide enough to
reach them swallows a third of the model first.

What does close it is a bridge.  From the middle of every open edge, a
ray is cast along the seam -- perpendicular to the edge, in the plane of
the surface, and pointing away from the surface the edge belongs to --
and the first thing it hits is the other side of the same slot.  The two
edges are then joined by a strip of geometry that spans the slot, which
is a surface again, and the surface no longer has a hole in it.

The strip is given the colour of the tile it grew out of, so it does
not read as a repair.  A ray that does not find the other side is left
alone: that is not a seam but a place where the scan stopped, and the
bottom of the helmet and the inside of the mouth are supposed to be
open.

Usage:
  blender -b -P scripts/bridge_yxz_seams.py -- \
    --source <glb> --output <glb> [--max-gap 0.006] [--head-z 0.18]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def seam_direction(edge):
    """The direction across the seam, in the plane of the surface.

    It is perpendicular to the edge and perpendicular to the surface, and
    it points away from the face the edge belongs to -- which is the
    side the slot is on.
    """
    normal = Vector((0.0, 0.0, 0.0))
    centre = Vector((0.0, 0.0, 0.0))
    count = 0
    for face in edge.link_faces:
        normal += face.normal
        centre += face.calc_center_median()
        count += 1
    if count == 0 or normal.length < 1e-9:
        return None, None
    normal.normalize()
    centre /= count
    along = edge.verts[1].co - edge.verts[0].co
    if along.length < 1e-9:
        return None, None
    along.normalize()
    across = normal.cross(along)
    if across.length < 1e-9:
        return None, None
    across.normalize()
    middle = (edge.verts[0].co + edge.verts[1].co) * 0.5
    # The face's own interior is on one side of the edge; the slot is on
    # the other.
    inward = centre - middle
    inward -= along * inward.dot(along)
    if across.dot(inward) > 0.0:
        across = -across
    return across, normal


def load_atlas():
    """The base colour image as a numpy array of rows."""
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    return None


def atlas_colour(atlas, uv):
    """The colour of the atlas at a place in the texture."""
    if atlas is None or uv is None:
        return None
    height, width = atlas.shape[0], atlas.shape[1]
    x = int(min(max(uv.x, 0.0), 1.0) * (width - 1))
    y = int(min(max(uv.y, 0.0), 1.0) * (height - 1))
    return atlas[y, x][:3]


def main():
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    max_gap = float(value_after("--max-gap", "0.006"))
    head_z = float(value_after("--head-z", "0.18"))
    max_colour = float(value_after("--max-colour-difference", "0.25"))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    # The tree is built before anything is added, so a bridge is never
    # allowed to bridge itself: the ray finds the shell, not the bridges
    # that are already there.
    tree = BVHTree.FromBMesh(bm, epsilon=0.0)
    # The tree's face indices refer to the faces as they were when the
    # tree was built, and adding faces renumbers them, so the original
    # list is kept and the indices are resolved through it.
    original_faces = list(bm.faces)
    atlas = load_atlas()

    open_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    report = {
        "openEdges": len(open_edges),
        "bridged": 0,
        "bridgedHead": 0,
        "reachedNothing": 0,
        "tooWide": 0,
        "noDirection": 0,
        "differentColour": 0,
        "facesBefore": len(bm.faces),
    }

    for edge in open_edges:
        across, normal = seam_direction(edge)
        if across is None:
            report["noDirection"] += 1
            continue
        is_head = max(vertex.co.z for vertex in edge.verts) >= head_z

        corners = []
        far_uv = [None, None]
        near_uv = []
        gaps = []
        far_normals = []
        ok = True
        for index, vertex in enumerate(edge.verts):
            uv = None
            if uv_layer:
                for loop in vertex.link_loops:
                    if loop.edge is edge:
                        uv = loop[uv_layer].uv.copy()
                        break
            near_uv.append(uv)
            origin = vertex.co + normal * 0.0004
            hit, hit_normal, _, distance = tree.ray_cast(origin, across, max_gap)
            if hit is None:
                report["reachedNothing"] += 1
                ok = False
                break
            # The far side of a slot faces the same way the near side
            # does.  A ray that comes back at an angle has found the
            # inside of something else, and bridging to that would draw
            # a sheet across the model.
            if hit_normal.dot(normal) < 0.4:
                report["differentColour"] += 1
                ok = False
                break
            # The strip is carried a little past the far side so that it
            # overlaps it, and the two meet without a line between them.
            far = hit + across * (distance * 0.25)
            corners.append((vertex, far))
            gaps.append(distance)
            far_normals.append(hit_normal)
            # The colour of the far end is read while the tree's own
            # indices are still the ones the tree was built with.
            if uv_layer:
                _, _, face_index, _ = tree.find_nearest(far, max_gap)
                if face_index is not None and face_index < len(original_faces):
                    hit_face = original_faces[face_index]
                    best = None
                    best_distance = 1e18
                    for corner in hit_face.loops:
                        distance = (corner.vert.co - far).length
                        if distance < best_distance:
                            best_distance = distance
                            best = corner
                    if best is not None:
                        far_uv[index] = best[uv_layer].uv.copy()
        if not ok:
            continue

        # The two sides of a slot are the same width apart at both ends
        # of the edge.  If they are not, the ray has found two different
        # things and the strip between them would be a fan.
        if max(gaps) > 0.0 and abs(gaps[0] - gaps[1]) > 0.5 * max(gaps) + 0.001:
            report["reachedNothing"] += 1
            continue

        # A seam that runs from one colour to another -- the white of the
        # shell into the navy of the visor -- is not a crack to be
        # bridged: the strip would have to be one colour or the other,
        # and either way it puts a stripe across the face.  Those seams
        # are left open, and the outline pass is told not to ink them.
        if atlas is not None and uv_layer:
            for index in range(2):
                near_colour = atlas_colour(atlas, near_uv[index])
                far_colour = atlas_colour(atlas, far_uv[index])
                if near_colour is None or far_colour is None:
                    continue
                difference = sum((float(a) - float(b)) ** 2
                                 for a, b in zip(near_colour, far_colour)) ** 0.5
                if difference > max_colour:
                    report["differentColour"] += 1
                    ok = False
                    break
        if not ok:
            continue

        (first, first_far), (second, second_far) = corners
        first_far_vertex = bm.verts.new(first_far)
        second_far_vertex = bm.verts.new(second_far)
        try:
            face = bm.faces.new((first, second, second_far_vertex, first_far_vertex))
        except ValueError:
            bm.verts.remove(first_far_vertex)
            bm.verts.remove(second_far_vertex)
            report["reachedNothing"] += 1
            continue
        face.smooth = True
        # Which way the strip faces is decided by the order its corners
        # were put in, and half of them come out the other way round.
        # A strip that faces inwards is culled by a single sided
        # material, and the seam it was meant to close is open again.
        if face.normal.dot(normal) < 0.0:
            face.normal_flip()

        # The strip is painted with the colour of the tile it grew from,
        # and the far end with the colour of the tile it grew onto, so
        # that the repair does not show as a patch of a different shade.
        if uv_layer:
            loops = list(face.loops)
            if len(near_uv) == 2 and near_uv[0] is not None and near_uv[1] is not None:
                loops[0][uv_layer].uv = near_uv[0]
                loops[1][uv_layer].uv = near_uv[1]
            if far_uv[0] is not None:
                loops[2][uv_layer].uv = far_uv[0]
            if far_uv[1] is not None:
                loops[3][uv_layer].uv = far_uv[1]

        report["bridged"] += 1
        if is_head:
            report["bridgedHead"] += 1

    report["facesAfter"] = len(bm.faces)
    bm.normal_update()
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()

    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_apply=False,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_skins=True,
        export_morph=True,
        export_yup=True,
        export_draco_mesh_compression_enable=False,
    )
    print("YXZ_BRIDGE " + json.dumps(report))


if __name__ == "__main__":
    main()
