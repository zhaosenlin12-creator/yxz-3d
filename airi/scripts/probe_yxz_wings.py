"""What the wings are made of.

The wings are the largest piece of the character that still reads as
unfinished: flat grey cards where the design calls for white feathers.  The
grey is the tell.  Nothing else on the model is grey, so whatever the
wings are sampling in the atlas is not the paint that was designed for
them, and knowing which material they use and which part of the atlas they
reach for says whether that is a texture the model can be pointed at or a
flat colour that has to be given to them.

Usage:
  blender -b -P scripts/probe_yxz_wings.py -- <glb> [--y 0.17]
  [--low -0.06] [--high 0.16]
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def span(corners, axis):
    low = round(min(c[axis] for c in corners), 3)
    high = round(max(c[axis] for c in corners), 3)
    return [low, high]


def main():
    source = value_after("--source")
    reach = float(value_after("--y", "0.17"))
    low = float(value_after("--low", "-0.06"))
    high = float(value_after("--high", "0.16"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        uv_data = mesh.uv_layers.active.data if mesh.uv_layers.active else None
        wanted = [p for p in mesh.polygons
                  if abs(p.center.y) >= reach and low <= p.center.z <= high]
        names = [slot.name if slot else None for slot in mesh.materials]
        report = {"mesh": obj.name, "materials": names,
                  "polygons": len(wanted),
                  "area": round(sum(p.area for p in wanted), 5)}
        counts = {}
        corners = []
        flat = []
        normals = []
        for polygon in wanted:
            key = str(polygon.material_index)
            counts[key] = counts.get(key, 0) + 1
            corners.extend([mesh.vertices[i].co for i in polygon.vertices])
            if uv_data is not None:
                flat.extend([uv_data[i].uv for i in polygon.loop_indices])
            normals.append(tuple(polygon.normal))
        report["byMaterial"] = counts
        if flat:
            report["uvMin"] = [round(min(u.x for u in flat), 3),
                               round(min(u.y for u in flat), 3)]
            report["uvMax"] = [round(max(u.x for u in flat), 3),
                               round(max(u.y for u in flat), 3)]
        if corners:
            report["box"] = [span(corners, 0), span(corners, 1), span(corners, 2)]
        if normals:
            report["meanNormal"] = [round(sum(n[i] for n in normals) / len(normals), 3)
                                   for i in range(3)]
        print("WINGS " + json.dumps(report))


main()
