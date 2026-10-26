import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
import numpy as np
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm"))
d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
T=face.triangles
cen=face.positions[T].mean(axis=1)
sel=(cen[:,2]>0.235)&(cen[:,1]>0.040)&(cen[:,1]<0.072)&(np.abs(cen[:,0])<0.038)
print("face triangles at the mouth:",sel.sum())
idx=np.nonzero(sel)[0]
uv=face.uvs
def area2(t):
    p=uv[t]; return np.abs((p[:,1,0]-p[:,0,0])*(p[:,2,1]-p[:,0,1])-(p[:,2,0]-p[:,0,0])*(p[:,1,1]-p[:,0,1]))
def signed(t):
    p=uv[t]; return (p[:,1,0]-p[:,0,0])*(p[:,2,1]-p[:,0,1])-(p[:,2,0]-p[:,0,0])*(p[:,1,1]-p[:,0,1])
A=area2(T[idx]); S=signed(T[idx])
print("uv area: median %.3e  p10 %.3e  p90 %.3e"%(np.median(A),np.percentile(A,10),np.percentile(A,90)))
print("uv signed area: positive %d negative %d"%(int((S>0).sum()),int((S<0).sum())))
big=np.nonzero(A>3*np.median(A))[0]
print("triangles with a much bigger uv patch:",len(big))
for k in big[:25]:
    t=idx[k]
    print("   tri %d cen %s uv area %.2e (median %.2e) uv %s"%(t,np.round(cen[t],4),A[k],np.median(A),np.round(uv[T[t]],4).tolist()))
