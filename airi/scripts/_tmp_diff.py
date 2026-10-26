from PIL import Image, ImageChops
import numpy as np
a = Image.open("docs/yxz-audit/defect-fix-r120/1-baseline-face.png").convert("RGB")
b = Image.open("docs/yxz-audit/defect-fix-r120/3-rim-off-face.png").convert("RGB")
w, h = a.size
# the visor/chin boundary runs across the lower third
box = (int(w*0.10), int(h*0.38), int(w*0.62), int(h*0.58))
ca = a.crop(box); cb = b.crop(box)
ca.resize((ca.size[0]*2, ca.size[1]*2), Image.LANCZOS).save("docs/yxz-audit/defect-fix-r120/edge-base.png")
cb.resize((cb.size[0]*2, cb.size[1]*2), Image.LANCZOS).save("docs/yxz-audit/defect-fix-r120/edge-rimoff.png")
d = np.abs(np.asarray(a, dtype=int) - np.asarray(b, dtype=int)).sum(axis=2)
print("max diff", d.max(), "pixels>30:", int((d>30).sum()))
ys, xs = np.where(d > 40)
if len(xs):
    print("diff bbox x", xs.min(), xs.max(), "y", ys.min(), ys.max())
