import bpy, bmesh, numpy as np, os, sys
from mathutils import Vector
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from repair_yxz_holes import boundary_loops, rim_order
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "docs", "yxz-variants", "v16", "lit.glb")))
body = max((o for o in bpy.context.scene.objects if o.type=="MESH"), key=lambda o: len(o.data.vertices))
bm = bmesh.new(); bm.from_mesh(body.data)
bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.0006)
bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
c = Vector((0.038,-0.001,0.094))
head = [v.co.copy() for v in bm.verts if (v.co-c).length < 0.34]
arr = np.array([[p.x,p.y,p.z] for p in head])
print("HEAD bbox", arr.min(axis=0).round(4), arr.max(axis=0).round(4), len(head))
d = np.array([(p-c).length for p in head])
print("HEAD dist pct", [round(float(np.percentile(d,q)),4) for q in (5,25,50,75,90,95,99)])
loops = boundary_loops(bm)
for L in sorted(loops, key=len, reverse=True)[:6]:
    rim = rim_order(L)
    pts = np.array([[v.co.x,v.co.y,v.co.z] for v in rim])
    dist = np.array([(v.co-c).length for v in rim])
    print("LOOP", len(rim), "box", pts.min(axis=0).round(4), pts.max(axis=0).round(4), "dist", round(float(dist.mean()),4), round(float(dist.min()),4), round(float(dist.max()),4))
