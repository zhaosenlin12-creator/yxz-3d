"""Take the flat flakes off the shell.

The scan of the character is not one surface but a mosaic: eleven thousand
separate pieces.  A hundred and thirty-nine of them are the character --
the tiles of the helmet, the panels of the arm, the plate of the book.
The rest are litter: chips lying *on* that surface, each one its own
island, none of them joined to anything.

What the litter does to the character is not a dirty render.  A chip that
lies on the surface is a second copy of a patch of it, a fraction of a
millimetre off, and the depth test cannot decide between the two: the
shell comes out of the render scratched with dark hairline marks, the
way a wall comes out when it is filmed through glass.  That scratching
is what makes a character read as shattered rather than as whole, and no
amount of lighting or material fixes it, because the two surfaces are
fighting for the same pixel.

So the test that matters is not what a chip looks like.  It is how far
off the surface it lies, and the answer is measured rather than guessed:

* On the surface -- within half a micron of a point that belongs to the
  design -- the chip is a copy.  It has no silhouette of its own, it
  adds nothing, and it only ever fights with the surface underneath it.
  It goes, whatever colour it is.  An earlier revision protected the
  painted marks by colour at this step, and the protection kept half the
  litter: the chips are UV-mapped into the dark parts of the atlas, so
  "not white" is exactly what a chip looks like.
* Standing off the surface -- the star on the forehead, the blue trim on
  the wings -- it is a piece of the design with a shape of its own, and
  it is kept when it is painted.  The shell is white; the marks are blue
  and violet, and they are the only things on the model that are.

Usage:
  blender -b -P scripts/clean_yxz_shell_flakes.py -- \
    --source <glb> --output <glb> [--thin 0.008] [--max-faces 400] \
    [--gap 0.004] [--coincident 0.0005] [--chroma 0.20] [--value 0.40] \
    [--report-only]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree


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


def flatness(points):
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


def chip_colour(atlas, uv_layer, group):
    """The mean atlas colour under one island, and how spread it is."""
    if atlas is None or uv_layer is None:
        return None, 0.0
    samples = []
    for face in group:
        for loop in face.loops:
            samples.append(atlas_colour(atlas, loop[uv_layer].uv))
    if not samples:
        return None, 0.0
    array = np.array(samples, dtype=np.float32)
    mean = array.mean(axis=0)
    spread = float((array.max(axis=0) - array.min(axis=0)).max())
    return mean, spread


def is_paint(mean, chroma, value):
    """Is this the blue of the star and the trim rather than the white?

    The shell is a warm white with almost no colour in it.  The star is
    blue and violet, the trim on the wings is the same blue, and both
    stand clear of the shell they are painted on.  A chip of torn shell
    catches whatever the atlas happened to put under its corners, so the
    line that matters is not "is it coloured" -- the chips are coloured
    too -- but "is it *strongly* coloured and still bright".  The litter
    samples the dark seams of the atlas and comes out near black, which
    no amount of chroma rescues.
    """
    if mean is None:
        return False
    if float(np.max(mean)) < value:
        return False
    return float(np.max(mean) - np.min(mean)) > chroma


def is_badge(face_count, closest, mean, chroma, value, raise_min, faces_min):
    """Is this a mark of the design standing proud of the shell?

    The star on the forehead and the blue trim on the wings are the only
    things on the model that stand up off the shell, and they are the
    only things worth keeping out of a sweep.  They are told apart from
    the litter by three numbers at once: they stand clear of the
    surface (the litter lies on it or floats in front of it), they are
    painted in a strong colour, and they are made of more than a couple
    of triangles.

    The colour has to be a strong one.  The visor is a strong colour
    too, and the litter lying on the visor samples it, so a chip that
    samples the navy of the visor is protected by a loose test and the
    visor comes out of the render flecked with white.  The badge is
    *bright* as well as coloured -- it is a pale blue, not a navy --
    and that is what tells the two apart.
    """
    if face_count < faces_min:
        return False
    if closest < raise_min:
        return False
    if mean is None:
        return False
    if float(np.max(mean)) < value:
        return False
    return float(np.max(mean) - np.min(mean)) > chroma


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    thin = float(value_after("--thin", "0.008"))
    max_faces = int(value_after("--max-faces", "400"))
    gap = float(value_after("--gap", "0.004"))
    coincident = float(value_after("--coincident", "0.0005"))
    chroma = float(value_after("--chroma", "0.20"))
    value = float(value_after("--value", "0.40"))
    raise_min = float(value_after("--raise", "0.0012"))
    paint_faces = int(value_after("--paint-faces", "10"))
    report_only = "--report-only" in sys.argv
    output.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()

    groups = islands(bm)
    # The design is in the large pieces; the litter is in the small ones.
    big = [group for group in groups if len(group) > max_faces]
    small = [group for group in groups if len(group) <= max_faces]

    # A tree over the design's own points, so the test "does this chip
    # lie on the character" is a nearest-neighbour question rather than a
    # comparison of every chip against every panel.
    design_points = [v.co.copy() for group in big for face in group
                     for v in face.verts]
    tree = KDTree(len(design_points))
    for index, point in enumerate(design_points):
        tree.insert(point, index)
    tree.balance()

    atlas = load_atlas()
    uv_layer = bm.loops.layers.uv.active

    doomed = []
    painted = 0
    copies = 0
    too_far = 0
    not_flat = 0
    badges = []
    for number, group in enumerate(small):
        points = [v.co.copy() for face in group for v in face.verts]
        if len(points) < 3:
            continue
        if flatness(points) > thin:
            not_flat += 1
            continue
        # How far is the chip from the design it is lying on?
        closest = min(tree.find(Vector(p))[2] for p in points)
        if closest > gap:
            too_far += 1
            continue
        mean, spread = chip_colour(atlas, uv_layer, group)
        if is_badge(len(group), closest, mean, chroma, value, raise_min,
                    paint_faces):
            painted += 1
            centre = Vector((0.0, 0.0, 0.0))
            for point in points:
                centre += point
            centre /= len(points)
            badges.append({
                "faces": len(group),
                "gap": round(closest, 6),
                "rgb": [round(float(c), 3) for c in mean],
                "at": [round(float(c), 3) for c in centre],
            })
            continue
        if closest <= coincident:
            copies += 1
        doomed.append((number, group, len(group), round(closest, 6)))

    doomed.sort(key=lambda row: -row[2])
    report = {
        "islands": len(groups),
        "bigIslands": len(big),
        "smallIslands": len(small),
        "flakes": len(doomed),
        "flakeFaces": sum(row[2] for row in doomed),
        "copiesRemoved": copies,
        "paintedKept": painted,
        "badges": badges[:40],
        "notFlat": not_flat,
        "offSurface": too_far,
        "facesBefore": len(bm.faces),
        "sample": [{"island": row[0], "faces": row[2], "gap": row[3]}
                    for row in doomed[:20]],
    }

    if not report_only and doomed:
        bmesh.ops.delete(bm, geom=[face for row in doomed for face in row[1]],
                         context="FACES")
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
        bm.normal_update()
        bm.to_mesh(body.data)
        body.data.update()
        report["facesAfter"] = len(body.data.polygons)

    bm.free()
    print("YXZ_FLAKES " + json.dumps(report))

    if not report_only:
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


if __name__ == "__main__":
    main()
