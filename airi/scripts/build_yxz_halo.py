"""Build the halo as its own object, so it can actually glow.

The halo came back from the scan as two thin blades of it -- crescent
shards, a few thousand triangles each, floating where the ring used to
be -- and nothing else.  Fitting a circle to one gives a radius of a
quarter of a unit with its centre half a unit outside the character, and
fitting the other gives a different circle entirely.  They are rubble,
not a ring.

So the ring is not recovered, it is rebuilt, from the design it was
supposed to follow: a flattened band of even section swept along a
circle, with a five-pointed star riding on it.

It used to be built as part of the body's own mesh, which is where the
problem was.  A ring that shares the body's material is a ring that
shares the body's lighting, and a lit band of plastic is exactly what
the halo looked like: a dull grey hoop above a character's head.  The
design calls for a ring of light, and light is not something a material
can borrow from a scan's colour map.

So the halo is built here as its own object, with its own material that
carries an emission, and it is bound to the `halo` bone the rig already
has, so it keeps following the character exactly as it did when it was
part of the body.

The colours are the design's own: a pale cyan ring and a deeper blue
star.  They are not sampled from the atlas, because the atlas has no
halo in it to sample -- the shards that used to be the halo were the
only place its colour survived, and they are gone by the time this
runs.

Usage:
  blender -b -P scripts/build_yxz_halo.py --   (imported by build_yxz_vrm.py)
"""

from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Vector

from rebuild_yxz_halo import (
    CENTRE,
    DEPTH,
    RADIUS,
    RING_STEPS,
    SECTION_SIDES,
    STAR_ANGLE_DEGREES,
    STAR_DEPTH,
    STAR_FACE_TILT_DEGREES,
    STAR_INNER,
    STAR_OUTER,
    STAR_POINTS,
    TILT_DEGREES,
    WIDTH,
)


# The design's palette.  A ring of light is not a colour that a scan
# can carry, so it is written down here instead of measured.
RING_COLOUR = (0.07, 0.20, 0.24, 1.0)
RING_EMISSION = (0.16, 0.62, 0.80, 1.0)
STAR_COLOUR = (0.12, 0.36, 0.66, 1.0)
STAR_EMISSION = (0.10, 0.32, 0.62, 1.0)


def R(point):
    """Measured frame -> exported frame, a -90 degree turn around Z.

    The same turn `build_yxz_vrm.py` applies to the body, so the halo ends
    up in the same place the shards used to be.
    """
    return Vector((point[1], -point[0], point[2]))


def ring_frame():
    """The ring's centre, the two directions it is drawn in, and its normal.

    The tilt is taken about the character's left-to-right axis, so the
    ring leans back rather than sideways, and it is negative so that the
    far side is the higher one -- a halo tipped the other way reads as a
    bowl the character is looking into.
    """
    tilt = math.radians(TILT_DEGREES)
    normal = Vector((0.0, math.sin(tilt), math.cos(tilt)))
    normal.normalize()
    axis_a = Vector((1.0, 0.0, 0.0))
    axis_a = (axis_a - normal * axis_a.dot(normal)).normalized()
    axis_b = normal.cross(axis_a)
    return CENTRE, axis_a, axis_b, normal


def ring_geometry():
    """A closed ring of even section, swept as a flattened torus.

    Sweeping a circle along a circle is the one construction that gives a
    band with no ends to see: every part of it is the same shape as every
    other part, so no edge of it can be the place where the surface
    stops.
    """
    centre, axis_a, axis_b, normal = ring_frame()
    centre, axis_a, axis_b, normal = (R(vector) for vector in (centre, axis_a, axis_b, normal))

    verts = []
    faces = []
    uvs = []
    for step in range(RING_STEPS):
        theta = 2.0 * math.pi * step / RING_STEPS
        on_ring = axis_a * (RADIUS * math.cos(theta)) + axis_b * (RADIUS * math.sin(theta))
        outward = on_ring.normalized()
        for cross in range(SECTION_SIDES):
            phi = 2.0 * math.pi * cross / SECTION_SIDES
            offset = outward * (WIDTH * math.cos(phi)) + normal * (DEPTH * math.sin(phi))
            verts.append(tuple(centre + on_ring + offset))
            # The band's own cross section is the second coordinate, so a
            # texture drawn across it can put the light in the middle of
            # the ribbon and let the two edges fall away.  That is what
            # stops the ring reading as a length of bent pipe.
            uvs.append((step / RING_STEPS, cross / SECTION_SIDES))

    for step in range(RING_STEPS):
        current = step * SECTION_SIDES
        following = ((step + 1) % RING_STEPS) * SECTION_SIDES
        for cross in range(SECTION_SIDES):
            after = (cross + 1) % SECTION_SIDES
            faces.append((current + cross, current + after, following + after, following + cross))
    return verts, faces, uvs


