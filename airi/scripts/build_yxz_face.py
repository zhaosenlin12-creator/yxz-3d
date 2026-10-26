"""Give the YXZ character real eyes and a real mouth.

The Tripo asset bakes its face into one texture: two blank white ovals where
the eyes should be and a painted red smile.  Nothing about it can be rigged
as-is, so this script rebuilds the features as geometry.

Probing the visor (`probe_yxz_face_surface.py`) showed why eyeball spheres
failed: the eye region is a flat panel at y = -0.238 ringed by a 10 mm step,
so a 0.055 sphere bulged straight through the shell.  Instead every piece is a
cap laid on a sphere least-squares fitted to the surrounding visor, so the
replacement hugs the shell at any size:

    socket   a dark disc that covers the painted oval and reads as an eye
             socket, giving a blink something to close onto
    sclera   the white of the eye, bound to the head so gaze can never slide
             it off the socket
    iris     one textured cap -- iris, limbal ring, pupil, glint and lid
             shadow are painted into it -- bound to leftEye / rightEye and
             floating clear of the sclera so a 25 degree gaze cannot sink it

Blink is a shape key that flattens the white to a slit and the iris to a dark
line, which is how a closed eye reads on this character.

Imported by `build_yxz_vrm.py`, which owns the coordinate conventions.
"""

from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from yxz_face_uv import interpolate_uv


# Measured from the baked texture and the visor depth probe.
EYE_X = 0.098
EYE_Z = 0.150
# The helmet texture has the eye whites painted straight onto it.  Anything
# that uncovers that paint shows it as a pale oval, which is why the socket
# cannot simply collapse on a blink: a wider shadow disc stays put and keeps
# the paint hidden for the whole expression, and the socket on top of it is
# free to shrink to the closed-eye line.
SHADOW_HW, SHADOW_HH = 0.046, 0.054

# The eye itself is the design's eye, and the design does not draw an eye.
# It draws a light: a soft luminous oval standing on the visor, taller than
# it is wide, pale cyan, and with no pupil in it at all.  The model came
# with a white of the eye, a blue iris and a black pupil instead, and that
# is what makes the character read as a toy with googly eyes rather than
# as the thing it was designed to be.
#
# So the light is rebuilt as the design draws it, and the gaze is kept by
# a small deeper core inside it that rides on the eye bone.  The core is
# soft-edged and carries the colour of the light at its own rim, so it
# reads as depth inside the glow rather than as a pupil stuck on the front.
GLOW_HW, GLOW_HH = 0.0445, 0.0525
CORE_HW, CORE_HH = 0.0125, 0.0155
CORE_DOME = 0.0010

# Caps follow the measured shell directly.  A fitted surface was tried first
# and left a 5 mm residual, because the visor has a brow step the fit could
# not follow; sitting exactly on the shell costs nothing and cannot float.
SHADOW_LIFT = 0.0005
GLOW_LIFT = 0.0022
# The core has to clear the light it sits in by more than the sideways
# swing of its own rim: at the 22 degree horizontal limit the rim travels
# 4.7 mm, and the pivot only controls how far the centre drifts, not that.
CORE_LIFT = 0.0060
# How far a blink drops the white and the iris behind the socket.  It has to
# clear the socket's own lift plus the shell relief under the rim.
BLINK_RETREAT = 0.0045

FALLBACK_Y = -0.238

MOUTH_Z = 0.062
MOUTH_HW, MOUTH_HH = 0.048, 0.018

SEG = 48
RINGS = 8


def material(name, color=None, roughness=0.32, image=None, emission=0.0,
             emission_colour=None, emission_image=None):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = next((n for n in nodes if "BSDF" in n.bl_idname), None)
    if bsdf is None:
        print("YXZ_MAT_WARN " + name + " nodes="
              + str([(n.name, n.bl_idname) for n in nodes]))
        return mat
    if color is not None:
        bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0
    if image is not None:
        # An Image datablock is not a node, so it needs a texture node of its
        # own; Blender 5.x also hands back an immutable tuple from
        # socket.links, so the node tree owns the connection.
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.location = (-320, 240)
        mat.node_tree.links.new(texture.outputs["Color"],
                                bsdf.inputs["Base Color"])
    if emission or emission_image is not None:
        if "Emission Color" in bsdf.inputs:
            if emission_colour is not None:
                bsdf.inputs["Emission Color"].default_value = emission_colour
            else:
                bsdf.inputs["Emission Color"].default_value = (
                    (0.55, 0.65, 0.78, 1.0) if color is None else color)
        if emission_image is not None:
            # The emission is a picture of its own, so the light carries a
            # gradient instead of a flat wash.  MToon reads the emission
            # from the standard glTF slot, and the standard slot is where
            # the exporter puts a textured emission.
            texture = nodes.new("ShaderNodeTexImage")
            texture.image = emission_image
            texture.location = (-320, -60)
            mat.node_tree.links.new(texture.outputs["Color"],
                                    bsdf.inputs["Emission Color"])
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = max(emission, 1.0)
    return mat


