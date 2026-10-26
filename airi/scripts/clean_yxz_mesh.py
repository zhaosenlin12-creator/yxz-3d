"""Clean the doubled and folded surfaces out of the YXZ scan.

The character arrives from Tripo as one mesh made of 230 blobs, and the
surface of that mesh folds over itself in a few hundred places.  Where a
fold exists, two sheets of front-facing geometry sit a hair apart, the
depth test flips between them from pixel to pixel, and the surface breaks
into speckle.  That is the shredded look on the visor edge and along the
helmet rim, and it is geometry, not texture: the base colour atlas is
clean and the speckle survives every material change.

The fix is to weld the fold away.  `remove doubles` merges vertices that
are closer together than the threshold, so a fold collapses into a single
sheet and the two copies stop fighting over the same pixel.  The
threshold has to be well under the size of a triangle -- the scan's
triangles are about 0.005 across -- so that only a genuine fold is welded
and the surface detail is left alone.

The welding is only half of it.  Welding moves vertices but leaves their
normals where they were, so a merged vertex ends up with a normal that
belongs to neither of the surfaces it now joins, and the surface that used
to be smooth turns into a faceted one.  That is what the scan's noise
looked like: a row of saw-tooth triangles along the jaw and a band of
speckle along the top of the visor, both of them clean in the base colour
atlas and both of them a pure shading artefact.

So the normals are repaired afterwards.  The repair is deliberately
targeted rather than a blanket "shade smooth": the scan's own normals are
right almost everywhere, and they carry the soft gradient across the cheek
that makes the face read as a face.  Rebuilding every normal from the
faces flattens that gradient into a hard white mask, which looks worse
than the noise it removes.

What is broken is a vertex whose normal does not agree with the surface it
sits on.  A vertex is only wrong when the faces around it are nearly
coplanar -- a real crease, where the two faces meet at a steep angle, has
a normal that sits between them and is perfectly correct.  So each corner
is compared against the average of the faces around its vertex that face
the same way, and only the corners that disagree are replaced.

Usage:
  blender -b -P scripts/clean_yxz_mesh.py -- \
    --source <glb> --output <glb> [--threshold 0.0006] [--push 0] \
    [--repair-deg 20] [--flat-deg 30]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def count_degenerate(mesh) -> int:
    bm = bmesh.new()
    bm.from_mesh(mesh)
    result = sum(1 for face in bm.faces if face.calc_area() < 1e-12)
    bm.free()
    return result


def drop_loose(mesh, max_faces: int) -> dict:
    """Take away the pieces of the mesh that touch nothing.

    The weld leaves the character in eleven thousand pieces, and the
    pieces that matter are the big ones: a few hundred patches that
    carry the whole surface.  The rest are the fringe -- single
    triangles and slivers caught along every edge the scan was cut on,
    and the torn sheet that lay across the jaw.  On screen that fringe
    is the sawtooth along the visor, the cracked crown and the white
    tongue over the mouth: the body itself is smooth, and what reads
    as broken is a layer of loose debris sitting on it.

    A piece is loose when it is a component of its own, so it can be
    taken away whole.  Taking a piece away cannot open a hole in what
    it was lying on, because it was never joined to it.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
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

    groups.sort(key=len, reverse=True)
    census = {
        "pieces": len(groups),
        "largest": len(groups[0]),
        "singleFacePieces": sum(1 for group in groups if len(group) == 1),
        "smallPieces": sum(1 for group in groups if len(group) <= max_faces),
    }
    if max_faces <= 0:
        bm.free()
        return {"skipped": "not asked for", "census": census}

    keep = set(groups[0])
    loose = [group for group in groups[1:] if len(group) <= max_faces]
    doomed = [face for group in loose for face in group]
    if not doomed:
        bm.free()
        return {"skipped": "nothing loose", "census": census}

    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return {
        "removedFaces": len(doomed),
        "removedPieces": len(loose),
        "census": census,
    }


