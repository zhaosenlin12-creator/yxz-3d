"""Create a review-only VRM candidate with selected mesh islands removed.

The UV seeds come from same-frame browser raycasts. Each seed is mapped to
its nearest triangle, then only the edge-connected component containing that
triangle is removed. The source asset is never modified.

Usage:
  python scripts/remove_yxz_uv_components.py source.vrm candidate.vrm \
    --uv 0.3108051,0.7039829 --uv 0.2670376,0.9741349
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb, write_glb  # noqa: E402


COMPONENT_TYPES = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_accessor(document, binary, index):
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    dtype = np.dtype(COMPONENT_TYPES[accessor["componentType"]])
    width = TYPE_WIDTHS[accessor["type"]]
    stride = view.get("byteStride", dtype.itemsize * width)
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    values = np.ndarray(
        (accessor["count"], width),
        dtype=dtype,
        buffer=binary,
        offset=offset,
        strides=(stride, dtype.itemsize),
    )
    return values.copy()


def connected_faces(faces, seed):
    edge_faces: dict[tuple[int, int], list[int]] = {}
    adjacency = [[] for _ in range(len(faces))]
    for face_index, (a, b, c) in enumerate(faces):
        for first, second in ((a, b), (b, c), (c, a)):
            key = (int(min(first, second)), int(max(first, second)))
            neighbours = edge_faces.setdefault(key, [])
            for neighbour in neighbours:
                adjacency[face_index].append(neighbour)
                adjacency[neighbour].append(face_index)
            neighbours.append(face_index)

    found = np.zeros(len(faces), dtype=bool)
    found[seed] = True
    stack = [seed]
    while stack:
        current = stack.pop()
        for neighbour in adjacency[current]:
            if not found[neighbour]:
                found[neighbour] = True
                stack.append(neighbour)
    return np.flatnonzero(found)


def repack_views(document, binary, replacements):
    chunks = []
    offset = 0
    for index, view in enumerate(document["bufferViews"]):
        start = view.get("byteOffset", 0)
        blob = replacements.get(
            index,
            binary[start:start + view["byteLength"]],
        )
        padding = (-offset) % 4
        if padding:
            chunks.append(b"\x00" * padding)
            offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        chunks.append(blob)
        offset += len(blob)
    packed = b"".join(chunks)
    document["buffers"][0]["byteLength"] = len(packed)
    return packed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--uv",
        action="append",
        required=True,
        help="base-colour atlas UV seed as U,V; repeat for each component",
    )
    parser.add_argument("--max-faces", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    document, binary = read_glb(args.source)
    candidates = []
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            position_index = primitive.get("attributes", {}).get("POSITION")
            if position_index is not None:
                candidates.append((
                    document["accessors"][position_index]["count"],
                    mesh_index,
                    primitive_index,
                    primitive,
                ))
    if not candidates:
        raise SystemExit("no indexed mesh with POSITION was found")

    _, mesh_index, primitive_index, primitive = max(candidates, key=lambda row: row[0])
    attributes = primitive["attributes"]
    positions = read_accessor(document, binary, attributes["POSITION"])
    uvs = read_accessor(document, binary, attributes["TEXCOORD_0"])
    index_accessor = document["accessors"][primitive["indices"]]
    if index_accessor["type"] != "SCALAR":
        raise SystemExit("mesh index accessor is not SCALAR")
    indices = read_accessor(document, binary, primitive["indices"]).reshape(-1)
    if len(indices) % 3:
        raise SystemExit("triangle index count is not divisible by three")
    faces = indices.reshape(-1, 3).astype(np.int64)
    face_uvs = uvs[faces].mean(axis=1)

    removed = np.zeros(len(faces), dtype=bool)
    records = []
    for raw_seed in args.uv:
        seed_uv = np.array([float(value) for value in raw_seed.split(",")])
        if seed_uv.shape != (2,):
            raise SystemExit(f"invalid UV seed: {raw_seed}")
        distances = np.linalg.norm(face_uvs - seed_uv, axis=1)
        seed_face = int(np.argmin(distances))
        component = connected_faces(faces, seed_face)
        if len(component) > args.max_faces:
            raise SystemExit(
                f"refusing {len(component)} faces at UV {raw_seed}; "
                f"limit is {args.max_faces}"
            )
        if removed[component].any():
            raise SystemExit(f"UV seeds select overlapping components: {raw_seed}")
        removed[component] = True
        component_vertices = np.unique(faces[component])
        component_uv = uvs[component_vertices]
        component_positions = positions[component_vertices]
        record = {
            "seedUV": seed_uv.tolist(),
            "seedFace": seed_face,
            "seedDistance": float(distances[seed_face]),
            "faces": int(len(component)),
            "vertices": int(len(component_vertices)),
            "uvBounds": [
                component_uv.min(axis=0).tolist(),
                component_uv.max(axis=0).tolist(),
            ],
            "positionBounds": [
                component_positions.min(axis=0).tolist(),
                component_positions.max(axis=0).tolist(),
            ],
        }
        records.append(record)
        print("YXZ_UV_COMPONENT " + str(record))

    if args.dry_run:
        print(f"YXZ_UV_DRY_RUN removed={int(removed.sum())} faces")
        return

    kept_indices = faces[~removed].reshape(-1).astype(indices.dtype)
    index_view_index = index_accessor["bufferView"]
    index_view = document["bufferViews"][index_view_index]
    index_dtype = np.dtype(COMPONENT_TYPES[index_accessor["componentType"]])
    index_blob = kept_indices.astype(index_dtype, copy=False).tobytes()
    replacements = {index_view_index: index_blob}
    index_accessor["count"] = int(len(kept_indices))
    if len(kept_indices):
        index_accessor["min"] = [int(kept_indices.min())]
        index_accessor["max"] = [int(kept_indices.max())]
    document["meshes"][mesh_index]["primitives"][primitive_index] = primitive
    packed = repack_views(document, binary, replacements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(args.output, document, packed)
    print(
        f"YXZ_UV_CANDIDATE {args.output} "
        f"triangles={len(faces)}->{len(kept_indices) // 3} "
        f"removed={int(removed.sum())}"
    )


if __name__ == "__main__":
    main()
