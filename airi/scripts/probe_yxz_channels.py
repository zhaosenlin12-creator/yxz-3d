"""List every animation channel in a GLB with its real value range.

When a channel is authored but does not survive the export, the fastest way
to see it is one flat table: node, path, key count, and the actual numeric
excursion of the track.
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glb_json import read_glb  # noqa: E402

COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_FORMAT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_track(document, binary, index):
    accessor = document["accessors"][index]
    count = accessor["count"]
    components = TYPE_COMPONENTS[accessor["type"]]
    size = COMPONENT_SIZE[accessor["componentType"]]
    fmt = COMPONENT_FORMAT[accessor["componentType"]]
    view = document["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or components * size
    values = []
    for i in range(count):
        start = base + i * stride
        values.append(struct.unpack_from("<" + fmt * components, binary, start))
    return values


def main() -> None:
    path = Path(sys.argv[1])
    only = sys.argv[2] if len(sys.argv) > 2 else None
    document, binary = read_glb(path)
    names = [node.get("name", "") for node in document["nodes"]]

    print("== hierarchy ==")
    for index, node in enumerate(document["nodes"][:8]):
        print(f"  [{index}] {node.get('name')} T={node.get('translation')} "
              f"R={node.get('rotation')} children={node.get('children')}")

    for animation in document.get("animations", []):
        if only and animation.get("name") != only:
            continue
        print(f"== {animation.get('name')} ==")
        rows = []
        for channel in animation["channels"]:
            node_name = names[channel["target"]["node"]]
            path_name = channel["target"]["path"]
            sampler = animation["samplers"][channel["sampler"]]
            times = read_track(document, binary, sampler["input"])
            values = read_track(document, binary, sampler["output"])
            span = max(abs(v) for v in values[0]) if values else 0.0
            excursion = 0.0
            for i in range(len(values)):
                for j in range(len(values[0])):
                    column = [v[j] for v in values]
                    excursion = max(excursion, max(column) - min(column))
            rows.append((node_name, path_name, len(times), span, excursion))
        for node_name, path_name, count, span, excursion in rows:
            print(f"  {node_name:14s} {path_name:12s} keys={count:4d} "
                  f"max={span:.5f} range={excursion:.5f}")


if __name__ == "__main__":
    main()
