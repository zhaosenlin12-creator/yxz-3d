import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "scripts")
from patch_yxz_mouth_surface import Asset, Face

path = Path(sys.argv[1])
a = Asset(path); d = a.document
for i, m in enumerate(d["meshes"]):
    nm = m.get("name", "")
    if nm in ("YXZ_Mouth", "YXZ_MouthCavity"):
        pr = m["primitives"][0]
        P = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
        print("%-16s verts %6d  bbox x %+.4f..%+.4f  y %+.4f..%+.4f  z %+.4f..%+.4f" % (
            nm, len(P), P[:,0].min(), P[:,0].max(), P[:,1].min(), P[:,1].max(), P[:,2].min(), P[:,2].max()))
        mat = pr.get("material")
        print("   material", d["materials"][mat].get("name") if mat is not None else None)
        if mat is not None:
            mtl = d["materials"][mat]
            print("   baseColor", mtl.get("pbrMetallicRoughness", {}).get("baseColorFactor"))
            print("   has baseColorTexture:", "baseColorTexture" in mtl.get("pbrMetallicRoughness", {}))
            print("   doubleSided", mtl.get("doubleSided"), "alphaMode", mtl.get("alphaMode"))

bi = next(i for i, m in enumerate(d["meshes"]) if str(m.get("name", "")).startswith("tripo_mesh"))
face = Face(a, bi)
centre = np.array([0.0, 0.0621, 0.2501])
cand = face.near(centre, 0.09)
tri = face.triangles[cand]
A = face.positions[tri[:,0]]; B = face.positions[tri[:,1]]; C = face.positions[tri[:,2]]
# frontmost face z over the mouth footprint
from patch_yxz_mouth_surface import heightmap
xs, ys, dep, hit = heightmap(face, centre, 0.046, 0.032, 0.0002, cand)
print("face front z over mouth footprint: min %.4f max %.4f" % (np.nanmin(dep), np.nanmax(dep)))
print("face z at centre region: max %.4f" % np.nanmax(dep[np.abs(ys-0.0621) < 0.004]))
