"""Segment the YXZ source mesh into its actual connected parts.

Everything about this asset is a pose: one arm is raised in a wave, the other
hangs down holding a book, and the helmet carries wide ear discs.  Reading a
skeleton off the bounding box gets every one of those wrong, so the parts
have to be pulled apart and measured instead.

  blender -b -P scripts/probe_yxz_parts.py -- --source <glb> [--out <dir>]
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
    return sys.argv[sys.argv.index(name) + 1]


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
    parts = []
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [count]))
    for start, end in zip(starts, ends):
        index = order[start:end]
        parts.append((int(sorted_labels[start]), index))
    parts.sort(key=lambda item: -len(item[1]))
    return parts


def label(part_coords):
    """Guess what a part is from where it sits in the body."""
    centre = part_coords.mean(axis=0)
    high = part_coords.max(axis=0)
    height = centre[2]
    if height > 0.39:
        return "halo"
    if high[2] > 0.30 and abs(centre[0]) < 0.16:
        return "helmet"
    if height > 0.14 and abs(centre[1]) > 0.15:
        return "raised-arm"
    if abs(centre[1]) > 0.15 and centre[2] < 0.12:
        return "hanging-arm"
    if high[2] < -0.30:
        return "leg"
    return "body"


def render_views(mesh, out_dir):
    """Render the raw mesh from the axes that matter, to orient by eye."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 700
    scene.render.resolution_y = 900
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_cavity = True
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.07, 1)
    scene.world = world

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
    cam_data.ortho_scale = height * 1.2
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    track = cam.constraints.new("TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    for name, direction in (("negY", Vector((0, -1, 0))),
                            ("posY", Vector((0, 1, 0))),
                            ("posX", Vector((1, 0, 0))),
                            ("negX", Vector((-1, 0, 0)))):
        cam.location = centre + direction * height * 3
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"parts_view_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_PARTS_VIEW " + scene.render.filepath)


def render_component_colours(mesh, parts, out_dir):
    """Paint every large component a different colour and render the front.

    The skinning rules have to know which disconnected piece is the arm and
    which is the wing, and reading that off a bounding box is guesswork.
    A colour-coded render settles it in one look.
    """
    import colorsys

    out_dir.mkdir(parents=True, exist_ok=True)
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

    owner = {}
    for index, (label_id, vertex_index) in enumerate(parts[:26]):
        if len(vertex_index) < 40:
            continue
        material = bpy.data.materials.new(f"part_{index}")
        material.diffuse_color = (*colorsys.hsv_to_rgb(index / 26.0, 0.85, 0.95), 1.0)
        mesh.data.materials.append(material)
        for vertex in vertex_index:
            owner[int(vertex)] = index
        block = mesh.data.vertices[vertex_index[0]].co
        print(f"YXZ_COLOUR {index} n={len(vertex_index)} "
              + f"rgb={tuple(round(c, 2) for c in material.diffuse_color[:3])} "
              + "at " + str([round(float(v), 3) for v in block]))

    # Blender 5 keeps the material slot on the polygon, not the vertex.
    for polygon in mesh.data.polygons:
        polygon.material_index = owner.get(polygon.vertices[0], 0)

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
    for name, direction in (("front", Vector((1, 0, 0))), ("side", Vector((0, -1, 0)))):
        cam.location = centre + direction * height * 3
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"colour_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_COLOUR_VIEW " + scene.render.filepath)