def grid_faces(rings, segments, offset=0):
    faces = []
    for i in range(rings):
        for j in range(segments):
            a = offset + i * segments + j
            b = offset + i * segments + (j + 1) % segments
            c = offset + (i + 1) * segments + (j + 1) % segments
            d = offset + (i + 1) * segments + j
            faces.append((a, b, c, d))
    return faces


def relax(verts, rings, segments, weight):
    """Ease interior depths so the visor's brow step becomes a ramp.

    The outer ring is left exactly on the measured surface so the cap keeps
    its silhouette; only the interior is pulled toward its neighbours, and
    less the further out it already is.
    """
    out = list(verts)
    for i in range(1, rings):
        for j in range(segments):
            index = i * segments + j
            neighbours = ((i - 1) * segments + j, (i + 1) * segments + j,
                          i * segments + (j - 1) % segments,
                          i * segments + (j + 1) % segments)
            average = sum(verts[k][1] for k in neighbours) / 4.0
            blend = weight * (1.0 - i / rings)
            out[index] = (verts[index][0],
                          verts[index][1] * (1.0 - blend) + average * blend,
                          verts[index][2])
    return out


def clamp_to_shell(verts, front, lift):
    """Keep a relaxed cap in front of the shell.

    Smoothing can pull a cap backwards where the visor dips, and any patch
    that sinks inside the helmet stops covering the painted eye oval, which
    then shows as a pale crescent along the rim.
    """
    out = []
    for x, y, z in verts:
        surface = front(x, z)
        limit = (FALLBACK_Y if surface is None else surface) - lift
        out.append((x, min(y, limit), z))
    return out


