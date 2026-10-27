"""Which bones of the YXZ rig can be moved without tearing the mesh.

The figure broke every time a clip was cross-faded: the arms and the jaw
travel through the middle of a fade, and the automatic skin weights are
weakest exactly there, so the mesh gets dragged instead of following the
limb.  Not every joint is like that.  A joint that owns its geometry
rigidly -- weight 1.0 on every vertex it dominates -- can be rotated
freely, because the geometry it moves moves as one solid piece.

This reports, for every joint of every skinned mesh:

  dominant   -- vertices for which this joint is the strongest influence
  rigid      -- of those, how many carry the full weight (1.0) on it
  share      -- the mean weight this joint holds on the vertices it
                dominates; 1.0 means the geometry belongs to the joint
                alone and travels with it

And it lists the meshes that are not skinned at all -- those follow their
parent bone rigidly and are always safe to move.

Usage:
  python scripts/probe_yxz_safe_bones.py <model.vrm|glb>
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
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
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + length]
        if kind == 0x4E4F534A:
            document = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            binary = chunk
        offset += 8 + length
    return document, binary


def accessor(document, binary, index):
    spec = document["accessors"][index]
    view = document["bufferViews"][spec["bufferView"]]
    count = spec["count"]
    width = COUNT[spec["type"]]
    fmt = COMPONENT.get(spec["componentType"])
    if fmt is None:
        return []
    size = struct.calcsize("<" + fmt)
    base = view.get("byteOffset", 0) + spec.get("byteOffset", 0)
    stride = view.get("byteStride") or size * width
    buffer = memoryview(binary)
    out = []
    for row in range(count):
        start = base + row * stride
        out.append(struct.unpack_from("<" + fmt * width, buffer, start))
    return out


def mesh_name(node):
    return node.get("name") or "(unnamed)"


def main() -> None:
    document, binary = read_glb(Path(sys.argv[1]))
    nodes = document["nodes"]
    names = [node.get("name", "") for node in nodes]

    # Meshes that are not skinned follow their parent bone rigidly.
    skinned_nodes = {node["skin"] for node in nodes if "skin" in node}
    rigid_meshes = []
    for index, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        if "skin" in node:
            continue
        rigid_meshes.append({
            "node": index,
            "name": mesh_name(node),
            "parent": names[node["parent"]] if "parent" in node else None,
        })

    # Per joint, how its vertices are weighted.
    joints = {}
    for skin_index, skin in enumerate(document.get("skins", [])):
        joint_nodes = skin["joints"]
        for node_index, node in enumerate(nodes):
            if node.get("skin") != skin_index:
                continue
            mesh = document["meshes"][node["mesh"]]
            for primitive in mesh.get("primitives", []):
                joint_attribute = primitive["attributes"].get("JOINTS_0")
                weight_attribute = primitive["attributes"].get("WEIGHTS_0")
                if joint_attribute is None or weight_attribute is None:
                    continue
                joint_rows = accessor(document, binary, joint_attribute)
                weight_rows = accessor(document, binary, weight_attribute)
                for joint_row, weight_row in zip(joint_rows, weight_rows):
                    best = max(range(len(weight_row)), key=lambda i: weight_row[i])
                    local = joint_row[best]
                    joint_name = names[joint_nodes[local]]
                    entry = joints.setdefault(
                        joint_name,
                        {"dominant": 0, "rigid": 0, "weightSum": 0.0, "meshes": set()},
                    )
                    entry["dominant"] += 1
                    entry["weightSum"] += weight_row[best]
                    entry["meshes"].add(mesh_name(node))
                    if weight_row[best] >= 0.999:
                        entry["rigid"] += 1

    report = {}
    for name, entry in sorted(joints.items()):
        dominant = entry["dominant"]
        report[name] = {
            "dominant": dominant,
            "rigid": entry["rigid"],
            "rigidShare": round(entry["rigid"] / dominant, 3) if dominant else 0.0,
            "meanWeight": round(entry["weightSum"] / dominant, 3) if dominant else 0.0,
            "meshes": sorted(entry["meshes"]),
        }

    print(json.dumps({
        "unskinnedMeshes": rigid_meshes,
        "joints": report,
    }, indent=2))


if __name__ == "__main__":
    main()