def render_bands(mesh, out_dir, axis_name):
    """Colour the mesh by a coordinate band, so heights read off the image.

    Measuring a joint by looking at a point cloud is guesswork; measuring it
    by looking at a banded render is a lookup.  Each band is one legend
    entry, so the band a fingertip falls in gives its coordinate.
    """
    import colorsys

    out_dir.mkdir(parents=True, exist_ok=True)
    axis = {"x": 0, "y": 1, "z": 2}[axis_name]
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

    count = len(mesh.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    low = float(coords[:, axis].min())
    high = float(coords[:, axis].max())
    bands = 20
    step = (high - low) / bands
    for band in range(bands):
        material = bpy.data.materials.new(f"band_{band}")
        material.diffuse_color = (*colorsys.hsv_to_rgb(band / bands, 0.9, 0.95), 1.0)
        mesh.data.materials.append(material)
        print(f"YXZ_BAND {axis_name} {band} "
              f"[{low + band * step:+.3f},{low + (band + 1) * step:+.3f}] "
              + f"rgb={tuple(round(c, 2) for c in material.diffuse_color[:3])}")
    for polygon in mesh.data.polygons:
        value = float(coords[polygon.vertices[0], axis])
        polygon.material_index = int((value - low) / step)

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
    for name, direction in (("front", Vector((1, 0, 0))), ("side", Vector((0, -1, 0)))):
        cam.location = centre + direction * height * 3
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f"band_{axis_name}_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("YXZ_BAND_VIEW " + scene.render.filepath)


def main() -> None:
    source = value_after("--source")
    out_dir = value_after("--out")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    mesh = max(meshes, key=lambda o: len(o.data.vertices))
    count = len(mesh.data.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.data.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    print("YXZ_PARTS_VERTS " + str(count))
    print("YXZ_PARTS_BBOX min " + str([round(float(v), 4) for v in coords.min(axis=0)])
          + " max " + str([round(float(v), 4) for v in coords.max(axis=0)]))

    parts = components(mesh)
    print("YXZ_PARTS_COUNT " + str(len(parts)))
    for _, index in parts:
        block = coords[index]
        low = block.min(axis=0)
        high = block.max(axis=0)
        if len(index) < 40:
            continue
        print(f"YXZ_PART n={len(index)} "
              + "min " + str([round(float(v), 3) for v in low])
              + " max " + str([round(float(v), 3) for v in high])
              + " mean " + str([round(float(v), 3) for v in block.mean(axis=0)]))

    # Which way is the character facing?  The visor is the widest part of the
    # head along the facing axis, so that extent settles the sign.
    head = coords[(coords[:, 2] > 0.10) & (coords[:, 2] < 0.30)
                  & (np.abs(coords[:, 1]) < 0.12)]
    if len(head):
        print("YXZ_FACE_X min " + str(round(float(head[:, 0].min()), 4))
              + " max " + str(round(float(head[:, 0].max()), 4))
              + " mean " + str(round(float(head[:, 0].mean()), 4)))

    if out_dir:
        render_views(mesh, Path(out_dir))
        render_component_colours(mesh, parts, Path(out_dir))
        for axis_name in ("z", "x", "y"):
            render_bands(mesh, Path(out_dir), axis_name)

    # Which disconnected piece does each candidate bone actually capture?
    # This is the question the skinning rules turn on, and the distance
    # answers it without any guessing about what a part is called.
    chains = {
        "leftUpperArm": ((0.0, 0.135, 0.045), (0.030, 0.240, -0.070)),
        "leftLowerArm": ((0.030, 0.240, -0.070), (0.080, 0.300, -0.030)),
        "leftHand": ((0.080, 0.300, -0.030), (0.090, 0.352, 0.020)),
        "rightUpperArm": ((0.0, -0.135, 0.045), (0.010, -0.165, -0.060)),
        "rightLowerArm": ((0.010, -0.165, -0.060), (0.060, -0.175, -0.155)),
        "rightHand": ((0.060, -0.175, -0.155), (0.090, -0.190, -0.210)),
        "head": ((0.0, -0.040, 0.0), (0.0, -0.040, 0.360)),
    }
    segments = [(name, np.array(a), np.array(b))
                for name, (a, b) in chains.items()]
    for name, start, end in segments:
        direction = end - start
        length_sq = float(direction @ direction)
        if length_sq < 1e-12:
            continue
        for label_id, index in parts:
            if len(index) < 40:
                continue
            block = coords[index]
            t = np.clip(((block - start) @ direction) / length_sq, 0.0, 1.0)
            closest = start + t[:, None] * direction
            distance = np.linalg.norm(block - closest, axis=1)
            print(f"YXZ_CAPTURE {name} n={len(index)} "
                  + f"min={distance.min():.4f} mean={distance.mean():.4f} "
                  + "bbox " + str([round(float(v), 3) for v in block.min(axis=0)])
                  + ".." + str([round(float(v), 3) for v in block.max(axis=0)]))


if __name__ == "__main__":
    main()