def new_object(name, verts, faces, uvs, mats, arm, bone, shape_keys=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    if uvs:
        layer = mesh.uv_layers.new(name="UVMap")
        flat = []
        for loop in mesh.loops:
            flat.extend(uvs[loop.vertex_index])
        layer.data.foreach_set("uv", flat)
    mesh.update()
    for mat in mats:
        mesh.materials.append(mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    group = obj.vertex_groups.new(name=bone)
    group.add(list(range(len(mesh.vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = arm
    modifier.use_vertex_groups = True
    obj.parent = arm
    if shape_keys:
        obj.shape_key_add(name="Basis", from_mix=False)
        for name, coords in shape_keys.items():
            key = obj.shape_key_add(name=name, from_mix=False)
            key.data.foreach_set("co", [c for co in coords for c in co])
    return obj


def squash(coords, cx, cz, keep, bow=0.0, retreat=0.0):
    """Flatten an eye cap toward a closed-lid line.

    `retreat` pushes the cap backwards, away from the character.  The visor is
    flat, so an eyelid large enough to cover the eye would have to float
    further forward than the iris itself and the iris would then swing through
    it on every glance.  Closing therefore works the other way round: the
    white and the iris duck behind the socket disc and the socket itself
    collapses into the closed-eye line.
    """
    out = []
    for x, y, z in coords:
        span = max(abs(x - cx), abs(z - cz), 1e-6)
        out.append((x, y + retreat,
                    cz + (z - cz) * keep - bow * (1.0 - ((x - cx) / span) ** 2)))
    return out


class Face:
    """Front-surface queries plus a barycentric texture lookup."""

    def __init__(self, body):
        mesh = body.data
        mesh.calc_loop_triangles()
        self.mesh = mesh
        self.bvh = BVHTree.FromPolygons(
            [v.co[:] for v in mesh.vertices],
            [tuple(t.vertices) for t in mesh.loop_triangles],
            all_triangles=True,
        )
        layer = mesh.uv_layers.active
        self.uv_data = layer.data if layer else None
        self.triangles = mesh.loop_triangles
        self.misses = 0
        self.image = None
        if mesh.materials and mesh.materials[0]:
            self.image = self._base_color_image(mesh.materials[0])
        self.pixels = None
        if self.image:
            self.size = tuple(self.image.size)
            raw = np.empty(len(self.image.pixels), dtype=np.float32)
            self.image.pixels.foreach_get(raw)
            self.pixels = raw.reshape(self.size[1], self.size[0], 4)

    @staticmethod
    def _base_color_image(mat):
        if not getattr(mat, "use_nodes", False):
            return None
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf is None:
            bsdf = next((n for n in nodes if "BSDF" in n.bl_idname), None)
        if not bsdf or not bsdf.inputs["Base Color"].links:
            return None
        return bsdf.inputs["Base Color"].links[0].from_node.image

    def _hit(self, x, z):
        # Blender 5.x ray_cast returns (location, normal, index, object).
        found = self.bvh.ray_cast(Vector((x, -3.0, z)), Vector((0.0, 1.0, 0.0)))
        if found[0] is None:
            self.misses += 1
            return None, None
        return found[0], found[2] if len(found) > 2 else None

    def front(self, x, z):
        point, _ = self._hit(x, z)
        return None if point is None else point.y

    def colour(self, x, z, fallback=(0.0, 0.0, 0.0)):
        point, tri_index = self._hit(x, z)
        if point is None or tri_index is None or self.pixels is None:
            return fallback
        tri = self.triangles[tri_index]
        v0, v1, v2 = (self.mesh.vertices[i].co.copy() for i in tri.vertices)
        d00, d01 = (v0 - point).dot(v0 - v1), (v0 - point).dot(v0 - v2)
        d11 = (v1 - point).dot(v1 - v2)
        d12 = (v1 - point).dot(v1 - v0)
        denom = d00 * d11 - d01 * d12
        if abs(denom) < 1e-12:
            return fallback
        w1 = (d11 * d00 - d01 * d12) / denom
        w2 = (d00 * d11 - d01 * d12) / denom
        uvs = [self.uv_data[li].uv for li in tri.loops]
        u = uvs[0][0] + w1 * (uvs[1][0] - uvs[0][0]) + w2 * (uvs[2][0] - uvs[0][0])
        v = uvs[0][1] + w1 * (uvs[1][1] - uvs[0][1]) + w2 * (uvs[2][1] - uvs[0][1])
        width, height = self.size
        px = min(width - 1, max(0, int(u * width)))
        py = min(height - 1, max(0, int(v * height)))
        texel = self.pixels[py, px]
        return tuple(float(texel[i]) for i in range(3)) + (1.0,)

    def uv(self, x, z, fallback=(0.5, 0.5)):
        point, tri_index = self._hit(x, z)
        if point is None or tri_index is None or self.uv_data is None:
            return fallback
        triangle = self.triangles[tri_index]
        positions = tuple(
            tuple(float(component) for component in self.mesh.vertices[index].co)
            for index in triangle.vertices
        )
        uvs = tuple(
            tuple(float(component) for component in self.uv_data[loop].uv)
            for loop in triangle.loops
        )
        return interpolate_uv(tuple(point), positions, uvs) or fallback

    def ring_colour(self, cx, cz, radius, samples=16):
        # The median, not the mean.  A ring drawn round the eye runs over
        # the white of the eye that the scan painted onto the texture as
        # well as over the visor, and on the inner side of the eye the
        # white is most of what the ring crosses.  Averaging drags the
        # visor's own colour towards it, and the disc that covers that
        # paint then reads as a pale ring around the eye.
        found = []
        for index in range(samples):
            angle = 2 * math.pi * index / samples
            pixel = self.colour(cx + radius * math.cos(angle),
                                cz + radius * 0.86 * math.sin(angle))
            found.append(np.array(pixel[:3]))
        return tuple(float(v) for v in np.median(np.array(found), axis=0))

def cap(height, cx, cz, hw, hh, lift, rings=RINGS, segments=SEG, dome=0.0,
        uv_cover=0.0):
    """An elliptical cap laid on a height field, one ring per sample."""
    if uv_cover and isinstance(uv_cover, (tuple, list)):
        cover_u, cover_v = float(uv_cover[0]), float(uv_cover[1])
    else:
        cover_u = cover_v = float(uv_cover)
    verts, uvs = [], []
    for i in range(rings + 1):
        t = i / rings
        for j in range(segments):
            angle = 2 * math.pi * j / segments
            px = cx + hw * t * math.cos(angle)
            pz = cz + hh * t * math.sin(angle)
            surface = height(px, pz)
            y = (FALLBACK_Y if surface is None else surface) - lift
            if dome:
                y -= dome * (1.0 - t * t)
            verts.append((px, y, pz))
            uvs.append((0.5 + (px - cx) / (2.0 * cover_u),
                        0.5 + (pz - cz) / (2.0 * cover_v))
                       if uv_cover else (0.0, 0.0))
    return verts, uvs


def glow_texture(name="YXZ_EyeGlowTex", size=256):
    """The luminous oval of the design, painted into one image.

    The design's eye is a light, and a light has a falloff: pale and
    almost white in the middle, deeper cyan towards the rim, with the
    faint grid of a screen across it.  The grid is not decoration --
    without it the oval reads as a blob of paint on a lens, and with
    it the visor reads as the screen it is.
    """
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    tex = bpy.data.images.new(name, size, size, alpha=False)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xs + 0.5) / size - 0.5
    # Blender's v axis runs upwards, so flip the row index.
    v = 0.5 - (ys + 0.5) / size
    r = np.sqrt(u * u + v * v) / 0.5

    centre = np.array([0.82, 0.97, 0.98])
    rim = np.array([0.24, 0.68, 0.76])
    t = np.clip((r - 0.30) / 0.66, 0.0, 1.0)[:, :, None]
    pixels = centre * (1.0 - t) + rim * t

    scan = 0.5 + 0.5 * np.sin(v * size * 0.44)
    pixels = pixels * (0.962 + 0.038 * scan)[:, :, None]
    grid = (np.abs(((u * size) % 16) - 8) < 0.7) | (np.abs(((v * size) % 16) - 8) < 0.7)
    pixels[grid] = pixels[grid] * 1.07

    out = np.zeros((size, size, 4), dtype=np.float64)
    out[..., :3] = np.clip(pixels, 0.0, 1.0)
    out[..., 3] = 1.0
    tex.pixels.foreach_set(out.ravel().astype(np.float32))
    tex.pack()
    return tex


def core_texture(name="YXZ_EyeCoreTex", size=128):
    """A soft deeper core inside the light, so the gaze has something to move.

    It is not a pupil.  A pupil is a hard black disc and it turns the
    design's light back into the googly eye the design never asked for.
    This is a soft well of deeper cyan that fades into the colour of the
    light at its own rim, so it reads as depth in the glow, and it rides
    on the eye bone so the character can be seen to be looking at you.
    """
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    tex = bpy.data.images.new(name, size, size, alpha=False)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xs + 0.5) / size - 0.5
    v = 0.5 - (ys + 0.5) / size
    r = np.sqrt(u * u + v * v) / 0.5

    deep = np.array([0.30, 0.66, 0.78])
    into = np.array([0.82, 0.97, 0.98])
    t = np.clip((r - 0.10) / 0.78, 0.0, 1.0)[:, :, None]
    pixels = deep * (1.0 - t) + into * t

    # The white highlight this used to carry has gone.  A pale dot near the
    # top of a small bright oval is read as a pupil catching the light, and
    # a pupil is the one thing the design's eye must not have.  The core is
    # carried by the depth of the well instead.

    out = np.zeros((size, size, 4), dtype=np.float64)
    out[..., :3] = np.clip(pixels, 0.0, 1.0)
    out[..., 3] = 1.0
    tex.pixels.foreach_set(out.ravel().astype(np.float32))
    tex.pack()
    return tex


def iris_texture(name="YXZ_IrisTex", size=256):
    """Paint iris, limbal ring, pupil, glint and lid shadow into one image."""
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    tex = bpy.data.images.new(name, size, size, alpha=False)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xs + 0.5) / size - 0.5
    # Blender's v axis runs upwards, so flip the row index.
    v = 0.5 - (ys + 0.5) / size
    r = np.sqrt(u * u + v * v)

    # Dark field outside the cap.  The blink morph squashes this cap into a
    # line, and anything pale out here would show up as white specks along
    # the closed eyelid.
    pixels = np.zeros((size, size, 4), dtype=np.float64)
    pixels[..., :3] = np.array([0.05, 0.08, 0.12])
    pixels[..., 3] = 1.0

    inner = np.array([0.16, 0.46, 0.82])
    outer = np.array([0.04, 0.13, 0.38])
    iris_t = np.clip(r / 0.84, 0.0, 1.0)[:, :, None]
    iris = inner * (1.0 - iris_t) + outer * iris_t
    # Radial fibres, so the iris does not read as a flat gradient.
    angle = np.arctan2(v, u)
    fibres = 0.5 + 0.5 * np.sin(angle * 26.0 + r * 34.0)
    iris = iris * (0.86 + 0.20 * fibres)[:, :, None]

    limbal = r >= 0.84
    shade = np.clip((r - 0.84) / 0.09, 0.0, 1.0)[:, :, None]
    pixels[limbal, :3] = (iris * (1.0 - shade) + np.array([0.03, 0.05, 0.14])
                          * shade)[limbal]
    pixels[~limbal, :3] = iris[~limbal]

    # A soft shadow along the top of the eye reads as an upper lid.
    lid = np.clip((v - 0.16) / 0.34, 0.0, 1.0) ** 1.6
    pixels[..., :3] = pixels[..., :3] * (1.0 - 0.42 * lid)[:, :, None]

    pupil = r < 0.225
    pixels[pupil, :3] = np.array([0.016, 0.020, 0.045])

    def blob(bu, bv, br, strength):
        d = np.sqrt((u - bu) ** 2 + (v - bv) ** 2) / br
        return np.clip(1.0 - d * d, 0.0, 1.0)[:, :, None] * strength

    pixels[..., :3] += blob(-0.22, 0.26, 0.15, 1.0)
    pixels[..., :3] += blob(0.26, -0.24, 0.06, 0.40)

    tex.pixels.foreach_set(np.clip(pixels, 0.0, 1.0).ravel().astype(np.float32))
    tex.pack()
    return tex


def build_eye(face, side, sign, arm, glow_tex, core_tex):
    cx, cz = sign * EYE_X, EYE_Z
    objects = []
    front = face.front

    # --- shadow: never moves, so the painted oval stays covered forever ----
    tone = face.ring_colour(cx, cz, GLOW_HW * 1.12)
    # The disc has to stay opaque and wide enough to keep the helmet's own
    # painted eye hidden for the whole of a blink, but it sits a few
    # millimetres proud of the light, so whatever colour it is shows as a
    # ring around the eye.  At 30% of the visor it read as a dark outline
    # drawn round the character's gaze; holding it just under the visor it
    # still hides the paint and is no longer visible itself.
    shadow_colour = tuple(c * 0.88 for c in tone) + (1.0,)
    verts, uvs = cap(front, cx, cz, SHADOW_HW, SHADOW_HH, SHADOW_LIFT)
    verts = clamp_to_shell(relax(verts, RINGS, SEG, 0.45), front, SHADOW_LIFT)
    objects.append(new_object(
        "YXZ_EyeShadow." + side, verts, grid_faces(RINGS, SEG), uvs,
        [material("YXZ_EyeShadow", shadow_colour, roughness=0.85)],
        arm, "head"))

    # --- the light itself: the design's eye -------------------------------
    verts, uvs = cap(front, cx, cz, GLOW_HW, GLOW_HH, GLOW_LIFT,
                     uv_cover=(GLOW_HW, GLOW_HH))
    verts = clamp_to_shell(relax(verts, RINGS, SEG, 0.45), front, GLOW_LIFT)
    # A blink closes the light down to a slit.  The shadow underneath stays
    # where it is, so a closed eye is a dark line on the visor rather than
    # a white patch of paint.
    shut = squash(verts, cx, cz, 0.06, bow=0.0016, retreat=BLINK_RETREAT)
    # `blink` exists on both eyes; blinkLeft / blinkRight stay per eye so a
    # wink can close just one of them.
    objects.append(new_object(
        "YXZ_EyeGlow." + side, verts, grid_faces(RINGS, SEG), uvs,
        [material("YXZ_EyeGlow", (0.05, 0.10, 0.13, 1.0), roughness=0.42,
                  emission_image=glow_tex)],
        arm, "head",
        shape_keys={"blink": shut, "blink" + side.capitalize(): list(shut)}))

    # --- the core: the one part of the eye that moves ----------------------
    verts, uvs = cap(front, cx, cz, CORE_HW, CORE_HH, CORE_LIFT,
                     dome=CORE_DOME, uv_cover=(CORE_HW, CORE_HH))
    closed = squash(verts, cx, cz, 0.05, retreat=BLINK_RETREAT)
    objects.append(new_object(
        "YXZ_EyeCore." + side, verts, grid_faces(RINGS, SEG), uvs,
        [material("YXZ_EyeCore", (0.04, 0.08, 0.11, 1.0), roughness=0.30,
                  emission_image=core_tex)],
        arm, side + "Eye",
        shape_keys={"blink": closed,
                    "blink" + side.capitalize(): list(closed)}))

    return objects, {
        "surfaceY": face.front(cx, cz),
        "shadowColour": [round(c, 4) for c in shadow_colour],
    }


# inner half-width, inner half-height, vertical offset
MOUTH_SHAPES = {
    "Basis": (0.030, 0.0020, 0.0000),
    "aa": (0.019, 0.0130, -0.0012),
    "ih": (0.027, 0.0075, 0.0000),
    "ou": (0.014, 0.0110, -0.0006),
    "ee": (0.029, 0.0048, 0.0006),
    "happy": (0.030, 0.0068, 0.0030),
    "sad": (0.023, 0.0046, -0.0032),
    "angry": (0.027, 0.0038, -0.0022),
    "relaxed": (0.021, 0.0028, 0.0006),
    "surprised": (0.017, 0.0130, -0.0012),
}

MOUTH_RINGS = 5


def mouth_patch(front, lift, inner):
    """Annulus between a shaped inner opening and the fixed outer edge."""
    iw, ih, dz = inner
    verts = []
    for k in range(MOUTH_RINGS + 1):
        t = k / MOUTH_RINGS
        for j in range(SEG):
            angle = 2 * math.pi * j / SEG
            px = (iw + (MOUTH_HW - iw) * t) * math.cos(angle)
            pz = (ih + (MOUTH_HH - ih) * t) * math.sin(angle)
            z = MOUTH_Z + dz + pz
            surface = front(px, z)
            verts.append((px, (FALLBACK_Y if surface is None else surface) - lift, z))
    return verts


def mouth_cavity(front, lift, inner):
    """A shallow, shaped cavity that stays in front of the scanned face."""
    width, height, dz = inner
    rings = 5
    verts = []
    for ring in range(rings + 1):
        radius = ring / rings
        depth = lift * (0.56 + 0.44 * radius * radius)
        for segment in range(SEG):
            angle = 2 * math.pi * segment / SEG
            x = width * radius * math.cos(angle)
            z = MOUTH_Z + dz + height * radius * math.sin(angle)
            surface = front(x, z)
            base = FALLBACK_Y if surface is None else surface
            verts.append((x, base - depth, z))
    return verts


def build_mouth(face, arm):
    front = face.front
    lift = 0.0008
    # The plate follows the scan's own colour variation so its edge does not
    # read as a solid oval pasted over the muzzle.
    plate = material("YXZ_MouthPlate", (1.0, 1.0, 1.0, 1.0),
                     roughness=0.72, image=face.image)
    cavity = material("YXZ_MouthCavity", (0.024, 0.016, 0.028, 1.0), roughness=0.35)

    states = {name: mouth_patch(front, lift, shape)
              for name, shape in MOUTH_SHAPES.items()}
    cavity_states = {name: mouth_cavity(front, lift, shape)
                     for name, shape in MOUTH_SHAPES.items()}
    plate_uvs = [face.uv(x, z) for x, _, z in states["Basis"]]
    plate_obj = new_object(
        "YXZ_Mouth", states["Basis"], grid_faces(MOUTH_RINGS, SEG), plate_uvs,
        [plate], arm, "head",
        shape_keys={k: v for k, v in states.items() if k != "Basis"})

    cavity_obj = new_object(
        "YXZ_MouthCavity", cavity_states["Basis"],
        grid_faces(5, SEG), None, [cavity], arm, "head",
        shape_keys={k: v for k, v in cavity_states.items() if k != "Basis"})
    return [plate_obj, cavity_obj], None, {
        "plateLift": lift,
        "cavityShapeKeys": len(cavity_states) - 1,
        "texturedPlate": face.image is not None,
    }


def attach_face(body, arm):
    face = Face(body)
    glow_tex = glow_texture()
    core_tex = core_texture()
    report = {"eyes": {}}
    objects = []
    for side, sign in (("left", 1.0), ("right", -1.0)):
        eye_objects, info = build_eye(face, side, sign, arm, glow_tex, core_tex)
        objects.extend(eye_objects)
        report["eyes"][side] = info
    mouth_objects, plate_colour, mouth_info = build_mouth(face, arm)
    objects.extend(mouth_objects)
    report["mouth"] = mouth_info
    report["mouthColour"] = plate_colour
    report["misses"] = face.misses
    report["bounds"] = {}
    for obj in objects:
        coords = [v.co for v in obj.data.vertices]
        report["bounds"][obj.name] = [
            [round(min(c[i] for c in coords), 4), round(max(c[i] for c in coords), 4)]
            for i in range(3)
        ]
    return report
