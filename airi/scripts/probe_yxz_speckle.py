"""Work out what the speckle on the visor is made of.

The speckle survived every material change, so it is not the texture and
not the outline pass.  Two kinds of geometry can still produce it:

 * two front-facing sheets that lie on top of each other.  Both are drawn,
   their depths are almost equal, and the depth test flips between them
 * one sheet that folds over itself, so the same thing happens inside a
   single blob

The difference matters: the first is fixed by dropping a sheet, the second
by welding the fold away.  This counts both, separately, inside a region
of the model.

Usage: python scripts/probe_yxz_speckle.py <model.glb> [--min-y 0.70]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_json import read_glb  # noqa: E402
from probe_yxz_overlap import islands, load_meshes  # noqa: E402


def main():
    path = Path(sys.argv[1])
    min_y = 0.70
    if "--min-y" in sys.argv:
        min_y = float(sys.argv[sys.argv.index("--min-y") + 1])
    distance_limit = 0.006
    if "--distance" in sys.argv:
        distance_limit = float(sys.argv[sys.argv.index("--distance") + 1])

    document, meshes = load_meshes(path)
    report = {"file": str(path), "min_y": min_y, "distance": distance_limit}

    for entry in meshes:
        positions = entry["position"]
        indices = entry["indices"]
        if indices is None:
            indices = np.arange(positions.shape[0], dtype=np.int64)
        triangles = indices.reshape(-1, 3)
        labels = islands(positions, indices)

        corners = positions[triangles]
        face_normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        length = np.maximum(np.linalg.norm(face_normal, axis=1), 1e-12)
        unit = face_normal / length[:, None]
        area = length * 0.5
        # The exported asset faces +Z, so a front-facing triangle is one
        # whose normal points back at the camera.
        front = unit[:, 2] > 0
        centroids = corners.mean(axis=1)

        region = centroids[:, 1] > min_y
        selected = np.nonzero(region)[0]
        report["mesh"] = entry["mesh"]
        report["bounds_min"] = [round(float(v), 4) for v in positions.min(axis=0)]
        report["bounds_max"] = [round(float(v), 4) for v in positions.max(axis=0)]
        report["triangles_in_region"] = int(selected.size)
        report["front_facing_in_region"] = int((front & region).sum())
        report["area_in_region"] = round(float(area[region].sum()), 8)

        # Bucket the front-facing triangles of the region.
        cell = distance_limit
        keys = np.floor(centroids[selected] / cell).astype(np.int64)
        table = defaultdict(list)
        for index, key in zip(selected.tolist(), map(tuple, keys)):
            table[key].append(index)

        cross_island = 0
        same_island = 0
        cross_pairs = set()
        distances = []
        affected_area = 0.0
        offsets = [(-1, 0, 1)] * 3
        for index in selected.tolist():
            if not front[index]:
                continue
            base = np.floor(centroids[index] / cell).astype(np.int64)
            for dx in offsets[0]:
                for dy in offsets[1]:
                    for dz in offsets[2]:
                        for other in table.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                            if other <= index:
                                continue
                            if not front[other]:
                                continue
                            # Two triangles that share a vertex are just
                            # neighbours in the same sheet.
                            if set(triangles[index].tolist()) & set(triangles[other].tolist()):
                                continue
                            distance = float(np.linalg.norm(centroids[index] - centroids[other]))
                            if distance > distance_limit:
                                continue
                            distances.append(distance)
                            if labels[index] != labels[other]:
                                cross_island += 1
                                cross_pairs.add((int(labels[index]), int(labels[other])))
                            else:
                                same_island += 1
                            affected_area += area[index] + area[other]

        distances = np.array(distances) if distances else np.array([0.0])
        report.update({
            "overlapping_front_pairs_cross_island": cross_island,
            "overlapping_front_pairs_same_island": same_island,
            "cross_island_pair_count": len(cross_pairs),
            "top_cross_island_pairs": [
                {"islands": list(pair)}
                for pair in list(cross_pairs)[:10]
            ],
            "overlap_distance_min": round(float(distances.min()), 8),
            "overlap_distance_mean": round(float(distances.mean()), 8),
            "affected_area": round(float(affected_area), 8),
            "affected_area_fraction": round(
                float(affected_area / max(area[region].sum(), 1e-12)), 4),
        })
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
