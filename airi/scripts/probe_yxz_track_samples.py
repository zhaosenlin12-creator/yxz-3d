"""Print the keyframes of one bone in one clip, as angles over time.

The motion layer needs to know the *shape* of a track before it can reuse
it: a wing that flaps once and rests reads as a living thing, a wing
that swings evenly forever reads as a fan.  This dumps the sampled
rotation of the named bones of the named clip, in degrees, so the shape
can be read off directly.

Usage:
  python scripts/probe_yxz_track_samples.py <model.vrm> <clip> <bone> [...]
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


def euler_degrees(quaternion):
    x, y, z, w = quaternion
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.degrees(math.atan2(sinr, cosr))
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.degrees(math.asin(sinp))
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.degrees(math.atan2(siny, cosy))
    return [round(roll, 2), round(pitch, 2), round(yaw, 2)]


def main() -> None:
    document, binary = read_glb(Path(sys.argv[1]))
    clip_name = sys.argv[2]
    wanted = set(sys.argv[3:])
    names = [node.get("name", "") for node in document["nodes"]]

    for animation in document.get("animations", []):
        if animation.get("name") != clip_name:
            continue
        for channel in animation["channels"]:
            node_name = names[channel["target"]["node"]]
            if node_name not in wanted:
                continue
            sampler = animation["samplers"][channel["sampler"]]
            times = [row[0] for row in read_track(document, binary, sampler["input"])]
            values = read_track(document, binary, sampler["output"])
            samples = []
            for time, value in zip(times, values):
                entry = {"t": round(time, 3)}
                if channel["target"]["path"] == "rotation":
                    entry["deg"] = euler_degrees(value)
                else:
                    entry["v"] = [round(component, 4) for component in value]
                samples.append(entry)
            print(json.dumps({
                "clip": clip_name,
                "bone": node_name,
                "path": channel["target"]["path"],
                "samples": samples,
            }))


if __name__ == "__main__":
    main()
