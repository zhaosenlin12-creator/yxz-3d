"""Rebuild the halo, which the scan did not record at all.

The character arrives from Tripo wearing a halo: a ring of light above
the head with a star on it.  What came back is not a broken ring.  It
is two thin blades of it -- crescent shards, a few thousand triangles
each, floating where the ring used to be -- and nothing else.  There
is no curve through them: fitting a circle to one gives a radius of a
quarter of a unit with its centre half a unit outside the character,
and fitting the other gives a different circle entirely.  They are
rubble, not a ring.

So the ring is not recovered.  It is rebuilt, from the design it was
supposed to follow, and rebuilt as geometry rather than as whatever
the camera happened to catch.  A ring that is generated is a ring:
closed, of even section, with no ends and no seams, which is exactly
what the two blades could not be.  The shards are measured first --
where they sit, how far above the crown -- and the new ring is placed
to agree with them, so it lands where the original was rather than
somewhere that merely looks like it.

The section is the other half of the job.  The shards are knife-edged
sheets, and a knife-edged sheet is what reads as broken: its outline
is a hard line that ends abruptly, and there is nothing for the light
to do along it.  The rebuilt ring is a flattened torus instead -- wide
across, thinner through, smoothly rounded at the corners -- so the
highlight travels along it instead of stopping dead.

The colour comes from the atlas the character already uses.  The
shards are painted in the halo's own colours, and the most common texel
among them is what the ring was, and the bluest is what the star was.
Sampling those keeps the new geometry inside the existing material, so
there is no second material to introduce and nothing downstream has to
know this happened.
"""

from __future__ import annotations

import math

import bmesh
import numpy as np
from mathutils import Vector


# Where the ring goes: centred a little above the crown.
#
# The ring is a shade under half a unit from side to side, against a head
# that is a shade over half a unit across, so it sits just inside the
# width of the head and well clear above it.  The design's halo is a
# flat disc of light lying almost flat on top of the head, and the ring
# here is that: wide enough to read as a halo, thin enough that it is
# not a hoop of wire.
CENTRE = Vector((0.0, -0.012, 0.474))
# The tip is the angle the ring rolls by about the character's front-to-back
# axis.  It is negative on purpose: a negative tip puts the character's left
# end of the ring -- the end the star rides on, and the end the design puts
# the star on -- higher than the other, and a ring tipped the other way puts
# the star at the bottom of the frame where it reads as a scrap.
#
# It used to be twenty degrees, and that was the whole reason the halo read
# as a sheet of bent plastic rather than as a ring of light.  Tipped that
# far, the near end of the ring drops a hundredth of a unit below the
# crown -- the ring passes through the helmet -- and the ring's own face
# is turned towards the camera, so what the eye sees is a broad blade
# lying across the top of the head.  Seven degrees keeps the ring clear of
# the helmet and turns its face away from the camera, which is what
# leaves a thin ellipse of light above the head, and that is what the
# design draws.
#
# The measured frame has +X as the character's front and +Y as the side
# that appears on the right of the screen, so "left" here means the viewer's
# right, which is the side the design's star is on.
TILT_DEGREES = -7.0
RADIUS = 0.262

# The band: wide across the ring, thinner through it, and rounded at
# the corners.  Those three numbers are the difference between a halo
# and a length of chopped pipe.
WIDTH = 0.022
DEPTH = 0.005
SECTION_SIDES = 16
RING_STEPS = 128

# The star that rides on the ring.  The design's star is about a seventh of
# the ring's own diameter across, so it is a small badge on the rim and not
# a second halo; a star half the ring's size reads as debris.
STAR_OUTER = 0.036
STAR_INNER = 0.015
STAR_DEPTH = 0.006
# How far round the ring the star sits, measured from the ring's own high
# end (the one that appears on the right of the screen) and turned a little
# towards the back, so it stands clear of the head instead of sitting on
# the shoulder of the helmet.
STAR_ANGLE_DEGREES = 14.0
STAR_POINTS = 5