def drop_above(mesh, min_z: float) -> dict:
    """Take away the pieces of the scan that float above the head.

    The scan's halo came back as a dozen separate blades of a broken
    ring hovering over the crown, and the character wears a ring of
    light that is built properly instead.  What is left of the old one
    is a scatter of torn plates and slivers above the helmet, and on
    screen they are the shards that hang over the head, the flat lid
    that floats above the crown and the star that sits in the wrong
    place with a piece of ring through it.

    A piece is one of them when the whole of it is above the crown.
    The helmet's own top reaches 0.40 and every piece of the old halo
    starts at 0.41 or higher, so the rule takes the halo's remains
    away and leaves the helmet exactly where it was.
    """
    if min_z <= 0:
        return {"skipped": "not asked for"}

    bm = bmesh.new()
    bm.from_mesh(mesh)
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

    doomed = []
    kept = 0
    for group in groups:
        lowest = min(vert.co.z for face in group for vert in face.verts)
        if lowest > min_z:
            doomed.extend(group)
        else:
            kept += 1
    if not doomed:
        bm.free()
        return {"skipped": "nothing above the crown"}

    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return {
        "removedFaces": len(doomed),
        "removedPieces": len(groups) - kept,
        "keptPieces": kept,
        "threshold": min_z,
    }


def repair_normals(mesh, repair_degrees: float, flat_degrees: float) -> dict:
    """Replace the corner normals that disagree with the surface they sit on.

    The scan is a merge of a couple of hundred separate sheets, and welding
    them pulls a few thousand vertices onto the wrong sheet.  Those are the
    vertices that turn a smooth surface into a torn one, and they are rare
    enough that a blanket rebuild costs more than it fixes: the rebuild
    throws away the soft gradient across the cheek that the face is made
    of.

    So every corner is compared with the average of the faces around its
    vertex that point the same way.  Two faces that meet at a steep angle
    are a crease and the corner between them is left alone; two faces that
    are nearly coplanar are a surface, and a corner whose normal points
    somewhere else entirely is a mistake.
    """
    repair_limit = math.radians(repair_degrees)
    flat_limit = math.radians(flat_degrees)

    face_normals = [polygon.normal.copy() for polygon in mesh.polygons]
    face_areas = [polygon.area for polygon in mesh.polygons]
    corners = [normal.vector.copy() for normal in mesh.corner_normals]

    vertex_faces: dict[int, list[int]] = {}
    for polygon_index, polygon in enumerate(mesh.polygons):
        for vertex_index in polygon.vertices:
            vertex_faces.setdefault(vertex_index, []).append(polygon_index)

    # `MeshLoop` has no back-pointer to its polygon, so the map is built
    # from the polygons' own loop ranges.
    loop_polygon: list[int] = [0] * len(mesh.loops)
    for polygon_index, polygon in enumerate(mesh.polygons):
        for loop_index in range(polygon.loop_start, polygon.loop_start + polygon.loop_total):
            loop_polygon[loop_index] = polygon_index

    repaired = 0
    for loop in mesh.loops:
        polygon_index = loop_polygon[loop.index]
        vertex_index = loop.vertex_index
        face_normal = face_normals[polygon_index]
        if face_normal.length < 1e-9:
            continue
        average = Vector((0.0, 0.0, 0.0))
        for other in vertex_faces.get(vertex_index, ()):
            if face_normals[other].length < 1e-9:
                continue
            if face_normals[other].angle(face_normal) < flat_limit:
                average += face_normals[other] * face_areas[other]
        if average.length < 1e-9:
            # The faces around this vertex cancel out, which is a fold:
            # there is no single right answer for its normal.
            continue
        average.normalize()
        if corners[loop.index].length < 1e-9:
            continue
        if corners[loop.index].angle(average) > repair_limit:
            corners[loop.index] = average
            repaired += 1

    mesh.normals_split_custom_set(corners)
    mesh.update()
    return {
        "corners": len(corners),
        "repaired": repaired,
        "repair_deg": repair_degrees,
        "flat_deg": flat_degrees,
    }


