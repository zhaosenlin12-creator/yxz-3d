from PIL import Image
im = Image.open("docs/yxz-audit/deployed-blender-r122/tex-000.png")
w,h = im.size
box = (int(w*0.06), int(h*0.40), int(w*0.66), int(h*0.66))
c = im.crop(box)
c.resize((c.size[0]*2, c.size[1]*2), Image.LANCZOS).save("docs/yxz-audit/deployed-blender-r122/edge-tex.png")
print(im.size, c.size)
