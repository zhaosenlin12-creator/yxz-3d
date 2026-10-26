"""Find the loose pieces of the scan: the components that are not the body.

The scan arrives as a couple of hundred blobs.  After the weld the
character is still not one shell: it is one big shell plus a long tail of
pieces that touch nothing, and a piece that touches nothing can be a
whole feature -- the halo's remains, a feather plate, a panel -- or it
can be a single triangle left lying on the face.

Which one it is does not follow from the atlas.  A rectangle of the
atlas finds a patch, and a patch is shared by the front and the back of
the helmet, so cutting a rectangle out of it cuts a hole in the cheek.
Reachability does find the piece, and a piece that is a component of its
own can be taken away whole.

This probe lists the small components, says where they are and how big
they are, and renders the ones in the head so they can be looked at
against the shell they are lying on.

Usage:
  blender -b -P scripts/probe_yxz_loose.py -- \
    --glb <glb> [--max-faces 40] [--out <png>] [--center x,y,z] [--yaw 90]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def components(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
    bm.faces.ensure_lookup_table()
    groups = []
    unvisited = set(bm.faces)
    while unvisited:
        seed = unvisited.pop()
        group = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if other is current or other not in unvisited:
                        continue
                    unvisited.discard(other)
                    group.append(other)
                    frontier.append(other)
        groups.append(group)
    return groups


def main() -> None:
    glb = value_after("--glb")
    max_faces = int(value_after("--max-faces", 40))
    out = value_after("--out")
    centre = Vector([float(part) for part in value_after("--center", "0.21,0.0,0.10").split(",")])
    yaw = float(value_after("--yaw", 90))
    scale = float(value_after("--scale", 0.42))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    groups = components(bm)
    groups.sort(key=len, reverse=True)
    main_group = groups[0]

    loose = [group for group in groups[1:] if len(group) <= max_faces]
    census = []
    for group in loose:
        cloud = np.array([list(face.calc_center_median()) for face in group])
        area = sum(face.calc_area() for face in group)
        census.append({
            "faces": len(group),
            "area": round(float(area), 7),
            "centre": [round(float(value), 4) for value in cloud.mean(axis=0)],
            "low": [round(float(value), 4) for value in cloud.min(axis=0)],
            "high": [round(float(value), 4) for value in cloud.max(axis=0)],
        })

    print("YXZ_LOOSE " + json.dumps({
        "totalComponents": len(groups),
        "mainFaces": len(main_group),
        "looseCount": len(loose),
        "looseFaces": sum(len(group) for group in loose),
        "singleFace": sum(1 for group in loose if len(group) == 1),
    }))
    for entry in sorted(census, key=lambda item: item["area"]):
        print("YXZ_LOOSE_PIECE " + json.dumps(entry))

    if out:
        keep = set(face.index for face in main_group)
        loose_index = set()
        for group in loose:
            for face in group:
                loose_index.add(face.index)
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH":
                continue
            obj.data.materials.clear()
            material = bpy.data.materials.new("flat")
            material.use_nodes = True
            shader = material.node_tree.nodes["Principled BSDF"]
            shader.inputs["Base Color"].default_value = (0.80, 0.82, 0.86, 1.0)
            shader.inputs["Roughness"].default_value = 0.7
            obj.data.materials.append(material)

        # The loose pieces are painted a flat red so they can be told apart
        # from the shell they are lying on.
        piece = bmesh.new()
        piece.from_mesh(body.data)
        piece.faces.ensure_lookup_table()
        target = [face for face in piece.faces if face.index in loose_index]
        bmesh.ops.delete(piece, geom=[face for face in piece.faces if face.index not in loose_index],
                         context="FACES")
        piece.to_mesh(body.data)
        piece.free()
        body.data.materials.clear()
        material = bpy.data.materials.new("loose")
        material.use_nodes = True
        shader = material.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = (0.95, 0.12, 0.18, 1.0)
        shader.inputs["Roughness"].default_value = 0.6
        body.data.materials.append(material)
        body.data.update()

        cam_data = bpy.data.cameras.new("loose")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = scale
        cam = bpy.data.objects.new("loose", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        angle = np.radians(yaw)
        turned = Vector((np.cos(angle), -np.sin(angle), 0.0))
        cam.location = centre + turned * 2.0
        look = (centre - cam.location).normalized()
        cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
        scene = bpy.context.scene
        scene.camera = cam

        key = bpy.data.lights.new("key", type="SUN")
        key.energy = 3.0
        key_obj = bpy.data.objects.new("key", key)
        scene.collection.objects.link(key_obj)
        key_obj.rotation_euler = (0.9, 0.2, 0.4)
        fill = bpy.data.lights.new("fill", type="AREA")
        fill.energy = 50.0
        fill.size = 2.0
        fill_obj = bpy.data.objects.new("fill", fill)
        scene.collection.objects.link(fill_obj)
        fill_obj.location = centre + Vector((-1.2, -1.4, 0.4))
        fill_obj.rotation_euler = (1.1, 0.0, -0.6)

        scene.render.resolution_x = 900
        scene.render.resolution_y = 900
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("YXZ_LOOSE_RENDERED " + str(out))

    bm.free()


if __name__ == "__main__":
    main()
