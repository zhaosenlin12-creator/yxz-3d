import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
a=Asset(Path("packages/stage-ui-three/src/assets/vrm/models/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
P=face.positions; T=face.triangles
n=len(P)
# neighbour lists
import collections
nbr=collections.defaultdict(list)
for t in T:
    for k in range(3):
        nbr[t[k]].append(t[(k+1)%3]); nbr[t[k]].append(t[(k+2)%3])
keys=np.array(sorted(nbr.keys()))
vals=np.array([nbr[k] for k in keys],dtype=object)
out=[]
for i,k in enumerate(keys):
    ns=np.array(nbr[k])
    if len(ns)==0: continue
    zs=P[ns,2]
    out.append((k, P[k,2]-zs.max(), zs.max()-zs.min(), len(ns)))
out=np.array(out)
sel=(P[keys,2]>0.235)&(P[keys,1]>0.040)&(P[keys,1]<0.080)&(np.abs(P[keys,0])<0.046)
sub=out[sel]
print("verts in the mouth region:",len(sub))
pro=sub[sub[:,1]>0.0012]
print("protruding by more than 1.2mm:",len(pro))
for row in pro[np.argsort(-pro[:,1])][:25]:
    k=int(row[0])
    print("   vert %6d at x %+.4f y %+.4f z %+.4f  stands %.2f mm in front of its neighbours (spread %.2f mm, %d neighbours)"%(k,P[k,0],P[k,1],P[k,2],row[1]*1000,row[2]*1000,int(row[3])))
