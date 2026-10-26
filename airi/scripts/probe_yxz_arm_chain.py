"""Walk the actual arm geometry and report the joint chain.

The YXZ asset ships with the left arm raised in a wave and the right arm
down holding a book, so a hand-authored skeleton is always a guess.  This
walks each arm with a greedy farthest-point chain and prints the waypoints,
which is enough to place shoulder, elbow, wrist and fingertips exactly.

  blender -b -P scripts/probe_yxz_arm_chain.py -- --source <glb> [--side left]
"""

from __future__ import annotations

import sys

import bpy
import numpy as np


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def bounds(block):
    """A compact min/max/mean summary of a vertex block."""
    return ("min " + str([round(float(v), 4) for v in block.min(axis=0)])
            + " max " + str([round(float(v), 4) for v in block.max(axis=0)])
            + " mean " + str([round(float(v), 4) for v in block.mean(axis=0)]))


def chain(points, start, step=0.035, reach=0.085):
    """Greedy farthest-point walk that cannot jump across a bend."""
    current = np.array(start, dtype=np.float64)
    trail = [current.copy()]
    for _ in range(40):
        delta = np.linalg.norm(points - current, axis=1)
        close = delta < reach
        if not close.any():
            break
        index = int(np.argmax(np.where(close, delta, -1.0)))
        if delta[index] < step * 0.9:
            break
        current = points[index]
        trail.append(current.copy())
    return trail


