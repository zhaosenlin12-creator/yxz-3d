"""Put the intact original head back into the shipped YXZ avatar.

The cleanup pass that removed the scan's stray flakes also took the
top of the helmet with it: the crown of the scan was peeled open, and
the pass that removed the peel was measured against the peel, so the
piece that was actually needed went as well.  The result was a head
with a hole in it and a rim of teeth around the hole.

The untouched model is still on disk from the original build.  Its
crown is closed, its visor is whole, and it sits in exactly the same
coordinates as the shipped one - the two share every vertex that
survived the cleanup.  So the repair is not a rebuild: it is the
original mesh put back into the shipped file, keeping everything the
shipped file added after the mesh was last touched - the halo, the
eye control, the patched texture, the animations and the VRM 1.0
extension the app needs.

Usage:
  python scripts/restore_yxz_pristine_mesh.py <pristine.vrm> <shipped.vrm> <out.vrm> [--dry-run]
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


def decode(document, data, index):
    a = document["accessors"][index]
    view = document["bufferViews"][a["bufferView"]]
    dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    count = a["count"] * width
    return np.frombuffer(data, dtype=dtype, count=count, offset=start).reshape(a["count"], width).copy()


def main():
    pristine_path = Path(sys.argv[1])
    shipped_path = Path(sys.argv[2])
    output = Path(sys.argv[3])
    dry = "--dry-run" in sys.argv

    pdoc, pdata = read_glb(pristine_path)
    sdoc, sdata = read_glb(shipped_path)

    pprim = pdoc["meshes"][0]["primitives"][0]
    sprim = sdoc["meshes"][0]["primitives"][0]
    print("pristine attributes %s" % sorted(pprim["attributes"].keys()))
    print("shipped  attributes %s" % sorted(sprim["attributes"].keys()))
    if sorted(pprim["attributes"].keys()) != sorted(sprim["attributes"].keys()):
        raise SystemExit("attribute sets differ")
    if pprim.get("material") != sprim.get("material"):
        print("material differs: pristine=%s shipped=%s (keeping shipped)" % (
            pprim.get("material"), sprim.get("material")))

    ppos = decode(pdoc, pdata, pprim["attributes"]["POSITION"]).astype(np.float64)
    spos = decode(sdoc, sdata, sprim["attributes"]["POSITION"]).astype(np.float64)
    shared = len(set(map(tuple, np.round(ppos, 5))) & set(map(tuple, np.round(spos, 5))))
    print("pristine verts=%d shipped verts=%d shared=%d" % (len(ppos), len(spos), shared))
    if shared < 1000:
        raise SystemExit("the two meshes do not look like the same model")

    # The skeleton has to be the same one, or the restored crown will
    # be welded to the wrong bone.
    pskin = pdoc.get("skins", [{}])[0]
    sskin = sdoc.get("skins", [{}])[0]
    print("pristine joints=%d shipped joints=%d" % (
        len(pskin.get("joints", [])), len(sskin.get("joints", []))))
    if len(pskin.get("joints", [])) != len(sskin.get("joints", [])):
        raise SystemExit("skeletons differ in size")
    pjoints = decode(pdoc, pdata, pprim["attributes"]["JOINTS_0"]).astype(np.int64)
    sjoints = decode(sdoc, sdata, sprim["attributes"]["JOINTS_0"]).astype(np.int64)
    print("joint index range pristine=%d..%d shipped=%d..%d" % (
        pjoints.min(), pjoints.max(), sjoints.min(), sjoints.max()))
    if pjoints.max() >= len(sskin.get("joints", [])):
        raise SystemExit("pristine mesh is bound to bones the shipped file does not have")
    pweights = decode(pdoc, pdata, pprim["attributes"]["WEIGHTS_0"]).astype(np.float64)
    swords = decode(sdoc, sdata, sprim["attributes"]["WEIGHTS_0"]).astype(np.float64)
    print("weight sum pristine=%.4f..%.4f shipped=%.4f..%.4f" % (
        pweights.sum(axis=1).min(), pweights.sum(axis=1).max(),
        swords.sum(axis=1).min(), swords.sum(axis=1).max()))

    # Collect the buffer views the pristine mesh needs, then lay the
    # shipped file's binary out again around them.
    wanted_accessors = []
    for name, accessor_index in pprim["attributes"].items():
        wanted_accessors.append(("attribute:" + name, accessor_index))
    wanted_accessors.append(("indices", pprim["indices"]))

    wanted_views = {}
    new_accessors = {}
    for label, accessor_index in wanted_accessors:
        accessor = dict(pdoc["accessors"][accessor_index])
        view_index = accessor["bufferView"]
        if view_index not in wanted_views:
            view = pdoc["bufferViews"][view_index]
            if "byteStride" in view:
                raise SystemExit("interleaved buffer view, not supported")
            start = view.get("byteOffset", 0)
            blob = pdata[start:start + view["byteLength"]]
            wanted_views[view_index] = blob
        accessor["bufferView"] = view_index  # placeholder, fixed below
        new_accessors[label] = accessor

    view_map = {}
    for view_index, blob in wanted_views.items():
        view = dict(pdoc["bufferViews"][view_index])
        view_map[view_index] = len(sdoc["bufferViews"])
        view["byteOffset"] = 0
        view["byteLength"] = len(blob)
        sdoc["bufferViews"].append(view)

    accessor_map = {}
    for label, accessor in new_accessors.items():
        accessor["bufferView"] = view_map[accessor["bufferView"]]
        accessor_map[label] = len(sdoc["accessors"])
        sdoc["accessors"].append(accessor)

    for name, accessor_index in pprim["attributes"].items():
        sprim["attributes"][name] = accessor_map["attribute:" + name]
    sprim["indices"] = accessor_map["indices"]

    print("new main mesh verts=%d tris=%d" % (
        pdoc["accessors"][pprim["attributes"]["POSITION"]]["count"],
        pdoc["accessors"][pprim["indices"]]["count"] // 3))

    if dry:
        print("dry run, nothing written")
        return

    # Lay the binary out again: the original buffer views keep their
    # blobs, the restored ones are appended.
    fresh_blobs = {}
    for view_index, blob in wanted_views.items():
        fresh_blobs[view_map[view_index]] = blob

    chunks = []
    offset = 0
    for index, view in enumerate(sdoc["bufferViews"]):
        if index in fresh_blobs:
            blob = fresh_blobs[index]
        else:
            start = view.get("byteOffset", 0)
            blob = sdata[start:start + view["byteLength"]]
        padding = (-offset) % 4
        chunks.append(b"\x00" * padding)
        offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        chunks.append(blob)
        offset += len(blob)
    sdoc["buffers"] = [{"byteLength": offset}]
    data = b"".join(chunks)

    # Refresh the bounds the file advertises for its positions.
    position_accessor = sdoc["accessors"][sprim["attributes"]["POSITION"]]
    new_positions = decode(sdoc, data, sprim["attributes"]["POSITION"])
    position_accessor["min"] = new_positions.min(axis=0).tolist()
    position_accessor["max"] = new_positions.max(axis=0).tolist()

    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, sdoc, data)
    print("written " + str(output))


if __name__ == "__main__":
    main()
