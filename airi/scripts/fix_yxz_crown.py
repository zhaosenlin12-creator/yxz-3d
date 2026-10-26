"""Lay the torn crown sheet of the YXZ helmet back down on the head.

The scan came back with the top of the helmet split open along a long
ragged slit that runs most of the way round the crown, and with the
sheet that the slit let go of standing up off the back of the head like
a flap of skin.  It is that flap, and not the hole it came from, that
the camera sees: from the front it breaks the silhouette of the helmet
in two places and it is the reason the character reads as broken rather
than as a model of a toy.

The head is very nearly a ball -- the crown's faces sit on a sphere to
within a couple of millimetres -- so the flap has somewhere true to go
back to.  Every vertex of the flap is pushed back along the radius that
runs through it until it is on that sphere again, which puts the flap
back where it was peeled from, closes the slit, and leaves the head as
one smooth shell.

The sheet is not a solid: it is the outermost skin of a helmet, and it
is drawn with the same atlas as the rest of the head, so laying it down
costs the design nothing.  Only the flap's own vertices move, and they
move by less than a centimetre, so the skin, the rig and the animation
are untouched.

Usage:
  python scripts/fix_yxz_crown.py <source.vrm> <out.vrm> \
    [--centre 0,0.06,0.04] [--radius 0.3193] [--lift 0.0006] \
    [--threshold 0.3305] [--floor 0.10]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb, write_glb  # noqa: E402


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def accessor(document, data, index):
    a = document["accessors"][index]
    view = document["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    count = a["count"]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    return (np.frombuffer(data, dtype=dtype, count=count * width, offset=start)
            .reshape(count, width).copy(),
            start)


def store_accessor(document, data, index, values):
    """Write a float32 accessor back into the binary chunk, in place."""
    a = document["accessors"][index]
    view = document["bufferViews"][a["bufferView"]]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    encoded = np.asarray(values, dtype="<f4").tobytes()
    return data[:start] + encoded + data[start + len(encoded):]


def main():
    source = Path(value_after("source", sys.argv[1] if len(sys.argv) > 1 else ""))
    output = Path(value_after("output", sys.argv[2] if len(sys.argv) > 2 else ""))
    centre = np.array([float(part) for part in
                       value_after("centre", "0,0.06,0.04").split(",")])
    radius = float(value_after("radius", "0.3193"))
    lift = float(value_after("lift", "0.0006"))
    threshold = float(value_after("threshold", "0.3305"))
    floor = float(value_after("floor", "0.10"))
    report_only = "--report-only" in sys.argv

    document, data = read_glb(source)
    primitive = document["meshes"][0]["primitives"][0]
    positions, _ = accessor(document, data, primitive["attributes"]["POSITION"])
    normals, _ = accessor(document, data, primitive["attributes"]["NORMAL"])

    offset = positions - centre
    distance = np.linalg.norm(offset, axis=1)
    # The flap is the sheet that stands off the ball.  The crown's own
    # faces sit on the ball to within a few millimetres, so the sheet is
    # the part that is further out than that.
    flap = (distance > threshold) & (positions[:, 1] > floor)
    print("YXZ_CROWN flapVertices=%d of %d" % (int(flap.sum()), len(positions)))
    if not flap.any():
        print("YXZ_CROWN nothing to do")
        return

    moved = positions.copy()
    direction = offset[flap] / distance[flap][:, None]
    moved[flap] = centre + direction * (radius + lift)
    drift = np.linalg.norm(moved[flap] - positions[flap], axis=1)
    print("YXZ_CROWN movedMax=%.5f movedMean=%.5f" % (drift.max(), drift.mean()))

    # On a ball the normal is the radius, so the flap's shading after it
    # has been laid down is the same shading the crown around it has.
    fixed = normals.copy()
    fixed[flap] = direction

    if report_only:
        print("YXZ_CROWN report only")
        return

    data = store_accessor(document, data, primitive["attributes"]["POSITION"], moved)
    data = store_accessor(document, data, primitive["attributes"]["NORMAL"], fixed)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, data)
    print("YXZ_CROWN written " + str(output))


if __name__ == "__main__":
    main()