# A badge lying flat in the ring's own plane is edge on to anyone standing
# at the character's eye line, and an edge-on plate is a line.  The star is
# tipped forward off the ring's plane by this much and then tipped down
# towards the camera, which is what lets it read as a star from where the
# camera actually is.
STAR_FACE_TILT_DEGREES = 25.0


def load_atlas():
    """The base colour image as a numpy array of rows."""
    import bpy

    for image in bpy.data.images:
        if image.name.startswith("Color"):
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
            width, height = image.size
            return pixels.reshape(height, width, 4)
    raise RuntimeError("no base colour image in the file")


def is_cyan(pixel) -> bool:
    """Is this texel the saturated cyan of the halo?

    The pixels come out of Blender in linear space.  The halo is a
    strongly saturated green-blue; the white body is bright but almost
    neutral, and the blue accents are far too dark to pass.  The test
    has to reject the white body, or every panel of the character comes
    back as halo.
    """
    r, g, b = float(pixel[0]), float(pixel[1]), float(pixel[2])
    return g > 0.45 and b > 0.45 and g - r > 0.25 and b - r > 0.25 and abs(g - b) < 0.22


def connected_faces(bm):
    """Every face of the mesh, grouped by the shell it belongs to.

    Colour alone does not say what a piece of geometry is: the visor
    and the trim are the same cyan as the halo.  What does say is
    reachability.  The scan arrives as a couple of hundred disconnected
    blobs, and once those are welded the character is a handful of
    shells -- the body, and the halo's remains floating clear of it.
    """
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


def describe_shells(groups):
    """A one line census of the shells: how big each is and where it sits."""
    census = []
    for group in groups:
        middle = np.array([list(face.calc_center_median()) for face in group]).mean(axis=0)
        where = [round(float(value), 3) for value in middle]
        census.append([len(group), where])
    return census


def face_texel(face, uv_layer, atlas):
    """The texel in the middle of a face."""
    u = sum(loop[uv_layer].uv.x for loop in face.loops) / len(face.loops)
    v = sum(loop[uv_layer].uv.y for loop in face.loops) / len(face.loops)
    x = int(min(max(u, 0.0), 1.0) * (atlas.shape[1] - 1))
    y = int(min(max(v, 0.0), 1.0) * (atlas.shape[0] - 1))
    return x, y


def halo_palette(atlas, faces, uv_layer):
    """The ring's colour and the star's, read off the shards themselves.

    Every texel the shards are painted with is a colour the halo was
    designed in.  The ring takes the one most of them share, and the
    star takes the most saturated blue among them, since the star is
    the one part of the halo that is not the same cyan as the ring.
    """
    height, width = atlas.shape[0], atlas.shape[1]
    tally = {}
    for face in faces:
        texel = face_texel(face, uv_layer, atlas)
        if not is_cyan(atlas[texel[1], texel[0]]):
            continue
        tally[texel] = tally.get(texel, 0) + 1
    if not tally:
        return None, None, None, None

    # Texels on the border of the atlas are one bilinear tap away from
    # whatever the packing put next to them, so a colour read from the
    # edge is not a colour, it is a smear of two.
    margin = 3
    usable = {
        texel: count
        for texel, count in tally.items()
        if margin <= texel[0] < width - margin and margin <= texel[1] < height - margin
    }
    if not usable:
        usable = tally

    def saturation(texel):
        """How far the texel is from grey, which is what colour means here."""
        pixel = atlas[texel[1], texel[0]]
        return min(float(pixel[1]) - float(pixel[0]),
                   float(pixel[2]) - float(pixel[0]))

    def blueness(texel):
        """How far the texel leans blue rather than green."""
        pixel = atlas[texel[1], texel[0]]
        return float(pixel[2]) - float(pixel[1])

    # The ring takes the most common colour, but only once the pale
    # highlights on the shards are out of the running: those are the
    # same hue a shade paler, and the mode lands on one of them often
    # enough to leave the finished ring looking like bare metal.
    strongest = max(saturation(texel) for texel in usable)
    solid = {
        texel: count for texel, count in usable.items()
        if saturation(texel) >= strongest * 0.72
    }
    ring_texel = max(solid, key=lambda key: solid[key])
    star_texel = max(solid, key=blueness)

    def to_uv(texel):
        return (texel[0] / (width - 1), texel[1] / (height - 1))

    def srgb(texel):
        pixel = atlas[texel[1], texel[0]]
        return [round(float(value), 3) for value in pixel[:3]]

    return to_uv(ring_texel), to_uv(star_texel), srgb(ring_texel), srgb(star_texel)


