"""Report the material slots of the YXZ mesh and which slots bound the face.

The Tripo export is a single 700k+ vertex mesh with a baked face texture, so the
only chance of getting real eyes and a real mouth is to find out whether the
visors, pupils and mouth are separate material slots that can be split out.

  blender -b -P scripts/probe_yxz_materials.py -- --glb <path>
"""

from __future__ import annotations

import json
import sys

import bpy


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    body = max(
        (o for o in bpy.context.scene.objects if o.type == "MESH"),
        key=lambda o: len(o.data.vertices),
    )
    mesh = body.data

    slots = []
    for slot in body.material_slots:
        mat = slot.material
        slots.append(
            {
                "name": mat.name if mat else None,
                "baseColor": [
                    round(v, 4) for v in (list(mat.diffuse_color) if mat else [0, 0, 0, 1])
                ],
            }
        )

    per_slot = [0] * len(slots)
    face_bounds = [None] * len(slots)
    for poly in mesh.polygons:
        slot_index = poly.material_index
        if slot_index >= len(per_slot):
            continue
        per_slot[slot_index] += 1
        xs, ys, zs = [], [], []
        for vi in poly.vertices:
            co = mesh.vertices[vi].co
            xs.append(co[0])
            ys.append(co[1])
            zs.append(co[2])
        box = (
            [round(min(xs), 4), round(max(xs), 4)],
            [round(min(ys), 4), round(max(ys), 4)],
            [round(min(zs), 4), round(max(zs), 4)],
        )
        current = face_bounds[slot_index]
        if current is None:
            face_bounds[slot_index] = box
        else:
            face_bounds[slot_index] = [
                [min(current[0][0], box[0][0]), max(current[0][1], box[0][1])],
                [min(current[1][0], box[1][0]), max(current[1][1], box[1][1])],
                [min(current[2][0], box[2][0]), max(current[2][1], box[2][1])],
            ]

    report = {
        "glb": glb,
        "mesh": mesh.name,
        "slotCount": len(slots),
        "slots": [
            {**slot, "polygons": per_slot[i], "bounds": face_bounds[i]}
            for i, slot in enumerate(slots)
        ],
    }
    print("YXZ_MATERIALS " + json.dumps(report))


if __name__ == "__main__":
    main()
