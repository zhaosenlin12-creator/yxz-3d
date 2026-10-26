import bpy, bmesh, sys
from mathutils import Vector
sys.path.insert(0, r"C:\kaifa_senlin\airi\scripts")
from repair_yxz_holes import boundary_loops, rim_order
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r"C:\kaifa_senlin\airi\docs\yxz-variants\v16\lit.glb")
body = max((o for o in bpy.context.scene.objects if o.type=="MESH"), key=lambda o: len(o.data.vertices))
bm = bmesh.new(); bm.from_mesh(body.data)
bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.0006)
bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
loops = boundary_loops(bm)
L = max(loops, key=len)
rim = rim_order(L)
mark = set()
for v in rim:
    for f in v.link_faces:
        mark.add(f)
print("LOOP", len(L), "faces", len(mark))
for obj in bpy.context.scene.objects:
    if obj.type != "MESH": continue
    obj.data.materials.clear()
    m = bpy.data.materials.new("flat"); m.use_nodes=True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value=(0.8,0.8,0.82,1)
    obj.data.materials.append(m)
    m2 = bpy.data.materials.new("mark"); m2.use_nodes=True
    m2.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value=(0.9,0.1,0.1,1)
    obj.data.materials.append(m2)
bm2 = bmesh.new(); bm2.from_mesh(body.data)
bm2.faces.ensure_lookup_table()
for f in bm2.faces:
    if f in mark:
        f.material_index = 1
bm2.to_mesh(body.data); body.data.update(); bm2.free()
import math
cam_d = bpy.data.cameras.new("c"); cam_d.type="ORTHO"; cam_d.ortho_scale=1.1
cam = bpy.data.objects.new("c", cam_d); bpy.context.scene.collection.objects.link(cam)
c = Vector((0.038,-0.001,0.094))
cam.location = c + Vector((0,-1,0))*2.0
cam.rotation_euler = (Vector(c)-cam.location).normalized().to_track_quat("-Z","Y").to_euler()
bpy.context.scene.camera = cam
k = bpy.data.lights.new("k", type="SUN"); k.energy=3.0
ko = bpy.data.objects.new("k", k); bpy.context.scene.collection.objects.link(ko); ko.rotation_euler=(0.9,0.2,0.4)
bpy.context.scene.render.resolution_x=900; bpy.context.scene.render.resolution_y=900
bpy.context.scene.render.filepath=r"C:\kaifa_senlin\airi\docs\yxz-audit\h31\loop999.png"
bpy.context.scene.render.image_settings.file_format="PNG"
bpy.ops.render.render(write_still=True)
print("DONE")
