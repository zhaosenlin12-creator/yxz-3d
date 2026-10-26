"""Dump the raw animation channels of one node in a GLB/VRM.

The YXZ breath lives in the hips translation channel, and a channel can be
present in the file while carrying the bone's rest position instead of the
animated one.  Comparing the build output against the post-processed VRM
shows whether the loss happens in Blender's exporter or in our own
rewriter.
"""

from __future__ import annotations

import json
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
    wanted = sys.argv[2] if len(sys.argv) > 2 else "hips"
    document, binary = read_glb(path)
    names = [node.get("name", "") for node in document["nodes"]]

    print("== node table ==")
    for index, node in enumerate(document["nodes"]):
        if node.get("name") in (wanted,) or node.get("name", "").endswith(wanted):
            print(f"  [{index}] {node.get('name')} children={node.get('children')} "
                  f"T={node.get('translation')} R={node.get('rotation')} "
                  f"S={node.get('scale')}")

    for animation in document.get("animations", []):
        print(f"== animation {animation.get('name')} ==")
        for channel in animation["channels"]:
            node_index = channel["target"]["node"]
            node_name = names[node_index]
            if node_name != wanted:
                continue
            path_name = channel["target"]["path"]
            sampler = animation["samplers"][channel["sampler"]]
            times = read_track(document, binary, sampler["input"])
            values = read_track(document, binary, sampler["output"])
            print(f"  {node_name}.{path_name} interp={sampler.get('interpolation')} "
                  f"input={sampler['input']} output={sampler['output']} "
                  f"keys={len(times)}")
            for index, (time, value) in enumerate(zip(times, values)):
                if index < 4 or index >= len(times) - 3:
                    print(f"     t={time[0]:.3f} v={[round(c, 5) for c in value]}")
                elif index == 4:
                    print("     ...")


if __name__ == "__main__":
    main()
