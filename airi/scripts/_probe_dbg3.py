import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,"scripts")
from patch_yxz_mouth_surface import Asset, Face
a=Asset(Path("docs/yxz-variants/r143-mouth/yxz.vrm")); d=a.document
bi=next(i for i,m in enumerate(d["meshes"]) if str(m.get("name","")).startswith("tripo_mesh"))
face=Face(a,bi)
centre=np.array([0.0,0.0621,0.2501])
cand=face.near(centre,0.09)
tri=face.triangles[cand]
A=face.positions[tri[:,0]]; B=face.positions[tri[:,1]]; C=face.positions[tri[:,2]]
cen=(A+B+C)/3
m=(np.abs(cen[:,0])<0.005)&(np.abs(cen[:,1]-0.0621)<0.005)&(cen[:,2]>0.20)
k=np.nonzero(m)[0][0]
print("A",A[k],"B",B[k],"C",C[k])
print("centroid",cen[k])
AB=B[k]-A[k]; AC=C[k]-A[k]
print("AB",AB,"AC",AC)
d00=AB[0]**2+AB[1]**2; d01=AB[0]*AC[0]+AB[1]*AC[1]; d11=AC[0]**2+AC[1]**2
print("d00 %.6e d01 %.6e d11 %.6e denom %.6e"%(d00,d01,d11,d00*d11-d01*d01))
px,py=cen[k,0],cen[k,1]
p20=px-A[k,0]; p21=py-A[k,1]
print("p20 %.6e p21 %.6e"%(p20,p21))
print("d20 %.6e d21 %.6e"%(p20*AB[0]+p21*AB[1], p20*AC[0]+p21*AC[1]))
wb=(d11*(p20*AB[0]+p21*AB[1])-d01*(p20*AC[0]+p21*AC[1]))/(d00*d11-d01*d01)
wc=(d00*(p20*AC[0]+p21*AC[1])-d01*(p20*AB[0]+p21*AB[1]))/(d00*d11-d01*d01)
print("wb %.4f wc %.4f wa %.4f"%(wb,wc,1-wb-wc))
