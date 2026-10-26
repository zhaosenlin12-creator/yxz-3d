"""Highlight a handful of mesh parts so their identity can be read off.

The YXZ asset arrives as 229 disconnected blobs, and the skinning rules
have to decide what each blob is.  Reading that off a number is guesswork;
painting the blob and looking at the character is not.

  blender -b -P scripts/probe_yxz_isolate.py -- \
    --source <glb> --out <dir> --parts 11,8,9
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    index = sys.argv.index(name) + 1
    if index >= len(sys.argv):
        return default
    return sys.argv[index]


class Union:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def components(mesh):
    """Group vertices into connected components through the edge list."""
    count = len(mesh.data.vertices)
    groups = Union(count)
    for edge in mesh.data.edges:
        groups.union(edge.vertices[0], edge.vertices[1])
    labels = np.array([groups.find(i) for i in range(count)], dtype=np.int64)
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    boundaries = np.flatnonzero(np.diff(sorted_labels)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [count]))
    parts = []
    for start, end in zip(starts, ends):
        index = order[start:end]
        parts.append((int(sorted_labels[start]), index))
    parts.sort(key=lambda item: -len(item[1]))
    return parts


def main() -> None:
    source = value_after("--source")
    out_dir = Path(value_after("--out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [int(v) for v in value_after("--parts", "").split(",") if v.strip()]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    mesh = max((o for o in bpy.context.scene.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices))
    parts = components(mesh)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 760
    scene.render.resolution_y = 980
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.06, 0.08, 1)
    scene.world = world

    # The imported mesh already carries a material, so the slots we add
    # start at one; the polygon index has to point at the slot we added.
    body = bpy.data.materials.new("body")
    body.diffuse_color = (0.62, 0.64, 0.68, 1.0)
    mesh.data.materials.append(body)
    body_slot = len(mesh.data.materials) - 1
    highlight = bpy.data.materials.new("highlight")
    highlight.diffuse_color = (0.95, 0.25, 0.15, 1.0)
    mesh.data.materials.append(highlight)
    highlight_slot = len(mesh.data.materials) - 1

    owner = {}
    for index, (_label, vertex_index) in enumerate(parts):
        if len(vertex_index) < 12:
            continue
        block = np.array([mesh.data.vertices[int(v)].co[:] for v in vertex_index])
        print(f"YXZ_ALL_PART {index} n={len(vertex_index)} "
              + "min " + str([round(float(v), 3) for v in block.min(axis=0)])
              + " max " + str([round(float(v), 3) for v in block.max(axis=0)]))
    for index in wanted:
        if index >= len(parts):
            continue
        block = np.array([mesh.data.vertices[int(v)].co[:] for v in parts[index][1]])
        print(f"YXZ_ISOLATE_PART {index} n={len(parts[index][1])} "
              + "min " + str([round(float(v), 3) for v in block.min(axis=0)])
              + " max " + str([round(float(v), 3) for v in block.max(axis=0)]))
        for vertex in parts[index][1]:
            owner[int(vertex)] = 1
    for polygon in mesh.data.polygons:
        polygon.material_index = (highlight_slot if owner.get(polygon.vertices[0])
                                 else body_slot)

    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for corner in mesh.bound_box:
        for i in range(3):
            lo[i] = min(lo[i], corner[i])
            hi[i] = max(hi[i], corner[i])
    centre = Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    height = max(hi[i] - lo[i] for i in range(3))
    focus = bpy.data.objects.new("Focus", None)
    focus.location = centre
    scene.collection.objects.link(focus)
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.15
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    track = cam.constraints.new("TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    for name, direction in (("front", Vector((1, 0, 0))),
                            ("side", Vector((0, -1, 0)))):
        cam.location = centre + direction * height * 3
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"isolate_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_ISOLATE_VIEW " + scene.render.filepath)


if __name__ == "__main__":
    main()