def ring_frame():
    """The ring's centre, the two directions it is drawn in, and its normal.

    The tilt is taken about the character's left-to-right axis, so the
    ring leans back rather than sideways, and it is negative so that
    the far side is the higher one -- a halo tipped the other way reads
    as a bowl the character is looking into.
    """
    tilt = math.radians(TILT_DEGREES)
    normal = Vector((0.0, math.sin(tilt), math.cos(tilt)))
    normal.normalize()
    axis_a = Vector((1.0, 0.0, 0.0))
    axis_a = (axis_a - normal * axis_a.dot(normal)).normalized()
    axis_b = normal.cross(axis_a)
    return CENTRE, axis_a, axis_b, normal


def build_ring(bm, centre, axis_a, axis_b, normal):
    """A closed ring of even section, swept as a flattened torus.

    Sweeping a circle along a circle is the one construction that gives
    a band with no ends to see: every part of it is the same shape as
    every other part, so no edge of it can be the place where the
    surface stops.
    """
    rings = []
    for step in range(RING_STEPS):
        theta = 2.0 * math.pi * step / RING_STEPS
        on_ring = axis_a * (RADIUS * math.cos(theta)) + axis_b * (RADIUS * math.sin(theta))
        outward = on_ring.normalized()
        cross_ring = []
        for cross in range(SECTION_SIDES):
            phi = 2.0 * math.pi * cross / SECTION_SIDES
            offset = outward * (WIDTH * math.cos(phi)) + normal * (DEPTH * math.sin(phi))
            cross_ring.append(bm.verts.new(centre + on_ring + offset))
        rings.append(cross_ring)

    made = []
    for step in range(RING_STEPS):
        current = rings[step]
        following = rings[(step + 1) % RING_STEPS]
        for cross in range(SECTION_SIDES):
            after = (cross + 1) % SECTION_SIDES
            face = bm.faces.new((current[cross], current[after], following[after], following[cross]))
            face.smooth = True
            made.append(face)
    return [vertex for cross_ring in rings for vertex in cross_ring], made


def build_star(bm, centre, axis_a, axis_b, normal):
    """The star that rides on the ring: a flat badge with real thickness.

    It is given thickness because a star drawn as a single sheet reads
    as a hole in the render from every angle but one -- and it is the
    one solid on the character with an edge on all twelve of its
    sides, so an edge that catches the light is what stops it looking
    like a decal painted on.
    """
    angle = math.radians(STAR_ANGLE_DEGREES)
    radial = axis_a * math.cos(angle) + axis_b * math.sin(angle)
    radial = radial.normalized()
    lean = math.radians(STAR_FACE_TILT_DEGREES)
    facing = normal * math.cos(lean) + axis_a.cross(normal) * math.sin(lean)
    facing.normalize()
    along = facing.cross(radial).normalized()
    middle = centre + radial * RADIUS
    half = facing * (STAR_DEPTH * 0.5)

    points = STAR_POINTS * 2
    outline = []
    for index in range(points):
        theta = index * (math.pi / STAR_POINTS) + math.pi * 0.5
        reach = STAR_OUTER if index % 2 == 0 else STAR_INNER
        outline.append(middle + radial * (reach * math.cos(theta)) + along * (reach * math.sin(theta)))

    made = []
    sides = []
    for side in (1.0, -1.0):
        hub = bm.verts.new(middle + half * side)
        corners = [bm.verts.new(point + half * side) for point in outline]
        for index in range(points):
            face = bm.faces.new((hub, corners[index], corners[(index + 1) % points]))
            face.smooth = False
            made.append(face)
        sides.append(corners)

    front, back = sides
    for index in range(points):
        face = bm.faces.new((front[index], back[index], back[(index + 1) % points], front[(index + 1) % points]))
        face.smooth = False
        made.append(face)
    return made


