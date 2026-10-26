"""Measure how much the YXZ scan overlaps itself.

The character arrives as 229 disconnected blobs that were merged into one
mesh, and where two of them overlap they z-fight: the depth test flips
triangle by triangle and the surface breaks into speckle.  Before deciding
how to remove the overlap it is worth knowing how the overlap is shaped.

For every triangle this finds the closest triangle that belongs to a
*different* blob, and reports the distance distribution plus which blob
pairs are responsible.  A mesh whose overlaps are all a hair apart can be
fixed by pushing the shells apart; a mesh with a whole inner copy of the
body needs the inner copy deleted.

Usage: python scripts/probe_yxz_overlap.py <model.glb>
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb  # noqa: E402


COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2",
             5125: "u4", 5126: "f4"}
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(document, binary, index):
    accessor = document["accessors"][index]
    dtype = COMPONENT[accessor["componentType"]]
    components = COMPONENTS[accessor["type"]]
    view = document["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or (np.dtype(dtype).itemsize * components)
    raw = np.frombuffer(binary, dtype=np.uint8, count=stride * accessor["count"], offset=base)
    values = np.frombuffer(raw.tobytes(), dtype=dtype)
    return values.reshape(accessor["count"], components) if components > 1 else values


def load_meshes(path):
    document, binary = read_glb(path)
    meshes = []
    for mesh in document.get("meshes", []):
        for part, primitive in enumerate(mesh.get("primitives", [])):
            attributes = primitive["attributes"]
            position = read_accessor(document, binary, attributes["POSITION"]).astype(np.float64)
            normal = None
            if "NORMAL" in attributes:
                normal = read_accessor(document, binary, attributes["NORMAL"]).astype(np.float64)
            uv = None
            if "TEXCOORD_0" in attributes:
                uv = read_accessor(document, binary, attributes["TEXCOORD_0"]).astype(np.float64)
            indices = None
            if "indices" in primitive:
                indices = read_accessor(document, binary, primitive["indices"]).astype(np.int64)
            meshes.append({
                "mesh": mesh.get("name", "?"),
                "part": part,
                "position": position,
                "normal": normal,
                "uv": uv,
                "indices": indices,
            })
    return document, meshes


def islands(positions, indices):
    """Label each triangle with the connected blob it belongs to."""
    vertex_count = positions.shape[0]
    parent = list(range(vertex_count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    triangles = indices.reshape(-1, 3)
    for a, b, c in triangles:
        union(int(a), int(b))
        union(int(b), int(c))
    labels = np.array([find(i) for i in range(vertex_count)])
    return labels[triangles[:, 0]]


def spatial_hash(points, cell):
    """Bucket points into a voxel grid and return the buckets as arrays."""
    keys = np.floor(points / cell).astype(np.int64)
    flat = (keys[:, 0] + 512) * 1024 * 1024 + (keys[:, 1] + 512) * 1024 + (keys[:, 2] + 512)
    order = np.argsort(flat, kind="stable")
    sorted_flat = flat[order]
    unique, start, count = np.unique(sorted_flat, return_index=True, return_counts=True)
    return unique, start, count, order


def coincident_vertices(positions, radius):
    """Count vertices that have another vertex within `radius`."""
    cell = radius
    unique, start, count, order = spatial_hash(positions, cell)
    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
    ]
    pairs = 0
    for dx, dy, dz in offsets:
        delta = (dx * 1024 * 1024 + dy * 1024 + dz)
        wanted = unique + delta
        position = np.searchsorted(unique, wanted)
        valid = position < unique.size
        position = np.minimum(position, unique.size - 1)
        matched = valid & (unique[position] == wanted)
        for bucket in np.nonzero(matched)[0]:
            members = order[start[bucket]:start[bucket] + count[bucket]]
            for a in members:
                for b in members:
                    if a >= b:
                        continue
                    distance = float(np.linalg.norm(positions[a] - positions[b]))
                    if distance < radius:
                        pairs += 1
    return pairs


def bounding_boxes(positions, triangles, labels):
    boxes = {}
    for index, triangle in enumerate(triangles):
        label = int(labels[index])
        corners = positions[triangle]
        if label not in boxes:
            boxes[label] = [corners.min(axis=0), corners.max(axis=0)]
        else:
            boxes[label][0] = np.minimum(boxes[label][0], corners.min(axis=0))
            boxes[label][1] = np.maximum(boxes[label][1], corners.max(axis=0))
    return boxes


def main():
    path = Path(sys.argv[1])
    document, meshes = load_meshes(path)
    report = {"file": str(path), "meshes": []}

    for entry in meshes:
        positions = entry["position"]
        indices = entry["indices"]
        if indices is None:
            indices = np.arange(positions.shape[0], dtype=np.int64)
        triangles = indices.reshape(-1, 3)
        labels = islands(positions, indices)

        centroids = positions[triangles].mean(axis=1)
        corners = positions[triangles]
        signed = np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])) / 6.0
        volumes = defaultdict(float)
        for label, value in zip(labels.tolist(), signed.tolist()):
            volumes[label] += value
        ordered = sorted(volumes.items(), key=lambda kv: -abs(kv[1]))
        info = {
            "mesh": entry["mesh"],
            "part": entry["part"],
            "vertices": int(positions.shape[0]),
            "triangles": int(triangles.shape[0]),
            "islands": int(len(set(labels.tolist()))),
            "extent": [round(float(v), 4) for v in (positions.max(axis=0) - positions.min(axis=0))],
        }
        info["largest_blobs"] = [
            {"island": int(label),
             "triangles": int((labels == label).sum()),
             "signed_volume": round(float(value), 8)}
            for label, value in ordered[:6]
        ]
        info["inward_blobs"] = sum(1 for value in volumes.values() if value < 0)

        for radius in (0.0005, 0.002, 0.01):
            info[f"coincident_vertex_pairs_within_{radius}"] = coincident_vertices(positions, radius)

        # Which blobs share space?  Two boxes that overlap are two scans of
        # the same piece of the character sitting on top of each other.
        boxes = bounding_boxes(positions, triangles, labels)
        overlaps = []
        items = list(boxes.items())
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                (label_a, box_a), (label_b, box_b) = items[a], items[b]
                gap = np.maximum(box_a[0] - box_b[1], box_b[0] - box_a[1]).max()
                if gap < 0.005:
                    overlaps.append({
                        "islands": [label_a, label_b],
                        "gap": round(float(gap), 6),
                        "triangles": int((labels == label_a).sum() + (labels == label_b).sum()),
                    })
        overlaps.sort(key=lambda row: row["gap"])
        info["overlapping_blob_pairs"] = overlaps[:12]
        info["overlapping_blob_pair_count"] = len(overlaps)
        report["meshes"].append(info)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
