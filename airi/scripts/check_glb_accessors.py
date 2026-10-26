"""Verify every accessor actually fits inside the buffer it points at.

Repacking buffer views is easy to get subtly wrong: the view offsets must
account for the alignment padding that accessors expect, and the accessor /
image / skin indirections must all survive renumbering. A viewer that does not
validate this fails deep inside three.js with an opaque
`Invalid typed array length` instead of naming the broken reference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glb_json import collect_buffer_view_refs  # noqa: E402
from glb_json import read_glb  # noqa: E402

COMPONENT_BYTES = {
    5120: 1,  # BYTE
    5121: 1,  # UNSIGNED_BYTE
    5122: 2,  # SHORT
    5123: 2,  # UNSIGNED_SHORT
    5125: 4,  # UNSIGNED_INT
    5126: 4,  # FLOAT
}
TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def check(path: Path) -> int:
    document, binary = read_glb(path)
    views = document.get("bufferViews", [])
    accessors = document.get("accessors", [])
    problems = []

    declared = document.get("buffers", [{}])[0].get("byteLength")
    if declared is not None and declared != len(binary):
        problems.append(
            f"buffer.byteLength {declared} != actual BIN chunk {len(binary)}")

    for index, view in enumerate(views):
        start = view.get("byteOffset", 0)
        end = start + view["byteLength"]
        if end > len(binary):
            problems.append(
                f"bufferView {index} spans {start}..{end}, past BIN size {len(binary)}")

    def spans(view_index: int, byte_offset: int, length: int, label: str) -> None:
        if not 0 <= view_index < len(views):
            problems.append(f"{label} references missing bufferView {view_index}")
            return
        view = views[view_index]
        start = view.get("byteOffset", 0) + byte_offset
        end = start + length
        limit = view.get("byteOffset", 0) + view["byteLength"]
        if end > limit:
            problems.append(
                f"{label} reads {start}..{end}, past bufferView {view_index} end {limit}")

    for index, accessor in enumerate(accessors):
        components = TYPE_COMPONENTS.get(accessor.get("type", ""))
        size = COMPONENT_BYTES.get(accessor.get("componentType", 0))
        if components is None or size is None:
            problems.append(f"accessor {index} has an unsupported type/componentType")
            continue
        count = accessor.get("count", 0)
        element = components * size
        sparse = accessor.get("sparse")
        if "bufferView" in accessor:
            if accessor["bufferView"] < len(views):
                view = views[accessor["bufferView"]]
                stride = view.get("byteStride") or element
                base_length = (count - 1) * stride + element if count else 0
                spans(accessor["bufferView"], accessor.get("byteOffset", 0),
                      base_length, f"accessor {index}")
            else:
                problems.append(
                    f"accessor {index} references missing bufferView {accessor['bufferView']}")
        elif count and sparse is None:
            problems.append(
                f"accessor {index} has {count} elements but no bufferView and no sparse")
        if sparse is not None:
            sparse_count = sparse.get("count", 0)
            if sparse_count > count:
                problems.append(
                    f"accessor {index} sparse count {sparse_count} exceeds {count}")
            index_size = COMPONENT_BYTES.get(
                sparse["indices"].get("componentType", 0), 0)
            spans(sparse["indices"]["bufferView"],
                  sparse["indices"].get("byteOffset", 0),
                  sparse_count * index_size,
                  f"accessor {index} sparse indices")
            spans(sparse["values"]["bufferView"],
                  sparse["values"].get("byteOffset", 0),
                  sparse_count * element,
                  f"accessor {index} sparse values")

    for index, image in enumerate(document.get("images", [])):
        if "bufferView" in image:
            view_index = image["bufferView"]
            if 0 <= view_index < len(views):
                spans(view_index, 0, views[view_index]["byteLength"], f"image {index}")
            else:
                problems.append(f"image {index} references missing bufferView {view_index}")

    for index, skin in enumerate(document.get("skins", [])):
        ibm = skin.get("inverseBindMatrices")
        if ibm is None:
            continue
        if not 0 <= ibm < len(accessors):
            problems.append(
                f"skin {index} inverseBindMatrices {ibm} is not a valid accessor")
            continue
        # A MAT4 accessor's `count` is already the number of matrices.
        expected = len(skin.get("joints", []))
        if accessors[ibm].get("count") != expected:
            problems.append(
                f"skin {index} inverseBindMatrices has {accessors[ibm].get('count')} "
                f"matrices, expected {expected} for {len(skin.get('joints', []))} joints")

    dangling = sorted(collect_buffer_view_refs(document) - set(range(len(views))))
    if dangling:
        problems.append(f"dangling bufferView references: {dangling}")

    for problem in problems:
        print("FAIL " + problem)
    if not problems:
        print(json.dumps({
            "file": str(path),
            "bufferViews": len(views),
            "accessors": len(accessors),
            "images": len(document.get("images", [])),
            "binBytes": len(binary),
            "status": "ok",
        }))
    return len(problems)


if __name__ == "__main__":
    sys.exit(1 if check(Path(sys.argv[1])) else 0)