def rebuild_halo(mesh, build_geometry=True):
    """Replace the halo's remains with a ring and a star that hold up.

    `build_geometry` is off when the halo is not wanted in this mesh: the
    shards still have to go either way, but the ring itself is built as an
    object of its own with a material that can carry a light, so adding it
    here as well would put two halos above the character's head.
    """
    atlas = load_atlas()
    if mesh.uv_layers.active is None:
        return {"skipped": "no uv layer"}
    had_custom_normals = mesh.has_custom_normals

    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.active

    shells = connected_faces(bm)
    body = max(shells, key=len)
    remains = []
    for group in shells:
        if group is body:
            continue
        coloured = 0
        for face in group:
            texel = face_texel(face, uv_layer, atlas)
            if is_cyan(atlas[texel[1], texel[0]]):
                coloured += 1
        if coloured >= len(group) * 0.5:
            remains.append(group)
    if not remains:
        bm.free()
        return {"skipped": "nothing outside the body is painted like a halo"}

    shards = [face for group in remains for face in group]
    palette = halo_palette(atlas, shards, uv_layer)
    if palette[0] is None:
        bm.free()
        return {"skipped": "the halo is not painted a colour to match"}
    ring_uv, star_uv, ring_colour, star_colour = palette

    discarded = len(shards)
    bmesh.ops.delete(bm, geom=shards, context="FACES")

    ring_faces = []
    star_faces = []
    centre, axis_a, axis_b, normal = ring_frame()
    if build_geometry:
        _, ring_faces = build_ring(bm, centre, axis_a, axis_b, normal)
        star_faces = build_star(bm, centre, axis_a, axis_b, normal)

        for face in ring_faces:
            for loop in face.loops:
                loop[uv_layer].uv = ring_uv
        for face in star_faces:
            for loop in face.loops:
                loop[uv_layer].uv = star_uv

    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    # The ring is a smooth surface and the star is a flat one, and the
    # two want different normals.  Writing them only matters where the
    # character arrived with normals of its own to preserve; where it
    # did, the new geometry is added alongside them rather than in
    # place of them, and where it did not, Blender's own are left.
    if had_custom_normals and mesh.has_custom_normals:
        corners = [each.vector.copy() for each in mesh.corner_normals]
        first = len(mesh.polygons) - len(ring_faces) - len(star_faces)
        for offset, polygon in enumerate(mesh.polygons[first:]):
            span = range(polygon.loop_start, polygon.loop_start + polygon.loop_total)
            smooth = offset < len(ring_faces)
            for index in span:
                vertex_index = mesh.loops[index].vertex_index
                corners[index] = mesh.vertices[vertex_index].normal if smooth else polygon.normal
        mesh.normals_split_custom_set([each.copy() for each in corners])
        mesh.update()

    return {
        "discardedFaces": discarded,
        "ringFaces": len(ring_faces),
        "starFaces": len(star_faces),
        "radius": RADIUS,
        "width": WIDTH,
        "depth": DEPTH,
        "centre": [round(float(v), 4) for v in centre],
        "normal": [round(float(v), 4) for v in normal],
        "ringUV": [round(v, 5) for v in ring_uv],
        "starUV": [round(v, 5) for v in star_uv],
        "ringColour": ring_colour,
        "starColour": star_colour,
    }
