"""The cracks in the shell, drawn on the model so they can be seen.

The shell is a scan stitched from pieces, and where two pieces were cut
apart the surface stops: those are the open boundaries, and on screen
they are the cracks the background shows through.  A number says how
many of them there are; a picture says what shape they are, and the
shape is what decides how they are closed -- a hairline crack wants a
different repair from a seam that runs the whole length of the helmet.

So the open runs are copied into a mesh of their own, in red, and the
model is drawn from four sides and from above with the red on it.

Usage:
  blender -b -P scripts/probe_yxz_cracks_render.py -- \
    --glb <glb> --out <prefix> [--head-z 0.18]
"""

from __future__ import annotations

import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def open_runs(bm):
    """The runs of edges that have a face on only one side."""
    bm.faces.index_update()
    bm.edges.index_update()
    bm.verts.index_update()
    open_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    unvisited = {edge.index: edge for edge in open_edges}
    runs = []
    while unvisited:
        seed = unvisited.pop(min(unvisited))
        run = [seed]
        stack = [seed]
        while stack:
            current = stack.pop()
            for vertex in current.verts:
                for other in vertex.link_edges:
                    if len(other.link_faces) != 1:
                        continue
                    if other.index in unvisited:
                        del unvisited[other.index]
                        run.append(other)
                        stack.append(other)
        runs.append(run)
    return runs


def main():
    source = value_after("--glb")
    out = os.path.abspath(value_after("--out"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    head_z = float(value_after("--head-z", "0.18"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    body = max((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
               key=lambda obj: len(obj.data.vertices))

    bm = bmesh.new()
    bm.from_mesh(body.data)
    runs = open_runs(bm)

    # The runs belong to the head, so only the ones up there are drawn:
    # the cracks on the arms and legs are a different problem and a
    # different repair.
    head_runs = []
    for run in runs:
        coords = []
        for edge in run:
            for vertex in edge.verts:
                coords.append(list(vertex.co))
        points = np.array(coords)
        if points[:, 2].min() >= head_z:
            head_runs.append(run)
    print("YXZ_CRACK_RUNS " + str(len(head_runs)))

    # The crack is drawn as a thin ribbon laid along the open edge and
    # lifted a hair off the surface, so that it shows up without
    # fighting with the shell it belongs to.
    marked = bmesh.new()
    for run in head_runs:
        for edge in run:
            normal = Vector((0.0, 0.0, 0.0))
            for face in edge.link_faces:
                normal += face.normal
            if normal.length < 1e-9:
                normal = Vector((0.0, 0.0, 1.0))
            normal.normalize()
            along = edge.verts[1].co - edge.verts[0].co
            if along.length < 1e-9:
                continue
            along.normalize()
            across = normal.cross(along)
            if across.length < 1e-9:
                continue
            across.normalize()
            lift = normal * 0.0018
            half = across * 0.0014
            corners = []
            for vertex in (edge.verts[0], edge.verts[1]):
                middle = vertex.co + lift
                corners.append((marked.verts.new(middle - half),
                                marked.verts.new(middle + half)))
            marked.faces.new((corners[0][0], corners[0][1],
                              corners[1][1], corners[1][0]))

    mesh = bpy.data.meshes.new("cracks")
    marked.to_mesh(mesh)
    marked.free()
    marks = bpy.data.objects.new("cracks", mesh)
    bpy.context.scene.collection.objects.link(marks)
    material = bpy.data.materials.new("crack")
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = (0.9, 0.05, 0.05, 1.0)
    shader.inputs["Emission Color"].default_value = (0.9, 0.05, 0.05, 1.0)
    shader.inputs["Emission Strength"].default_value = 1.0
    mesh.materials.append(material)

    # The body is drawn in flat grey so that the red is the only thing
    # with colour in the picture.
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj is marks:
            continue
        grey = bpy.data.materials.new("body")
        grey.use_nodes = True
        shader = grey.node_tree.nodes["Principled BSDF"]
        shader.inputs["Base Color"].default_value = (0.75, 0.75, 0.78, 1.0)
        obj.data.materials.clear()
        obj.data.materials.append(grey)

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.95, 0.96, 0.97, 1.0)
    bpy.context.scene.world = world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 2.2
    key_obj = bpy.data.objects.new("key", key)
    scene.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.8, 0.2, 0.6)

    # The head is the region the runs were taken from, so the camera is
    # put on it directly.
    coords = []
    for run in head_runs:
        for edge in run:
            for vertex in edge.verts:
                coords.append(list(vertex.co))
    points = np.array(coords)
    low = points.min(axis=0)
    high = points.max(axis=0)
    centre = (low + high) * 0.5
    scale = float(max(high - low)) * 1.15
    print("YXZ_CRACK_BOX " + str([round(float(v), 3) for v in low])
          + " " + str([round(float(v), 3) for v in high]))

    views = {
        "x+": Vector((1.0, 0.0, 0.0)),
        "x-": Vector((-1.0, 0.0, 0.0)),
        "y+": Vector((0.0, 1.0, 0.0)),
        "y-": Vector((0.0, -1.0, 0.0)),
        "top": Vector((0.25, -0.25, 1.0)),
    }
    for name, direction in views.items():
        cam_data.ortho_scale = scale
        cam.location = Vector(centre) + direction.normalized() * 3.0
        look = (Vector(centre) - cam.location).normalized()
        cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = "%s-%s.png" % (out, name)
        bpy.ops.render.render(write_still=True)
        print("YXZ_CRACK_VIEW " + scene.render.filepath)


main()
