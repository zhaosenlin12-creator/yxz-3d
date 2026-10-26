from __future__ import annotations

import numpy as np


def interpolate_uv(
    point: tuple[float, float, float],
    triangle: tuple[tuple[float, float, float], ...],
    uvs: tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    """Return barycentric UV coordinates for a point on a triangle."""
    if len(triangle) != 3 or len(uvs) != 3:
        raise ValueError("a triangle needs exactly three vertices and UVs")

    a, b, c = (np.asarray(vertex, dtype=np.float64) for vertex in triangle)
    p = np.asarray(point, dtype=np.float64)
    ab = b - a
    ac = c - a
    normal = np.cross(ab, ac)
    denominator = float(np.dot(normal, normal))
    if denominator < 1e-12:
        return None

    # Project onto the triangle plane before solving the barycentric weights.
    p = p - normal * float(np.dot(p - a, normal) / denominator)
    v0 = ab
    v1 = ac
    v2 = p - a
    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = float(np.dot(v2, v0))
    d21 = float(np.dot(v2, v1))
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1e-12:
        return None
    weight_b = (d11 * d20 - d01 * d21) / denominator
    weight_c = (d00 * d21 - d01 * d20) / denominator
    weight_a = 1.0 - weight_b - weight_c
    return tuple(
        float(weight_a * uvs[0][axis]
              + weight_b * uvs[1][axis]
              + weight_c * uvs[2][axis])
        for axis in range(2)
    )
