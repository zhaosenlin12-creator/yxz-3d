"""
 * What is under the visor panel?
 *
 * The scan recorded the face twice: a head with an eye painted on it,
 * and a dark visor panel laid over the top of that head.  Where the
 * painted head stands proud of the panel it shows through, and what
 * shows through is a bar of light across the middle of the visor.
 *
 * `fix_yxz_visor_bump.py` pushes that head back and paints over the
 * eye, but the bar is still there, so the question is whether the bar
 * is part of the region that script found or whether it is something
 * the region missed.  This prints every face in front of the face with
 * the colour it wears in the atlas, so the two can be compared.
 *
 * Usage:
 *   blender -b -P scripts/probe_yxz_bump_bar.py -- \
 *     --glb <glb> [--centre 0,-0.29,0.133] [--radius 0.12]
 """

from __future__ import annotations

import json
import sys

import bpy
import bmesh
import numpy as np


def value_after(name: str, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def main() -> None:
    glb = value_after("--glb")
    centre = np.array([float(part) for part in
                       value_after("--centre", "0,-0.29,0.133").split(",")])
    radius = float(value_after("--radius", "0.12"))
    uv_rect = value_after("--uv")
    u0 = u1 = v0 = v1 = None
    if uv_rect:
        u0, v0, u1, v1 = [float(part) for part in uv_rect.split(",")]
    faces_arg = value_after("--faces")
    ball = value_after("--ball")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )
    colour = None
    for image in bpy.data.images:
        if image.name.startswith("Color"):
            colour = image
            break
    width, height = colour.size
    pixels = np.empty(height * width * 4, dtype=np.float32)
    colour.pixels.foreach_get(pixels)
    top_down = pixels.reshape(height, width, 4)[::-1]

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active

    def atlas_colour(face):
        us = [loop[uv_layer].uv.x for loop in face.loops]
        vs = [loop[uv_layer].uv.y for loop in face.loops]
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        x = min(width - 1, max(0, int(u * width)))
        y = min(height - 1, max(0, int((1.0 - v) * height)))
        return top_down[y, x, :3]

    # The test the bump script uses to find the painted eye.
    def is_cyan(rgb):
        r, g, b = (float(value) for value in rgb)
        return b > 0.70 and g > 0.60 and r < 0.70 and b - r > 0.18

    if ball:
        bx, by, bz, br = [float(part) for part in ball.split(",")]
        picked = []
        for face in bm.faces:
            position = np.array(face.calc_center_median())
            if float(np.linalg.norm(position - np.array([bx, by, bz]))) > br:
                continue
            picked.append({
                "index": face.index,
                "rgb": [round(float(value), 3) for value in atlas_colour(face)],
                "pos": [round(float(value), 4) for value in position],
                "uv": [
                    round(sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops), 4),
                    round(sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops), 4),
                ],
            })
        print("YXZ_BUMP_BALL " + json.dumps({
            "faces": len(picked),
            "min": [round(min(item["pos"][axis] for item in picked), 4) for axis in range(3)] if picked else None,
            "max": [round(max(item["pos"][axis] for item in picked), 4) for axis in range(3)] if picked else None,
            "uvMin": [round(min(item["uv"][axis] for item in picked), 4) for axis in range(2)] if picked else None,
            "uvMax": [round(max(item["uv"][axis] for item in picked), 4) for axis in range(2)] if picked else None,
            "sample": picked[:10],
        }))
        return

    if faces_arg:
        wanted = [int(part) for part in faces_arg.split(",")]
        picked = []
        for index in wanted:
            if index >= len(bm.faces):
                continue
            face = bm.faces[index]
            picked.append({
                "index": index,
                "rgb": [round(float(value), 3) for value in atlas_colour(face)],
                "pos": [round(float(value), 4) for value in face.calc_center_median()],
                "uv": [
                    round(sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops), 4),
                    round(sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops), 4),
                ],
            })
        print("YXZ_BUMP_FACES " + json.dumps({
            "total": len(bm.faces),
            "picked": picked,
        }))
        return

    if uv_rect:
        picked = []
        for face in bm.faces:
            hit = False
            for loop in face.loops:
                if u0 <= loop[uv_layer].uv.x <= u1 and v0 <= loop[uv_layer].uv.y <= v1:
                    hit = True
            if not hit:
                continue
            position = np.array(face.calc_center_median())
            rgb = atlas_colour(face)
            picked.append({
                "rgb": [round(float(value), 3) for value in rgb],
                "pos": [round(float(value), 4) for value in position],
                "normal": [round(float(value), 3) for value in face.normal],
            })
        lo = np.array([min(item["pos"][axis] for item in picked) for axis in range(3)])
        hi = np.array([max(item["pos"][axis] for item in picked) for axis in range(3)])
        print("YXZ_BUMP_UV " + json.dumps({
            "faces": len(picked),
            "min": [round(float(value), 4) for value in lo],
            "max": [round(float(value), 4) for value in hi],
            "samples": picked[:12],
        }))
        return

    groups = {}
    for face in bm.faces:
        position = np.array(face.calc_center_median())
        if float(np.linalg.norm(position - centre)) > radius:
            continue
        rgb = atlas_colour(face)
        r, g, b = (float(value) for value in rgb)
        if r > 0.75 and g > 0.78 and b > 0.85:
            key = "white"
        elif is_cyan(rgb):
            key = "cyan"
        elif b > 0.10 and b > r * 1.4:
            key = "blue"
        else:
            key = "other"
        entry = groups.setdefault(key, {"faces": 0, "samples": []})
        entry["faces"] += 1
        if len(entry["samples"]) < 6:
            entry["samples"].append({
                "rgb": [round(r, 3), round(g, 3), round(b, 3)],
                "pos": [round(float(v), 4) for v in position],
                "uv": [
                    round(sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops), 4),
                    round(sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops), 4),
                ],
            })

    for key, entry in sorted(groups.items()):
        print("YXZ_BUMP_GROUP " + key + " " + json.dumps(entry))


if __name__ == "__main__":
    main()
