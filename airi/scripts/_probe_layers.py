import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
P=a.accessor(d["meshes"][mi]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
centre=P[:144].mean(axis=0)
tri=face.triangles
cen=face.positions[tri].mean(axis=1)
m=np.linalg.norm(cen[:,:2]-centre[:2],axis=1)<0.035
t=tri[m]
zs=face.positions[t][:,:,2]
zmin=zs.min(axis=1); zmax=zs.max(axis=1)
print("triangles within 35mm:", m.sum())
for lo,hi in [(0.240,0.246),(0.246,0.249),(0.249,0.252),(0.252,0.260)]:
    sel=(zmax>=lo)&(zmax<hi)
    print("  zmax in [%.3f,%.3f): %d tris"%(lo,hi,sel.sum()))
# the "front" layer: all three verts within 0.6mm of the max z of the local surface
front = (zmax - zmin) < 0.0015
print("flat-ish front triangles (zmax-zmin<1.5mm):", front.sum())
# their z range
print("   their zmax: %.4f..%.4f"%(zmax[front].min(), zmax[front].max()))
# the deeper ones
deep = ~front
print("deep triangles:", deep.sum(), "their zmax %.4f..%.4f zmin %.4f..%.4f"%(zmax[deep].min(),zmax[deep].max(),zmin[deep].min(),zmin[deep].max()))
# normals of deep ones
nn=face.normals[np.unique(t[deep].reshape(-1))]
print("   deep vert normal z: min %.3f max %.3f front %.2f"%(nn[:,2].min(),nn[:,2].max(),(nn[:,2]>0).mean()))
# XY extent of deep triangles
dpts=face.positions[t[deep]]
print("   deep tri XY x %.4f..%.4f y %.4f..%.4f"%(dpts[:,:,0].min(),dpts[:,:,0].max(),dpts[:,:,1].min(),dpts[:,:,1].max()))
fpts=face.positions[t[front]]
print("   front tri XY x %.4f..%.4f y %.4f..%.4f"%(fpts[:,:,0].min(),fpts[:,:,0].max(),fpts[:,:,1].min(),fpts[:,:,1].max()))
# is there a hole? coverage of a fine XY grid by front triangles only
import numpy as np
for tag, sel in (("front",front),("all",np.ones(len(t),bool))):
    pts=face.positions[t[sel]][:,:,:2]
    print(tag, "n tris", sel.sum())
