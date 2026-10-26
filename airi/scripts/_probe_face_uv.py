import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face

a = Asset(Path("docs/yxz-variants/r138-mouth-safe/yxz.vrm")); d=a.document
bi = next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face = Face(a, bi)
mi = next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
pr = d["meshes"][mi]["primitives"][0]
pos = a.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
uvs = a.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
centre = pos[:144].mean(axis=0)
print("mouth centre", np.round(centre,4))
# face vertices near the mouth
n = np.linalg.norm(face.positions - centre, axis=1)
near = np.nonzero(n < 0.012)[0]
print("face verts within 12mm:", len(near))
fu = face.uvs[near]
W=H=4096
print("their uv range: u %.3f..%.3f  v %.3f..%.3f"%(fu[:,0].min(),fu[:,0].max(),fu[:,1].min(),fu[:,1].max()))
print("their pixel range: x %.0f..%.0f y %.0f..%.0f"%(fu[:,0].min()*W,fu[:,0].max()*W,(1-fu[:,1].max())*H,(1-fu[:,1].min())*H))
print("plate uv range: u %.3f..%.3f v %.3f..%.3f"%(uvs[:,0].min(),uvs[:,0].max(),uvs[:,1].min(),uvs[:,1].max()))
# normals of those face verts: front facing?
fn = face.normals[near]
print("normal z: min %.3f max %.3f ; fraction front-facing %.2f"%(fn[:,2].min(), fn[:,2].max(), (fn[:,2]>0).mean()))
print("their 3d z: min %.4f max %.4f"%(face.positions[near][:,2].min(), face.positions[near][:,2].max()))
print("plate z: %.4f..%.4f"%(pos[:,2].min(), pos[:,2].max()))
# sample a few face verts with their uv
for i in near[:6]:
    print("  v %+0.4f %+0.4f %+0.4f  uv %.4f %.4f -> px %6.0f %6.0f  n %+.2f %+.2f %+.2f"%(
        face.positions[i][0],face.positions[i][1],face.positions[i][2],face.uvs[i][0],face.uvs[i][1],
        face.uvs[i][0]*W,(1-face.uvs[i][1])*H,*face.normals[i]))
