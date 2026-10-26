import re,sys
src=open("scripts/patch_yxz_mouth_surface.py",encoding="utf-8").read()
for name in ["def grid_indices","class Face"]:
    i=src.index(name)
    j=src.index("\nclass " if name.startswith("class") else "\ndef ",i+10)
    print(src[i:j][:3000]); print("-----")