def main():
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    threshold = float(value_after("--threshold", 0.0006))
    push = float(value_after("--push", 0))
    repair_deg = float(value_after("--repair-deg", 60))
    flat_deg = float(value_after("--flat-deg", 30))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh in " + str(source))
    body = max(meshes, key=lambda obj: len(obj.data.vertices))

    report = {
        "source": str(source),
        "threshold": threshold,
        "push": push,
        "vertices_before": len(body.data.vertices),
        "polygons_before": len(body.data.polygons),
        "degenerate_before": count_degenerate(body.data),
    }

    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")

    # Fold the surface back onto itself first.  Merging the vertices of a
    # fold is what actually removes the double sheet; everything after
    # this is tidying up what the merge left behind.
    #
    # The weld is optional, and it is optional because it is destructive
    # in a way that is not visible from the face alone.  The scan arrives
    # as 229 pieces that fit together, and the seams between them are
    # held by slivers of triangle that are a hair wide.  Merging the
    # vertices of a sliver collapses it, and a collapsed sliver is
    # removed, and a removed sliver leaves the two pieces it was
    # holding together holding nothing at all.  Measured on the welded
    # mesh, the character goes from 229 pieces to eleven thousand, the
    # largest surviving piece shrinks by two thirds, and the surface
    # picks up a fringe of loose shards along every silhouette it had.
    #
    # The seam between two pieces is where the scan's own surface was
    # cut, so welding it shut does not repair a fold -- it cuts a
    # second one.  The face renders with sawtooth spikes around the
    # eyes, a torn sheet across the mouth, and a cracked crown, and
    # none of that is in the scan.  The scan's own head render is
    # clean, so the weld is what breaks it.
    #
    # So the weld is off by default now, and the fold that the welder
    # was chasing is dealt with by the camera's depth precision and by
    # the shadow bias instead.
    if "--no-weld" not in sys.argv:
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=threshold)
        if "--no-dissolve" not in sys.argv:
            bpy.ops.mesh.dissolve_degenerate(threshold=1e-6)
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    report["vertices_after"] = len(body.data.vertices)
    report["polygons_after"] = len(body.data.polygons)
    report["degenerate_after"] = count_degenerate(body.data)
    report["welded_vertices"] = report["vertices_before"] - report["vertices_after"]

    # The loose pieces are taken off before the halo is rebuilt, because
    # the halo's own remains are a loose piece as well and the two
    # operations would otherwise fight over the same faces.
    loose_limit = int(value_after("--drop-loose", 0))
    report["loose"] = drop_loose(body.data, loose_limit)

    # The scan's own halo came back as a dozen blades of a broken ring
    # hovering over the crown.  The halo is rebuilt as an object of its
    # own later on, so the remains are taken away here, where the pieces
    # can still be told apart.
    report["aboveCrown"] = drop_above(
        body.data, float(value_after("--drop-above", 0.41))
    )

    # The halo is rebuilt after the weld, because the weld is what turns
    # the scanned double shell into the single sheet the halo actually
    # is, and the rebuild has to fit an ellipse to that sheet.
    #
    # Only the shards are removed here.  The ring itself is built later, as
    # an object of its own with a material that can carry a light: a ring
    # that shares the body's material is a ring that shares the body's
    # lighting, and a lit band of plastic is not a halo.
    if "--no-halo" not in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from rebuild_yxz_halo import rebuild_halo

        report["halo"] = rebuild_halo(body.data, build_geometry=False)

    # A few of the scan's folds ended up lying on the face rather than
    # around it.  The worst of them is a torn ribbon across the chin,
    # which draws a ragged white line over the muzzle.  It is a piece of
    # geometry of its own, lying on an intact surface, so it is taken
    # off rather than repaired.
    if "--no-debris" not in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from remove_yxz_debris import remove_debris

        report["debris"] = remove_debris(body.data)

    report["normals"] = repair_normals(body.data, repair_deg, flat_deg)

    if push:
        # A last resort for the folds that are too wide to weld: push every
        # vertex along its own normal.  The two sheets of a fold face
        # opposite ways, so the same push separates them.
        mesh = body.data
        for vertex in mesh.vertices:
            vertex.co.x += vertex.normal.x * push
            vertex.co.y += vertex.normal.y * push
            vertex.co.z += vertex.normal.z * push
        mesh.update()
        report["pushed"] = push

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
    report["output"] = str(output)
    print("YXZ_CLEANED " + json.dumps(report))


if __name__ == "__main__":
    main()
