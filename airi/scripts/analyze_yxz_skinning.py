"""Report how the YXZ skin actually binds the hands.

The rest pose always looks right -- that is what a bind pose is -- so a
mis-placed bone only shows up once the bone rotates: the mesh gets dragged
and torn instead of following the limb.  The way to see that is to compare,
for every bone, where the bone actually is with where the geometry it
dominates actually is.

  python scripts/analyze_yxz_skinning.py docs/yxz-rig-review/yxz_rig_test.glb
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np


COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path: Path):
    data = path.read_bytes()
    magic, version, _ = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise SystemExit("not a glb")
    offset = 12
    document = None
    binary = b""
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
        offset += 8 + chunk_length
    return document, binary


def accessor(document, binary, index):
    spec = document["accessors"][index]
    view = document["bufferViews"][spec["bufferView"]]
    count = spec["count"]
    width = COUNT[spec["type"]]
    dtype = np.dtype("<" + COMPONENT[spec["componentType"]])
    base = view.get("byteOffset", 0) + spec.get("byteOffset", 0)
    stride = view.get("byteStride") or dtype.itemsize * width
    buffer = memoryview(binary)
    out = np.zeros((count, width), dtype=dtype)
    for row in range(count):
        start = base + row * stride
        out[row] = np.frombuffer(buffer[start:start + dtype.itemsize * width], dtype=dtype)
    return out


def local_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    matrix[:3, :3] = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]) * scale
    matrix[:3, 3] = node.get("translation", [0.0, 0.0, 0.0])
    return matrix


def build_world(document):
    """World matrix of every node, resolved through the node hierarchy."""
    parents = {}
    for parent_index, parent in enumerate(document["nodes"]):
        for child in parent.get("children", []):
            parents[child] = parent_index
    world = {}
    for index in range(len(document["nodes"])):
        chain = []
        cursor = index
        while cursor is not None:
            chain.append(cursor)
            cursor = parents.get(cursor)
        matrix = np.eye(4)
        for node_index in reversed(chain):
            matrix = matrix @ local_matrix(document["nodes"][node_index])
        world[index] = matrix
    return world


def segment_distance(points, head, tail):
    segment = tail - head
    length_sq = float(segment @ segment)
    if length_sq < 1e-12:
        return np.linalg.norm(points - head, axis=1)
    t = np.clip(((points - head) @ segment) / length_sq, 0.0, 1.0)
    closest = head + t[:, None] * segment
    return np.linalg.norm(points - closest, axis=1)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "docs/yxz-rig-review/yxz_rig_test.glb")
    document, binary = read_glb(path)
    world = build_world(document)

    skin = document["skins"][0]
    joints = skin["joints"]
    joint_names = {index: document["nodes"][index].get("name", f"#{index}")
                   for index in joints}

    # The inverse bind matrix is the inverse of the bone's rest transform, so
    # inverting it back gives the bone's rest head and its rest axis.
    inverse = accessor(document, binary, skin["inverseBindMatrices"]).reshape(-1, 4, 4)
    inverse = np.transpose(inverse, (0, 2, 1))
    rest = np.linalg.inv(inverse)

    bone_head = {}
    bone_axis = {}
    for slot, joint in enumerate(joints):
        bone_head[joint] = rest[slot][:3, 3]
        bone_axis[joint] = rest[slot][:3, 1]

    # Collect the skinned geometry in world space.
    positions = []
    joint_ids = []
    weights = []
    mesh_nodes = {}
    for node_index, node in enumerate(document["nodes"]):
        if "mesh" in node:
            mesh_nodes.setdefault(node["mesh"], []).append(node_index)
    for mesh_index, mesh in enumerate(document["meshes"]):
        owner = mesh_nodes.get(mesh_index, [])
        transform = world[owner[0]] if owner else np.eye(4)
        for primitive in mesh["primitives"]:
            attributes = primitive["attributes"]
            if "JOINTS_0" not in attributes:
                continue
            position = accessor(document, binary, attributes["POSITION"]).astype(np.float64)
            homogeneous = np.concatenate(
                [position, np.ones((position.shape[0], 1))], axis=1)
            positions.append((homogeneous @ transform.T)[:, :3])
            joint_ids.append(accessor(document, binary, attributes["JOINTS_0"]).astype(np.int32))
            weights.append(accessor(document, binary, attributes["WEIGHTS_0"]).astype(np.float64))
    if not positions:
        raise SystemExit("no skinned primitives")
    position = np.concatenate(positions)
    joint_id = np.concatenate(joint_ids)
    weight = np.concatenate(weights)

    report = {}
    for slot, joint in enumerate(joints):
        name = joint_names[joint]
        dominant = (joint_id[:, 0] == slot) & (weight[:, 0] > 0.5)
        if not dominant.any():
            continue
        points = position[dominant]
        centre = points.mean(axis=0)
        head = bone_head[joint]
        # The bone's tail is the head of the next bone down the chain.
        tail = head + bone_axis[joint] * 0.0
        for other_slot, other in enumerate(joints):
            if other_slot == slot:
                continue
            other_head = bone_head[other]
            if np.linalg.norm(other_head - head) < 1e-6:
                continue
            direction = bone_axis[joint]
            along = float((other_head - head) @ direction)
            if along <= 0:
                continue
            if tail is head or along < float((tail - head) @ direction):
                tail = head + direction * along
        report[name] = {
            "vertices": int(dominant.sum()),
            "headAt": [round(float(v), 4) for v in head],
            "meshAt": [round(float(v), 4) for v in centre],
            "distanceToBone": round(float(np.median(segment_distance(points, head, tail))), 4),
        }

    print(json.dumps({
        "jointCount": len(joints),
        "vertexCount": int(position.shape[0]),
        "bones": report,
    }, indent=2))


if __name__ == "__main__":
    main()
