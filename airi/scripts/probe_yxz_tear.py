"""How far a joint drags the mesh around it when it turns.

`probe_yxz_safe_bones.py` answers "does this joint own its geometry".
That is necessary but not sufficient: a joint can own almost all of its
vertices and still share a thin band with its neighbour, and that band
is the part that stretches when the joint turns against the neighbour.

So this measures the band.  For every vertex that carries any weight on
a joint, the share of that vertex the joint does *not* own is the part
that lags behind when the joint turns:

    deficit = 1 - weight_of_this_joint

Turning the joint by theta drags that vertex by `deficit * theta` away
from where the neighbouring joints would have put it.  Summed over the
vertices and divided by the count, the mean deficit is the average
angular lag, in degrees per degree of joint rotation, that the mesh
around that joint has to absorb.

    0.0   the joint owns all of its geometry: nothing to stretch
    0.05  a 10 degree turn makes the seam slip half a degree: invisible
    0.30  a 3 degree turn makes the seam slip a degree: a visible crease

Usage:
  python scripts/probe_yxz_tear.py <model.vrm|glb> [joint ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from probe_yxz_safe_bones import read_glb, accessor  # noqa: E402


def main() -> None:
    document, binary = read_glb(Path(sys.argv[1]))
    nodes = document["nodes"]
    names = [node.get("name", "") for node in nodes]
    only = set(sys.argv[2:]) or None

    # joint -> sum of deficits, count of influenced vertices, and the
    # joints it shares its vertices with.
    deficit_sum: dict[str, float] = defaultdict(float)
    influenced: dict[str, int] = defaultdict(int)
    rigid: dict[str, int] = defaultdict(int)
    partners: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    total_verts = 0

    for skin in document.get("skins", []):
        joint_nodes = skin["joints"]
        for node in nodes:
            if node.get("skin") != document["skins"].index(skin):
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
                    total_verts += 1
                    for slot, weight in enumerate(weight_row):
                        if weight <= 0.001:
                            continue
                        # `joint_row[slot]` is the index of the joint this
                        # weight belongs to; the slot itself is only a
                        # position in the four-weight list.
                        joint_name = names[joint_nodes[joint_row[slot]]]
                        if only is not None and joint_name not in only:
                            continue
                        deficit_sum[joint_name] += 1.0 - weight
                        influenced[joint_name] += 1
                        if weight >= 0.999:
                            rigid[joint_name] += 1
                        for other_slot, other_weight in enumerate(weight_row):
                            if other_slot == slot or other_weight <= 0.001:
                                continue
                            partners[joint_name][names[joint_nodes[joint_row[other_slot]]]] += other_weight

    report = {}
    for joint in sorted(deficit_sum):
        count = influenced[joint]
        mean = deficit_sum[joint] / count if count else 0.0
        top = sorted(partners[joint].items(), key=lambda kv: -kv[1])[:4]
        report[joint] = {
            "influenced": count,
            "rigid": rigid[joint],
            "meanDeficit": round(mean, 4),
            "lagDegPerDeg": round(mean, 4),
            "topPartners": [
                {"joint": name, "sharedWeight": round(weight, 1)} for name, weight in top
            ],
        }

    print(json.dumps({"totalVerts": total_verts, "joints": report}, indent=2))


if __name__ == "__main__":
    main()
