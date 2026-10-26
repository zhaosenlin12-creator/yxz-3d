"""Find the halo by its colour and measure the ring it is drawn on.

The halo is the one piece of the character that is a bright cyan, and
it is also the piece that is visibly broken: the ring is split into two
arcs with a gap across the top, and the star beside it reads as a
shard.  Finding it by eye is hopeless and finding it by coordinate is
guesswork, so it is found by the colour it is painted.

Every face is sampled at the middle of its own UV island, the samples
are classified as halo or not, and the halo faces are then measured:
how far the ring reaches, how it is tilted, and how much of the
ellipse is actually there.  That last number is the broken bit.

Usage:
  blender -b -P scripts/probe_yxz_halo.py -- --glb <glb> [--out <png>]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def load_atlas():
    """The base colour image, as a numpy array of RGBA rows."""
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    raise RuntimeError("no base colour image in the file")


def classify(atlas, uv) -> tuple[bool, tuple]:
    """Is this UV on the cyan of the halo, and what colour is it?"""
    height, width = atlas.shape[0], atlas.shape[1]
    x = int(min(max(uv[0], 0.0), 1.0) * (width - 1))
    y = int(min(max(uv[1], 0.0), 1.0) * (height - 1))
    pixel = atlas[y, x]
    r, g, b = float(pixel[0]), float(pixel[1]), float(pixel[2])
    # Blender hands the pixels over in linear space, so the halo's cyan
    # is a bright, strongly saturated green-blue while the body's white
    # is bright but almost neutral.  The test has to reject the white
    # body, or every panel of the character comes back as halo.
    cyan = (
        g > 0.45
        and b > 0.45
        and g - r > 0.25
        and b - r > 0.25
        and abs(g - b) < 0.22
    )
    return cyan, (round(r, 3), round(g, 3), round(b, 3))


def main() -> None:
    glb = value_after("--glb")
    out = value_after("--out")
    min_z = float(value_after("--min-z", -1e9))
    require_cyan = "--any-colour" not in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    atlas = load_atlas()

    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    mesh = body.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("the body has no UV layer")

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    halo_faces = []
    for face in bm.faces:
        u = sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops)
        v = sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops)
        centre = face.calc_center_median()
        if centre.z < min_z:
            continue
        cyan, _ = classify(atlas, (u, v))
        if cyan or not require_cyan:
            halo_faces.append(face)

    print("YXZ_HALO_FACES %d of %d" % (len(halo_faces), len(bm.faces)))
    if not halo_faces:
        bm.free()
        return

    points = []
    for face in halo_faces:
        for vertex in face.verts:
            points.append(vertex.co.copy())

    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for point in points:
        for i in range(3):
            lo[i] = min(lo[i], point[i])
            hi[i] = max(hi[i], point[i])
    centre = (lo + hi) / 2
    print("YXZ_HALO_BBOX min=%s max=%s" % (list(lo), list(hi)))

    # The ring lies in a plane.  The plane's normal is the smallest
    # direction of the point cloud, found from the covariance matrix.
    coords = np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)
    covariance = np.cov(coords - coords.mean(axis=0), rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    normal = eigenvectors[:, 0]
    axis_a = eigenvectors[:, 2]
    axis_b = eigenvectors[:, 1]

    # Where each point sits on the ellipse, as an angle.
    angles = []
    for point in coords:
        delta = point - coords.mean(axis=0)
        angles.append(math.atan2(delta @ axis_b, delta @ axis_a))
    angles = np.array(angles)
    histogram = np.zeros(72, dtype=int)
    for angle in angles:
        histogram[int(((angle + math.pi) / (2 * math.pi) * 72).astype(int)) % 72] += 1

    gaps = []
    for index in range(72):
        if histogram[index] == 0:
            start = index
            while histogram[start] == 0:
                start = (start + 1) % 72
            end = start
            while histogram[end] == 0:
                end = (end + 1) % 72
            gaps.append((end - start) % 72)
    biggest = max(gaps) if gaps else 0

    print("YXZ_HALO_PLANE normal=%s" % [round(float(v), 4) for v in normal])
    print("YXZ_HALO_AXES major=%s minor=%s"
          % ([round(float(v), 4) for v in axis_a], [round(float(v), 4) for v in axis_b]))
    print("YXZ_HALO_ANGLES covered=%d/72 biggestGap=%d (%.1f deg)"
          % (72 - biggest, biggest, biggest * 5.0))
    print("YXZ_HALO_HISTOGRAM %s" % json.dumps(histogram.tolist()))

    if out:
        # A render of just the halo faces, so the shape can be looked at.
        keep = set(f.index for f in halo_faces)
        copy = mesh.copy()
        keep_bm = bmesh.new()
        keep_bm.from_mesh(copy)
        doomed = [f for f in keep_bm.faces if f.index not in keep]
        bmesh.ops.delete(keep_bm, geom=doomed, context="FACES")
        keep_bm.to_mesh(copy)
        keep_bm.free()
        obj = bpy.data.objects.new("halo", copy)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix(".blend")))
        print("YXZ_HALO_SAVED " + str(out))

    bm.free()


if __name__ == "__main__":
    main()