def main() -> None:
    source = value_after("--source")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    mesh = max((o for o in bpy.context.scene.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices))
    count = len(mesh.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3).astype(np.float64)
    x, y, z = coords[:, 0], coords[:, 1], coords[:, 2]

    # The raised arm is on the character's left, which is +Y in this frame.
    # The helmet ear disc on that side is a separate blob at head height, so
    # it is cut out with the head's own x range rather than with a z cutoff.
    raised = (y > 0.10) & (z > -0.02) & (z < 0.26) & (x < 0.13)
    raised = raised & ~((z > 0.20) & (np.abs(x) < 0.02))
    hanging = (y < -0.02) & (y > -0.16) & (z < 0.06) & (z > -0.24)

    for name, mask, start in (
            ("raised-left", raised, (0.0, 0.115, 0.035)),
            ("hanging-right", hanging, (0.0, -0.115, 0.035))):
        block = coords[mask]
        if not len(block):
            print("YXZ_CHAIN " + name + " empty")
            continue
        print(f"YXZ_CHAIN {name} n={len(block)} " + bounds(block))
        trail = chain(block, start)
        for index, point in enumerate(trail):
            print(f"YXZ_CHAIN_PT {name} {index} "
                  + str([round(float(v), 4) for v in point]))

    # The palm is the flat plate at the end of the raised arm.  Its extent
    # sets where the hand bone has to reach so the fingers do not stretch.
    palm = (y > 0.18) & (z > 0.17)
    if palm.any():
        block = coords[palm]
        print("YXZ_PALM n=" + str(len(block)) + " " + bounds(block))

    # Where the forearm meets the hand: the narrowest neck of the chain.
    neck = (y > 0.16) & (z > 0.10) & (z < 0.20)
    if neck.any():
        block = coords[neck]
        print("YXZ_FOREARM n=" + str(len(block)) + " " + bounds(block))

    # Occupancy maps.  The arm is a tube, so its silhouette in the (x, z)
    # plane says where the shoulder, elbow, wrist and fingertips are.
    arm = (y > 0.14) & (z > 0.00) & (z < 0.28) & (x > -0.03)
    maps = (
        ("XZ", (x, z), arm),
        ("YZ", (y, z), arm),
        ("XY", (x, y), arm),
    )
    for label, (axis_a, axis_b), mask in maps:
        if not mask.any():
            continue
        block = coords[mask]
        a_lo, a_hi = float(axis_a[mask].min()), float(axis_a[mask].max())
        b_lo, b_hi = float(axis_b[mask].min()), float(axis_b[mask].max())
        steps = 26
        a_edges = np.linspace(a_lo, a_hi, steps + 1)
        b_edges = np.linspace(b_lo, b_hi, steps + 1)
        print(f"YXZ_MAP {label} rows=b(top->bottom) cols=a(min->max) "
              f"a=[{a_lo:+.3f},{a_hi:+.3f}] b=[{b_lo:+.3f},{b_hi:+.3f}]")
        for bi in range(len(b_edges) - 2, -1, -1):
            row = []
            for ai in range(len(a_edges) - 1):
                cell = ((axis_a >= a_edges[ai]) & (axis_a < a_edges[ai + 1])
                        & (axis_b >= b_edges[bi]) & (axis_b < b_edges[bi + 1]))
                row.append(str(int(cell.sum())).rjust(5) if cell.any() else "    .")
            print(f"YXZ_MAP_ROW {label} b={b_edges[bi]:+.3f}..{b_edges[bi + 1]:+.3f} |"
                  + " ".join(row))
        print(f"YXZ_MAP_EDGES {label} "
              + " ".join(f"{v:+.3f}" for v in a_edges))

    # The medial line of the raised arm, sliced by height.  Only geometry
    # in front of the helmet counts, so the ear disc cannot be mistaken for
    # part of the limb.
    print("YXZ_SLICE z | n | centroid | y-range | x-range")
    z_lo, z_hi = 0.00, 0.21
    for step in range(14):
        centre = z_lo + (z_hi - z_lo) * step / 13.0
        band = (np.abs(z - centre) < 0.02) & (y > 0.15) & (x > 0.02)
        if not band.any():
            continue
        block = coords[band]
        print(f"YXZ_SLICE {centre:+.3f} n={len(block)} "
              + "c " + str([round(float(v), 4) for v in block.mean(axis=0)])
              + " y " + str([round(float(block[:, 1].min()), 3),
                             round(float(block[:, 1].max()), 3)])
              + " x " + str([round(float(block[:, 0].min()), 3),
                             round(float(block[:, 0].max()), 3)]))

    # The open palm: a flat plate facing the camera, so it is wide across x
    # and thin across y.
    palm = (y > 0.20) & (z > 0.18) & (z < 0.27) & (x > 0.04) & (x < 0.16)
    if palm.any():
        block = coords[palm]
        print("YXZ_PALMPLATE n=" + str(len(block)) + " " + bounds(block))
        tips = block[block[:, 2] > np.quantile(block[:, 2], 0.85)]
        print("YXZ_FINGERTIPS n=" + str(len(tips)) + " " + bounds(tips))

    # The medial line of a limb, read off by slicing across it.  The raised
    # arm runs mostly sideways, so slicing on y gives the joint positions
    # directly: the shoulder, the elbow bend, the wrist and the fingertips.
    for name, mask in (
            ("left", (y > 0.12) & (x > 0.03) & (x < 0.24) & (z > -0.16)
             & (z < 0.12)),
            ("right", (y < -0.02) & (y > -0.28) & (x > 0.02) & (x < 0.22)
             & (z > -0.36) & (z < 0.06))):
        if not mask.any():
            continue
        print(f"YXZ_MEDIAL {name}")
        axis = y if name == "left" else y
        low = float(axis[mask].min())
        high = float(axis[mask].max())
        for step in range(16):
            edge = low + (high - low) * step / 16.0
            band = mask & (axis >= edge) & (axis < edge + (high - low) / 16.0)
            if not band.any():
                continue
            block = coords[band]
            print(f"YXZ_MEDIAL_PT {name} y={edge:+.3f} n={len(block)} "
                  + "c " + str([round(float(v), 4) for v in block.mean(axis=0)])
                  + " x " + str([round(float(block[:, 0].min()), 3),
                                 round(float(block[:, 0].max()), 3)])
                  + " z " + str([round(float(block[:, 2].min()), 3),
                                 round(float(block[:, 2].max()), 3)]))


if __name__ == "__main__":
    main()
