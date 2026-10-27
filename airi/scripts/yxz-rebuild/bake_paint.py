"""Paint the model from the reference renders.

The character's face is not modelled, it is painted: a dark visor with two
cyan lights on it, a smile, a badge on the helmet, blue trim along every
seam.  All of that lives in the reference renders, and the mesh has none
of it -- a mesh without paint is a grey statue, which is exactly what the
stage showed before.

So the renders are projected back onto the model.  `fit_views.py` measured
where each render sits on the model; this takes that measurement and gives
every face of the model the colour of the render it is seen in.  A face is
seen in the view that looks most directly at it, so the front of the
character is painted by the front render, the back by the back render, and
the flanks by whichever render reaches them.

The result is one atlas: the three renders laid out in a grid, and every
face pointing into the cell of the render that painted it.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
import numpy as np


def strip_debris(mesh_obj, keep_faces=2000):
    """Drop the islands of the mesh that are not the character.

    The reconstruction carries a few hundred faces of leftovers from the
    ring above the head, which the shape model scattered over the model
    like confetti.  They are separate shells, so they are found by
    connectivity and deleted.
    """
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    bm.verts.ensure_lookup_table()
    seen = set()
    shells = []
    for vert in bm.verts:
        if vert.index in seen:
            continue
        stack = [vert]
        seen.add(vert.index)
        shell = []
        while stack:
            current = stack.pop()
            shell.append(current)
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
        shells.append(shell)
    shells.sort(key=len, reverse=True)

    removed = 0
    for shell in shells[1:]:
        faces = set()
        for vert in shell:
            faces.update(vert.link_faces)
        if len(faces) >= keep_faces:
            continue
        bmesh.ops.delete(bm, geom=list(faces), context="FACES")
        removed += len(faces)
    bm.to_mesh(mesh_obj.data)
    bm.free()
    mesh_obj.data.update()
    return removed


def _write_uvs(mesh, uv):
    layer = mesh.uv_layers[0] if mesh.uv_layers else mesh.uv_layers.new(name="UVMap")
    flat = uv.ravel()
    try:
        layer.uv.foreach_set("vector", flat)
    except AttributeError:
        layer.data.foreach_set("uv", flat)
    mesh.update()


def apply_paint(mesh_obj, bake_dir: Path):
    """Project the reference renders onto the model and give it a material."""
    bake_dir = Path(bake_dir)
    bake = json.loads((bake_dir / "bake.json").read_text(encoding="utf-8"))
    views = bake["views"]
    atlas = bake["atlas"]

    mesh = mesh_obj.data
    mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
    if count == 0:
        raise SystemExit("no triangles in the mesh")

    tri_verts = np.empty(count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tri_verts)
    tri_verts = tri_verts.reshape(-1, 3)
    tri_loops = np.empty(count * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", tri_loops)
    tri_loops = tri_loops.reshape(-1, 3)

    coords = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    # Blender's frame back into the frame the fit was measured in: Y up,
    # the character facing +Z.
    exported = np.stack([coords[:, 0], coords[:, 2], -coords[:, 1]], axis=1).astype(np.float64)

    corners = exported[tri_verts]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)

    names = list(views)
    cam = np.array([views[name]["cam"] for name in names], dtype=np.float64)
    right = np.array([views[name]["right"] for name in names], dtype=np.float64)
    up = np.array([views[name]["up"] for name in names], dtype=np.float64)
    scores = normals @ cam.T
    choice = np.argmax(scores, axis=1)
    best = scores[np.arange(count), choice]

    cell_w = float(atlas["cell_width"])
    cell_h = float(atlas["cell_height"])
    atlas_w = float(atlas["width"])
    atlas_h = float(atlas["height"])

    uv = np.zeros((len(mesh.loops), 2), dtype=np.float32)
    for index, name in enumerate(names):
        view = views[name]
        slot = atlas["slots"][name]
        take = choice == index
        if not take.any():
            continue
        # The fit was measured on a small grid; the render's own pixels
        # are the ones that matter.
        factor = cell_w / float(view["width"])
        scale = view["scale"] * factor
        tx = view["tx"] * factor
        ty = view["ty"] * factor
        points = exported[tri_verts[take]]
        px = (points @ right[index]) * scale + tx
        py = ty - (points @ up[index]) * scale
        ax = slot["column"] * cell_w + px
        ay = slot["row"] * cell_h + py
        # Keep the sample inside its own cell: a face that overhangs the
        # render's outline would otherwise read its neighbour's paint.
        left = slot["column"] * cell_w
        top = slot["row"] * cell_h
        ax = np.clip(ax, left + 0.5, left + cell_w - 0.5)
        ay = np.clip(ay, top + 0.5, top + cell_h - 0.5)
        cell_uv = np.stack([ax / atlas_w, 1.0 - ay / atlas_h], axis=2)
        loops = tri_loops[take]
        uv[loops[:, 0]] = cell_uv[:, 0]
        uv[loops[:, 1]] = cell_uv[:, 1]
        uv[loops[:, 2]] = cell_uv[:, 2]
        print("YXZ_PAINT " + name + " faces=" + str(int(take.sum()))
              + " direct=" + str(int((best[take] > 0.15).sum())))

    _write_uvs(mesh, uv)

    image = bpy.data.images.load(str(bake_dir / "atlas.png"))
    image.name = "YXZ_Atlas"
    image.pack()

    material = bpy.data.materials.get("tripo_body")
    if material is None:
        material = bpy.data.materials.new("tripo_body")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = next(node for node in nodes if "BSDF" in node.bl_idname)
    for node in list(nodes):
        if node.bl_idname == "ShaderNodeTexImage":
            nodes.remove(node)
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.location = (-320, 260)
    material.node_tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.34
    bsdf.inputs["Metallic"].default_value = 0.0
    mesh.materials.clear()
    mesh.materials.append(material)
    return {"faces": count, "material": material.name,
            "views": {name: int((choice == index).sum())
                      for index, name in enumerate(names)}}
