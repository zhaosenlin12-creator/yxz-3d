import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
from rebuild_yxz_mouth import heightmap

a=Asset(Path("docs/yxz-variants/r139-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
mi=next(i for i,m in enumerate(d["meshes"]) if m.get("name")=="YXZ_Mouth")
P=a.accessor(d["meshes"][mi]["primitives"][0]["attributes"]["POSITION"]).astype(np.float64)
centre=P[:144].mean(axis=0)
cand=face.near(centre,0.09)
xs,ys,depth,hit=heightmap(face,centre,0.060,0.030,0.0002,cand)
d2=np.diff(depth,axis=1)
bad=np.argwhere(np.abs(d2)>0.001)
print("cells with a depth step > 1mm:", len(bad))
for r,c in bad[:20]:
    print("   x %+0.4f y %+0.4f  z %.4f -> %.4f"%(xs[c], ys[r], depth[r,c], depth[r,c+1]))
# triangles near the mouth: their z spread
tri=face.triangles[cand]
cen=face.positions[tri].mean(axis=1)
m=np.linalg.norm(cen[:,:2]-centre[:2],axis=1)<0.03
print("triangles within 30mm:", m.sum())
zs=face.positions[tri[m]][:,:,2]
print("their z: min %.4f max %.4f"%(zs.min(), zs.max()))
nrm=face.normals[np.unique(tri[m].reshape(-1))]
print("vertex normals z: min %.3f max %.3f, front-facing %.2f"%(nrm[:,2].min(),nrm[:,2].max(),(nrm[:,2]>0).mean()))
# hole test: is the region covered by triangles in XY?
import collections
grid=collections.defaultdict(int)
for t in tri[m]:
    pts=face.positions[t][:,:2]
    x0,x1=pts[:,0].min(),pts[:,0].max(); y0,y1=pts[:,1].min(),pts[:,1].max()
    for gx in np.arange(math_floor:=np.floor(x0/0.002)*0.002, x1, 0.002):
        for gy in np.arange(np.floor(y0/0.002)*0.002, y1, 0.002):
            grid[(round(gx,3),round(gy,3))]+=1
print("2mm cells covered near mouth:", len(grid))
