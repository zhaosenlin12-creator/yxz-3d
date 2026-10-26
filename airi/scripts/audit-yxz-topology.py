"""Inspect source/candidate topology without importing or rewriting the rig."""
import io
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from glb_json import read_glb


def accessor(doc, data, index):
    a = doc["accessors"][index]
    v = doc["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
    return np.ndarray(
        (a["count"], width), dtype=dtype, buffer=data,
        offset=v.get("byteOffset", 0) + a.get("byteOffset", 0),
        strides=(v.get("byteStride", dtype.itemsize * width), dtype.itemsize),
    ).copy()


def inspect(filename, output):
    doc, data = read_glb(filename)
    prim = max((p for m in doc["meshes"] for p in m["primitives"]),
               key=lambda p: doc["accessors"][p["attributes"]["POSITION"]]["count"])
    p = accessor(doc, data, prim["attributes"]["POSITION"])
    faces = accessor(doc, data, prim["indices"]).reshape(-1, 3)
    uv = accessor(doc, data, prim["attributes"]["TEXCOORD_0"])
    # UV seams use split vertices. Weld only in the analysis, never in the asset.
    _, ids = np.unique(np.round(p, 6), axis=0, return_inverse=True)
    edges = np.sort(np.concatenate([ids[faces[:, [0, 1]]], ids[faces[:, [1, 2]]], ids[faces[:, [2, 0]]]]), axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    mat = doc["materials"][prim["material"]]
    tex = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    image = doc["images"][doc["textures"][tex]["source"]]
    view = doc["bufferViews"][image["bufferView"]]
    offset = view.get("byteOffset", 0)
    im = Image.open(io.BytesIO(data[offset:offset + view["byteLength"]]))
    output.mkdir(parents=True, exist_ok=True)
    im.save(output / "atlas.png")
    np.savez_compressed(output / "mesh.npz", positions=p, faces=faces, uv=uv)
    report = {"path": filename, "vertices": len(p), "triangles": len(faces),
              "bounds": [p.min(0).tolist(), p.max(0).tolist()],
              "edgeMultiplicity": dict(Counter(counts.tolist())),
              "nodes": [{k: n[k] for k in ("name", "mesh", "translation", "rotation", "scale", "skin") if k in n}
                        for n in doc["nodes"] if "mesh" in n],
              "extensions": list(doc.get("extensions", {}))}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    inspect(sys.argv[1], Path(sys.argv[2]))