def star_geometry():
    """The star that rides on the ring: a flat badge with real thickness.

    It is given thickness because a star drawn as a single sheet reads as
    a hole in the render from every angle but one -- and it is the one
    solid on the character with an edge on all twelve of its sides, so
    an edge that catches the light is what stops it looking like a decal
    painted on.
    """
    centre, axis_a, axis_b, normal = ring_frame()
    angle = math.radians(STAR_ANGLE_DEGREES)
    # The star rides on the ring's high end, turned a little towards the
    # back so that it stands clear of the helmet instead of sitting on
    # the shoulder of it.
    radial = axis_b * math.cos(angle) - axis_a * math.sin(angle)
    radial = radial.normalized()
    # The star is a badge that has to be read as a star, so it faces the
    # viewer: forward, and tipped down towards a camera that is at the
    # character's eye line and therefore well below the ring.
    lean = math.radians(STAR_FACE_TILT_DEGREES)
    front = Vector((1.0, 0.0, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    facing = (front * math.cos(lean) - up * math.sin(lean))
    facing.normalize()
    # The star's own up is the world's up, flattened into the plane the
    # badge lies in, so its point aims at the top of the frame.
    top = (up - facing * up.dot(facing)).normalized()
    right = top.cross(facing).normalized()
    middle = centre + radial * RADIUS
    half = facing * (STAR_DEPTH * 0.5)

    points = STAR_POINTS * 2
    outline = []
    for index in range(points):
        theta = index * (math.pi / STAR_POINTS) + math.pi * 0.5
        reach = STAR_OUTER if index % 2 == 0 else STAR_INNER
        outline.append(middle + right * (reach * math.cos(theta)) + top * (reach * math.sin(theta)))

    verts = []
    faces = []
    hubs = []
    corners = []
    for side in (1.0, -1.0):
        hub = len(verts)
        hubs.append(hub)
        verts.append(tuple(middle + half * side))
        side_corners = []
        for point in outline:
            side_corners.append(len(verts))
            verts.append(tuple(point + half * side))
        corners.append(side_corners)
        for index in range(points):
            faces.append((hub, side_corners[index], side_corners[(index + 1) % points]))

    # The side wall joins the two rims of the badge.  The first rim is the
    # hub at index 0 with its ten corners at 1..10; the second is the hub
    # at index 11 with its ten corners at 12..21.  An earlier version
    # worked the indices out from the total vertex count instead, and
    # stitched the wall to the hub and to a corner that was on the other
    # rim, which is what turned the star into a handful of spikes.
    front_hub, back_hub = hubs
    front_corners, back_corners = corners
    for index in range(points):
        faces.append((front_corners[index], back_corners[index],
                      back_corners[(index + 1) % points],
                      front_corners[(index + 1) % points]))

    # Everything above is worked out in the measured frame, and the ring is
    # carried over into the exported frame by `R` before a single vertex is
    # built -- `ring_geometry` does the same to its own frame.  The star was
    # missing that turn, so it was exported a quarter turn round from the
    # ring it is supposed to be riding on: behind the character instead of
    # beside it, which is exactly where it showed up on screen.
    return [tuple(R(vertex)) for vertex in verts], faces


def halo_texture(name="YXZ_HaloTex", size=256):
    """The band of light, painted as a picture rather than a flat colour.

    The ring is a flat ribbon, and a ribbon lit evenly all over is a
    ribbon of plastic.  The light belongs in the middle of the band and
    falls away towards both of its edges, and the two wide faces of the
    ribbon are the bright ones while the two thin edges are the dim
    ones -- which is what the cross section of the band is.

    So the second coordinate of the texture is the way round that cross
    section, and the light is drawn as two bands, one on each face.
    """
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    tex = bpy.data.images.new(name, size, size, alpha=False)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xs + 0.5) / size
    v = (ys + 0.5) / size

    # The cross section runs anticlockwise from the outer edge, so the two
    # wide faces sit a quarter of the way round from each other and the
    # two narrow edges sit half a section apart.
    #
    # The light belongs in the middle of the band, which is the wide face
    # -- the face that is actually seen, because the ring is nearly flat
    # and is looked at from above.  The narrow edges are the ones that
    # catch the key light and draw a bright line down each side of the
    # ring, and a ring with a bright line down each side of it and a dim
    # face between them reads as a wire hoop drawn on the page rather
    # than as a ribbon of light.  So the profile peaks on the wide faces.
    around = np.abs(np.sin(2.0 * np.pi * v))
    profile = 0.30 + 0.70 * around

    # A slow travel of brightness around the ring, so the light is not
    # perfectly uniform and the eye reads it as a lit object.  Both terms
    # have a whole number of cycles around the ring, so the seam where
    # the texture wraps does not show as a line round the band.
    travel = (0.86
              + 0.09 * np.sin(2.0 * np.pi * (u + 0.15))
              + 0.05 * np.cos(4.0 * np.pi * (u + 0.40)))

    # The colour of the light.  The green channel is kept well down: a
    # band whose green and blue are level is a band the tone mapper
    # desaturates into white, and a white band on a pale page is a hoop of
    # wire.  The blue is allowed past the bloom threshold and the green is
    # not, so the band spills a little light and keeps its colour.
    face = np.array([0.10, 0.55, 1.00])
    edge = np.array([0.04, 0.26, 0.52])
    t = (1.0 - profile)[:, :, None]
    pixels = (face * (1.0 - t) + edge * t) * (profile * travel)[:, :, None]

    out = np.zeros((size, size, 4), dtype=np.float64)
    out[..., :3] = np.clip(pixels, 0.0, 1.0)
    out[..., 3] = 1.0
    tex.pixels.foreach_set(out.ravel().astype(np.float32))
    tex.pack()
    return tex


def glowing_material(name, colour, emission, emission_image=None):
    """A flat material that carries its own light.

    The base colour is what the ring looks like where the light does not
    reach it, and the emission is what it looks like everywhere else.
    """
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = next((n for n in nodes if "BSDF" in n.bl_idname), None)
    if bsdf is None:
        raise RuntimeError("no shader in " + name)
    bsdf.inputs["Base Color"].default_value = colour
    bsdf.inputs["Roughness"].default_value = 0.34
    bsdf.inputs["Metallic"].default_value = 0.0
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = emission
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = 1.0
    if emission_image is not None:
        # The light is a picture, so it has to come in through a texture
        # node: the MToon loader reads the standard glTF emissive slot,
        # and that is where the exporter puts a textured emission.
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = emission_image
        texture.location = (-320, -60)
        mat.node_tree.links.new(texture.outputs["Color"],
                                bsdf.inputs["Emission Color"])
    return mat


def attach_halo(arm):
    """Add the halo and its star to the rig as objects of their own."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_yxz_face import new_object

    band = halo_texture()
    made = []
    for name, geometry, colour, emission, picture in (
        ("YXZ_Halo", ring_geometry(), RING_COLOUR, RING_EMISSION, band),
        ("YXZ_HaloStar", star_geometry(), STAR_COLOUR, STAR_EMISSION, None),
    ):
        verts, faces = geometry[0], geometry[1]
        uvs = geometry[2] if len(geometry) > 2 else None
        material = glowing_material(name, colour, emission, picture)
        obj = new_object(name, verts, faces, uvs, [material], arm, "halo")
        # The ring is a smooth band and the star is a flat badge, and they
        # want different normals: a band shaded flat reads as a folded
        # ribbon, which is the one thing that made the old ring look like
        # chopped pipe.
        for polygon in obj.data.polygons:
            polygon.use_smooth = name == "YXZ_Halo"
        if name == "YXZ_HaloStar":
            # The badge is a solid with twelve sides, and the winding of
            # its wall is worked out by hand, so the normals are put
            # right from the shape rather than trusted.
            import bmesh

            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
        made.append(obj.name)
    return made
