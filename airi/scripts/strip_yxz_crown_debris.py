"""Take the litter off the crown of the helmet.

The head is built from a handful of big tiles that tile the dome between
them, and those tiles sit on the dome at a radius of about 0.29 from the
middle of the head.  The scan also left a great many small pieces lying on
top of that dome: sheets of the clear bubble that stood over the helmet and
shattered, strips of shell that were torn off and never taken away, and
crumbs of every size.

They are all outside the dome.  Nothing that belongs to the helmet stands
off it by more than a millimetre, so the pieces that do are the litter, and
the test is simply how far out from the middle of the head they start.

What the litter does to the character is worse than a dirty render: a sheet
standing off the crown catches the key light on its edge and draws a bright
line across the top of the head, and a crown with a dozen bright lines
across it reads as a helmet that has been smashed rather than as a helmet.

Usage:
  blender -b -P scripts/strip_yxz_crown_debris.py -- \
    --source <glb> --output <glb> [--centre 0.038,-0.001,0.094] \
    [--radius 0.293] [--min-z 0.10]
"""

from __future__ import annotations

import json
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


def islands(bm):
    """Every connected group of faces, in the order the mesh keeps them."""
    bm.faces.ensure_lookup_table()
    unvisited = set(bm.faces)
    groups = []
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


def thickness(points):
    """How far the points spread across their own best-fit plane."""
    if len(points) < 3:
        return 0.0
    array = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
    array -= array.mean(axis=0)
    singular = np.linalg.svd(array, compute_uv=False)
    return float(singular[2]) * 2.0


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
    if atlas is None or uv is None:
        return None
    height, width = atlas.shape[0], atlas.shape[1]
    x = int(min(max(uv.x, 0.0), 1.0) * (width - 1))
    y = int(min(max(uv.y, 0.0), 1.0) * (height - 1))
    return atlas[y, x][:3]


def is_chromatic(colour):
    """Is this a painted mark rather than the white of the shell?

    The star on the forehead is a badge of blue and violet standing proud
    of the shell, and the rule that takes the torn edges off the crown
    takes the badge with it if the badge is not told apart first.  The
    shell is white and the badge is not, so the colour is what tells them
    apart.
    """
    if colour is None:
        return False
    low = min(float(c) for c in colour)
    high = max(float(c) for c in colour)
    return high - low > 0.12 and low < 0.85


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    radius = float(value_after("--radius", "0.293"))
    min_z = float(value_after("--min-z", "0.10"))
    crown_z = float(value_after("--crown-z", "0.30"))
    # The teeth rule is off by default.
    #
    # It was meant to take off the row of spikes along the rim where the
    # shell tore, and it does that -- but it takes the helmet with it.  A
    # face of the crown lies on a sphere, and near the top of the dome
    # the tangent plane of such a face passes very near the middle of the
    # head, so the rule cannot tell a spike of torn shell from a panel of
    # the helmet: it deleted a band of the crown and left the head with
    # a hole through the top of it.
    #
    # The shell's own torn edges are dealt with by the hole repair and by
    # the flake pass, which take them off without cutting into the panels
    # that are still wanted.
    standing = float(value_after("--standing", "-1"))
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    doomed = []
    report = {"islands": 0, "removedIslands": 0, "removedFaces": 0, "kept": 0,
              "crumbIslands": 0, "tangentialFaces": 0}
    for number, group in enumerate(islands(bm)):
        report["islands"] += 1
        points = [v.co.copy() for face in group for v in face.verts]
        if not points:
            continue
        if min(point.z for point in points) < min_z:
            continue
        radii = [(point - centre).length for point in points]
        if min(radii) < radius:
            continue
        doomed.append((number, group, min(radii), max(radii), len(group),
                        thickness(points)))

    for number, group, r_min, r_max, faces, thick in doomed:
        bmesh.ops.delete(bm, geom=group, context="FACES")
        report["removedIslands"] += 1
        report["removedFaces"] += faces
        if faces > 100 or r_max > 0.33:
            print("YXZ_DEBRIS_REMOVED " + json.dumps({
                "island": number, "faces": faces,
                "rMin": round(r_min, 4), "rMax": round(r_max, 4),
                "thick": round(thick, 4)}))

    # The teeth.  Where the shell was torn, the cut edge stands up out of
    # the surface as a row of spikes, and each spike is a piece of shell
    # on its end rather than a piece of it lying on the dome.
    #
    # The two are told apart by the distance from the middle of the head
    # to the plane of the face.  A face that lies on the dome has the
    # middle of the head a good half of the head's own radius off its
    # plane, because the plane of the face is a tangent of the sphere the
    # head is.  A face that stands on end has the middle of the head
    # almost in its own plane, because the piece of shell it belongs to
    # runs across the dome rather than around it.
    #
    # The badge on the forehead is a face that stands on end as well --
    # it is a badge standing proud of the shell -- and it is told apart by
    # its colour.
    atlas = load_atlas()
    uv_layer = bm.loops.layers.uv.active
    bm.faces.ensure_lookup_table()
    sideways = []
    for face in bm.faces:
        middle = face.calc_center_median()
        if middle.z < crown_z:
            continue
        outward = middle - centre
        if outward.length > 0.33:
            continue
        distance = abs(face.normal.dot(centre - middle))
        if distance >= standing:
            continue
        marked = False
        if atlas is not None and uv_layer:
            for loop in face.loops:
                if is_chromatic(atlas_colour(atlas, loop[uv_layer].uv)):
                    marked = True
                    break
        if marked:
            report["protectedFaces"] = report.get("protectedFaces", 0) + 1
            continue
        sideways.append(face)
    if sideways:
        bmesh.ops.delete(bm, geom=sideways, context="FACES")
        report["tangentialFaces"] = len(sideways)
        report["removedFaces"] += len(sideways)

    report["kept"] = report["islands"] - report["removedIslands"]
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
    print("YXZ_DEBRIS " + json.dumps(report))


if __name__ == "__main__":
    main()
