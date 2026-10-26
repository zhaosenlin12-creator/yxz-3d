"""Measure the real amplitude of every animation clip in the YXZ VRM.

Runtime sampling in a headless browser under-reports motion because the render
loop is throttled, so the authoritative check reads the keyframe data
directly: how far each bone actually travels across a clip, in degrees and in
model units.
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
SAMPLE_RATE = 30.0


def read_track(document, binary, index):
    """Return (times, values) for one glTF accessor."""
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


def lerp_track(values, times, time):
    """Linear interpolation between the two surrounding keyframes."""
    if not times:
        return (0.0, 0.0, 0.0, 0.0)
    if time <= times[0][0]:
        return values[0]
    if time >= times[-1][0]:
        return values[-1]
    for i in range(1, len(times)):
        if times[i][0] >= time:
            span = times[i][0] - times[i - 1][0]
            t = 0.0 if span <= 0 else (time - times[i - 1][0]) / span
            low = values[i - 1]
            high = values[i]
            return tuple(a + (b - a) * t for a, b in zip(low, high))
    return values[-1]


def quat_angle_deg(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


def channel_amplitude(document, binary, animation, channel):
    """Total excursion of one channel, sampled every frame of the clip.

    The meaningful number is the angular *range* the joint travels through, not
    the change between adjacent frames: a pose that is held (a forearm resting
    across the chest, say) barely moves frame to frame while still being a
    large, readable pose.
    """
    target = channel["target"]
    sampler = animation["samplers"][channel["sampler"]]
    times = read_track(document, binary, sampler["input"])
    values = read_track(document, binary, sampler["output"])
    if not times:
        return 0.0, 0.0

    frames = int(times[-1][0] * SAMPLE_RATE) + 1
    poses = [lerp_track(values, times, frame / SAMPLE_RATE)
             for frame in range(frames + 1)]
    origin = poses[0]
    peak_rotation = 0.0
    peak_translation = 0.0
    for current in poses:
        if target["path"] == "rotation":
            peak_rotation = max(peak_rotation, quat_angle_deg(origin, current))
        elif target["path"] == "translation":
            peak_translation = max(peak_translation, math.dist(origin, current))
    return peak_rotation, peak_translation


def main() -> None:
    document, binary = read_glb(Path(sys.argv[1]))
    names = [node.get("name", "") for node in document["nodes"]]

    report = {}
    for animation in document.get("animations", []):
        rotations = {}
        translations = {}
        duration = 0.0
        for channel in animation["channels"]:
            node_name = names[channel["target"]["node"]]
            label = f"{channel['target']['path']}:{node_name}"
            sampler = animation["samplers"][channel["sampler"]]
            times = read_track(document, binary, sampler["input"])
            if times:
                duration = max(duration, times[-1][0])
            peak_rotation, peak_translation = channel_amplitude(
                document, binary, animation, channel)
            if channel["target"]["path"] == "rotation":
                rotations[label] = max(rotations.get(label, 0.0), peak_rotation)
            elif channel["target"]["path"] == "translation":
                translations[label] = max(
                    translations.get(label, 0.0), peak_translation)

        top_rotation = sorted(rotations.items(), key=lambda kv: -kv[1])[:6]
        top_translation = sorted(translations.items(), key=lambda kv: -kv[1])[:4]
        report[animation.get("name", "unnamed")] = {
            "durationSec": round(duration, 3),
            "channels": len(animation["channels"]),
            "bonesRotating": sum(1 for value in rotations.values() if value > 0.5),
            "peakRotationDeg": {key: round(value, 2) for key, value in top_rotation},
            "peakTranslation": {key: round(value, 4) for key, value in top_translation},
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
