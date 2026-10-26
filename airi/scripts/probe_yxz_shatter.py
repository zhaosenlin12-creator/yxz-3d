"""Show every place the camera can see the inside of the character.

The character reads as broken because a handful of its surfaces are turned
away from the camera while their geometry still sits in front of the face,
and because a few of its shells have a tear in them.  Both look the same
on screen -- a bright shard lying on a smooth body -- and both have been
chased one at a time by picking at pixels, which never finds them: a ray
fired into a shard that is turned away passes straight through it and
reports whatever is behind, so every pick has come back clean.

So the shards are not picked.  They are drawn.  The material here is a
flat emission keyed off the geometry node's Backfacing output: a surface
turned towards the camera is grey, and a surface turned away from it is
red.  Nothing is lit and nothing is shaded, so a red pixel in the picture
is the inside of the character and not a highlight, a reflection or a
shadow.  Every red pixel is a place the camera is looking at the wrong
side of the model, and every one of them is a shard.

The same picture is rendered a second time with backface culling on.  The
red that survives that render is not a surface turned away from the camera
but a surface the camera cannot see at all, which is what a hole in the
shell looks like from this side.  Red in the first picture and gone from
the second is a sheet lying over an intact body; red in both is a gap.

Usage:
  blender -b -P scripts/probe_yxz_shatter.py -- \
    --glb <glb> --front 1,0 --out <png> [--prefix <png>]
"""

from __future__ import annotations

import json
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector


# Which way the character faces, in the frame the file is read in.  The
# cleaned scan puts the front on +X, so the default is a camera out on +X.
FRONT = [1.0, 0.0]


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def facing_material():
    """Flat emission: grey towards the camera, red away from it."""
    mat = bpy.data.materials.new("facing")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()

    out = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    mix = tree.nodes.new("ShaderNodeMixRGB")
    geometry = tree.nodes.new("ShaderNodeNewGeometry")

    mix.inputs["Color1"].default_value = (0.62, 0.64, 0.68, 1.0)
    mix.inputs["Color2"].default_value = (1.0, 0.05, 0.05, 1.0)
    emission.inputs["Strength"].default_value = 1.0

    tree.links.new(geometry.outputs["Backfacing"], mix.inputs["Fac"])
    tree.links.new(mix.outputs["Color"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], out.inputs["Surface"])
    return mat


def aim_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world(backface_culling):
    """A flat white world and a camera out in front of the character."""
    world = bpy.data.worlds.new("probe")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        1.0, 1.0, 1.0, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", data)
    bpy.context.scene.collection.objects.link(camera)
    data.lens = 85.0
    camera.location = Vector((FRONT[0] * 6.0, FRONT[1] * 6.0, 1.30))
    bpy.context.scene.camera = camera
    aim_at(camera, (0.0, 0.0, 0.22))

    # The emission carries the picture on its own, so no light is added:
    # a light would put a gradient across the grey and the red would stop
    # being the only thing in the picture that is coloured.
    data = bpy.data.lights.new("key", type="SUN")
    data.energy = 0.0
    light = bpy.data.objects.new("key", data)
    bpy.context.scene.collection.objects.link(light)
    light.location = Vector((1.0, 0.0, 0.0))
    aim_at(light, (0.0, 0.0, 0.0))

    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"

    # Backface culling is a per-material switch, so the material is
    # re-pointed for the second render rather than a new scene being built.
    for mat in bpy.data.materials:
        if mat.name.startswith("facing"):
            mat.use_backface_culling = backface_culling

    # Anything that reads the camera's matrix directly -- a projection, a
    # ray cast -- needs the dependency graph refreshed first, or it goes on
    # using an identity matrix.
    bpy.context.view_layer.update()
    return scene


def red_mask(path):
    """How much of the picture is red, and where it is."""
    image = bpy.data.images.load(path)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    # The render is stored bottom-up, so the rows are flipped back to the
    # order a person reads them in before anything is reported.
    frame = pixels.reshape(height, width, 4)[::-1]
    red = (frame[:, :, 0] > 0.5) & (frame[:, :, 1] < 0.35) & (frame[:, :, 2] < 0.35)
    bpy.data.images.remove(image)

    coverage = float(red.mean())
    rows = np.where(red.any(axis=1))[0]
    cols = np.where(red.any(axis=0))[0]
    if rows.size == 0:
        return {"redFraction": 0.0, "blobs": 0}

    # Red that comes in a blob is one torn sheet; red that comes in a
    # handful of pixels is a seam.  Both are counted, because both are
    # broken, but they are not the same fault and they do not get the same
    # fix.
    step = 12
    cells = set()
    for r in range(0, height, step):
        for c in range(0, width, step):
            if red[r:r + step, c:c + step].any():
                cells.add((r // step, c // step))
    blobs = 0
    while cells:
        seed = cells.pop()
        frontier = [seed]
        while frontier:
            r, c = frontier.pop()
            for neighbour in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if neighbour in cells:
                    cells.remove(neighbour)
                    frontier.append(neighbour)
        blobs += 1

    return {
        "redFraction": round(coverage, 5),
        "blobs": blobs,
        "box": [int(cols.min()), int(rows.min()),
                int(cols.max()), int(rows.max())],
    }


def main() -> None:
    global FRONT
    front = value_after("--front")
    if front:
        FRONT = [float(v) for v in front.split(",")]

    source = value_after("--glb")
    out = os.path.abspath(value_after("--out"))
    prefix = value_after("--prefix") or os.path.splitext(out)[0]
    weld = value_after("--weld")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh in " + str(source))

    # A fold is two sheets of surface meeting along a seam, and welding
    # that seam collapses the doubled half into one.  Whether welding is a
    # good idea was an argument in the cleaner; here it is a measurement,
    # so the welded mesh and the unwelded one are counted against each
    # other instead.
    if weld is not None:
        welded = []
        for obj in meshes:
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts),
                                     dist=float(weld))
            bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
            bm.to_mesh(obj.data)
            bm.free()
            welded.append([obj.name, len(obj.data.vertices),
                           len(obj.data.polygons)])
        print("YXZ_WELDED " + json.dumps({"weld": float(weld),
                                          "meshes": welded}))

    # Every mesh gets the same material: the eye and mouth overlays live in
    # their own meshes and they are turned towards the camera, so they come
    # out grey and change nothing.  The halo is turned away in places and
    # would otherwise add red that is not part of the body.
    mat = facing_material()
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(mat)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    report = {"glb": str(source), "front": FRONT}

    scene = setup_world(backface_culling=False)
    both = os.path.abspath(prefix + "-seen.png")
    scene.render.filepath = both
    bpy.ops.render.render(write_still=True)
    report["seen"] = red_mask(both)

    scene = setup_world(backface_culling=True)
    culled = os.path.abspath(prefix + "-culled.png")
    scene.render.filepath = culled
    bpy.ops.render.render(write_still=True)
    report["culled"] = red_mask(culled)

    print("YXZ_SHATTER " + json.dumps(report))


if __name__ == "__main__":
    main()
