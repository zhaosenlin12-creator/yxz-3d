"""Take the scan's leftovers out of the restored YXZ model.

The scan came with a halo of its own, in pieces, floating above the
head.  The model was given a proper ring to replace it, so the pieces
are now duplicates that sit in the middle of the new ring and make it
look like debris.

The pieces are easy to pick out: they are separate sheets of the
mesh, and every one of their vertices is above the head, clear of the
body.  This removes those sheets and leaves everything else - the
rebuilt halo is its own mesh and is not touched.

Usage:
  python scripts/trim_yxz_restored.py <in.vrm> <out.vrm> [--min-y 0.40]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb, write_glb  # noqa: E402


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def decode(document, data, index):
    a = document["accessors"][index]
    view = document["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    count = a["count"] * width
    return np.frombuffer(data, dtype=dtype, count=count, offset=start).reshape(a["count"], width).copy()


def islands(positions, faces):
    """Label every vertex with the sheet of mesh it belongs to."""
    key = np.round(positions, 6)
    lookup = {}
    welded = np.empty(len(positions), dtype=np.int64)
    for i, point in enumerate(map(tuple, key)):
        if point not in lookup:
            lookup[point] = i
        welded[i] = lookup[point]
    fv = np.stack([welded[faces[:, 0]], welded[faces[:, 1]], welded[faces[:, 2]]], axis=1)
    parent = np.arange(len(positions))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for tri in fv:
        ra = find(int(tri[0]))
        for b in tri[1:]:
            rb = find(int(b))
            if ra != rb:
                parent[rb] = ra
    roots = np.array([find(i) for i in range(len(positions))])
    _, inverse = np.unique(roots, return_inverse=True)
    return inverse, inverse[fv[:, 0]]


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    min_y = float(value_after("--min-y", "0.40"))

    document, data = read_glb(source)
    primitive = document["meshes"][0]["primitives"][0]
    attributes = primitive["attributes"]
    positions = decode(document, data, attributes["POSITION"]).astype(np.float64)
    normals = decode(document, data, attributes["NORMAL"]).astype(np.float64)
    uvs = decode(document, data, attributes["TEXCOORD_0"]).astype(np.float64)
    joints = decode(document, data, attributes["JOINTS_0"])
    weights = decode(document, data, attributes["WEIGHTS_0"]).astype(np.float64)
    indices = decode(document, data, primitive["indices"]).reshape(-1).astype(np.uint32)
    faces = indices.reshape(-1, 3).astype(np.int64)

    labels, face_labels = islands(positions, faces)
    keep_faces = np.ones(len(faces), dtype=bool)
    removed = 0
    for sheet in np.unique(face_labels):
        verts = np.nonzero(labels == sheet)[0]
        if len(verts) < 50:
            continue
        if positions[verts, 1].min() < min_y:
            continue
        sel = face_labels == sheet
        keep_faces &= ~sel
        removed += int(sel.sum())
        print("YXZ_TRIM sheet %d removed: %d faces, %d verts, y %.3f..%.3f" % (
            sheet, int(sel.sum()), len(verts),
            positions[verts, 1].min(), positions[verts, 1].max()))

    if removed == 0:
        print("YXZ_TRIM nothing to remove")
        return

    # The vertices that no face uses any more go too, so the file does
    # not carry a cloud of loose points.
    used = np.zeros(len(positions), dtype=bool)
    used[np.unique(faces[keep_faces])] = True
    remap = np.full(len(positions), -1, dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))

    new_faces = remap[faces[keep_faces]]
    new_positions = positions[used]
    new_normals = normals[used]
    new_uvs = uvs[used]
    new_joints = joints[used]
    new_weights = weights[used]
    new_indices = new_faces.reshape(-1).astype(np.uint32)

    # Find the buffer view each of the main mesh's accessors reads from,
    # rather than assuming they are the first six.
    replacements = {
        attributes["POSITION"]: new_positions.astype("<f4").tobytes(),
        attributes["NORMAL"]: new_normals.astype("<f4").tobytes(),
        attributes["TEXCOORD_0"]: new_uvs.astype("<f4").tobytes(),
        attributes["JOINTS_0"]: new_joints.tobytes(),
        attributes["WEIGHTS_0"]: new_weights.astype("<f4").tobytes(),
        primitive["indices"]: new_indices.tobytes(),
    }
    view_blobs = {}
    for accessor_index, blob in replacements.items():
        view_index = document["accessors"][accessor_index]["bufferView"]
        view_blobs[view_index] = blob
    print("YXZ_TRIM faces %d -> %d, verts %d -> %d" % (
        len(faces), len(new_faces), len(positions), int(used.sum())))

    # Re-lay the binary chunk so the changed views fit.
    chunks = []
    offset = 0
    for index, view in enumerate(document["bufferViews"]):
        if index in view_blobs:
            blob = view_blobs[index]
        else:
            start = view.get("byteOffset", 0)
            blob = data[start:start + view["byteLength"]]
        padding = (-offset) % 4
        chunks.append(b"\x00" * padding)
        offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        chunks.append(blob)
        offset += len(blob)
    document["buffers"] = [{"byteLength": offset}]
    binary = b"".join(chunks)

    for name in ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"):
        document["accessors"][attributes[name]]["count"] = len(new_positions)
    document["accessors"][attributes["POSITION"]]["min"] = new_positions.min(axis=0).tolist()
    document["accessors"][attributes["POSITION"]]["max"] = new_positions.max(axis=0).tolist()
    document["accessors"][primitive["indices"]]["count"] = len(new_indices)

    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, binary)
    print("YXZ_TRIM written " + str(output))


if __name__ == "__main__":
    main()
