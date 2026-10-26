"""Measure the mouth plate and the dish behind it, straight out of the VRM.

Everything about the "shattered" look comes down to numbers that can be
measured: how big the hole in the plate is, where the hole goes when a
viseme opens it, whether the plate ever sinks *into* the face it is
lying on (which is what makes it fight with the face for the same
pixels and shred the painted smile into shards), and whether the dish
behind the hole is a flat lid or a bowl that actually goes in.

Usage:
    python scripts/probe_yxz_mouth_geom.py <model.vrm>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patch_yxz_mouth_surface import Asset, Face  # noqa: E402


def ring_of(count: int) -> tuple[int, int]:
    """The plate is a grid of rings and segments; find the two numbers."""
    for segments in range(8, count, 8):
        if count % segments:
            continue
        rings = count // segments
        if 4 <= rings <= 64:
            return rings, segments
    raise SystemExit("cannot factor %d" % count)


def mesh_by_name(meshes, name):
    return next(i for i, mesh in enumerate(meshes) if mesh.get("name") == name)


def main() -> None:
    path = Path(sys.argv[1])
    asset = Asset(path)
    document = asset.document
    meshes = document["meshes"]

    body_index = next(
        i for i, mesh in enumerate(meshes)
        if str(mesh.get("name", "")).startswith("tripo_mesh"))
    mouth_index = mesh_by_name(meshes, "YXZ_Mouth")
    cavity_index = mesh_by_name(meshes, "YXZ_MouthCavity")

    face = Face(asset, body_index)
    report = {"model": path.name}

    mouth = meshes[mouth_index]
    primitive = mouth["primitives"][0]
    attributes = primitive["attributes"]
    base = asset.accessor(attributes["POSITION"]).astype(np.float64)
    count = base.shape[0]
    rings, segments = ring_of(count)
    grid = base.reshape(rings, segments, 3)
    centre = base.mean(axis=0)
    radial = np.linalg.norm(grid - centre, axis=2)
    report["plate"] = {
        "vertices": count,
        "rings": rings,
        "segments": segments,
        "centre": np.round(centre, 4).tolist(),
        "holeRadiusMin": round(float(radial[0].min()), 5),
        "holeRadiusMax": round(float(radial[0].max()), 5),
        "outerRadius": round(float(radial[-1].mean()), 5),
        "hasUv": "TEXCOORD_0" in attributes,
        "material": document["materials"][primitive["material"]].get("name"),
        "targets": len(primitive.get("targets", [])),
    }

    reach = float(np.abs(base - centre).max()) + 0.06
    candidates = face.near(centre, reach)
    surface, normals, uvs, distance = face.project(base, candidates)
    unit = normals / np.linalg.norm(normals, axis=1, keepdims=True)
    signed = ((base - surface) * unit).sum(axis=1)
    report["plate"]["standOff"] = {
        "min": round(float(signed.min()), 5),
        "mean": round(float(signed.mean()), 5),
        "max": round(float(signed.max()), 5),
    }

    expression = document.get("extensions", {}).get("VRMC_vrm", {}) \
        .get("expressions", {})
    morph_names = {}
    for group_name in ("preset", "custom"):
        groups = expression.get(group_name, {})
        if isinstance(groups, dict):
            groups = list(groups.values())
        for group in groups:
            for key, value in group.items():
                if isinstance(value, dict) and "morphTarget" in value:
                    morph_names[value["morphTarget"]] = key

    visemes = []
    for index, target in enumerate(primitive.get("targets", [])):
        delta = asset.accessor(target["POSITION"]).astype(np.float64)
        moved = base + delta
        moved_grid = moved.reshape(rings, segments, 3)
        moved_radial = np.linalg.norm(
            moved_grid - moved_grid.mean(axis=1, keepdims=True), axis=2)
        moved_centre = moved.mean(axis=0)
        signed_moved = ((moved - surface) * unit).sum(axis=1)
        visemes.append({
            "index": index,
            "name": morph_names.get(index, "?"),
            "maxDelta": round(float(np.linalg.norm(delta, axis=1).max()), 5),
            "holeRadiusMin": round(float(moved_radial[0].min()), 5),
            "holeRadiusMax": round(float(moved_radial[0].max()), 5),
            "holeMoved": round(float(
                np.linalg.norm(moved_grid[0] - grid[0], axis=1).mean()), 5),
            "centreShift": round(float(np.linalg.norm(moved_centre - centre)), 5),
            "sunkBelowFace": int((signed_moved < 0).sum()),
            "deepestSink": round(float(signed_moved.min()), 5),
            "ringOrderBroken": bool(
                (np.diff(moved_radial.mean(axis=1)) < 0).any()),
        })
    report["visemes"] = visemes

    cavity = meshes[cavity_index]
    cavity_primitive = cavity["primitives"][0]
    cavity_attributes = cavity_primitive["attributes"]
    cavity_positions = asset.accessor(
        cavity_attributes["POSITION"]).astype(np.float64)
    cavity_material = document["materials"][cavity_primitive["material"]]
    report["dish"] = {
        "vertices": int(cavity_positions.shape[0]),
        "hasUv": "TEXCOORD_0" in cavity_attributes,
        "material": cavity_material.get("name"),
        "baseColorTexture": cavity_material.get(
            "pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index"),
        "bboxMin": np.round(cavity_positions.min(axis=0), 4).tolist(),
        "bboxMax": np.round(cavity_positions.max(axis=0), 4).tolist(),
        "radiusMax": round(float(np.linalg.norm(
            cavity_positions - cavity_positions.mean(axis=0), axis=1).max()), 5),
    }
    mtoon = cavity_material.get("extensions", {}).get("VRMC_materials_mtoon", {})
    report["dish"]["mtoon"] = {
        "rim": mtoon.get("parametricRimColorFactor"),
        "rimMix": mtoon.get("rimLightingMixFactor"),
        "toony": mtoon.get("shadingToonyFactor"),
    }

    print("YXZ_MOUTH_GEOM " + json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
