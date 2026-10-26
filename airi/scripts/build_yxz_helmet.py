"""Rebuild the crown of the YXZ helmet.

The scan of the head is broken in two different ways, and both of them
show on screen.

The first is the glass bubble.  The design has a clear bubble over the
head with the halo ring round it, and in the scan that bubble is a
separate skin of geometry standing clear of the white helmet.  The scan
shattered it, and what survives is a torn sheet lying across the face.
It is the reason the character reads as glassy and hazy on screen, and
it is also the source of a good half of the debris: every fragment of
the bubble catches the key light on its own and twinkles.

The second is the crown of the helmet itself.  It was torn into pieces
along the line of the bubble's rim, so the top of the head is a drift of
small flakes with a hole through it, and the star on the forehead sits
in the middle of the damage.

So the head is put back together in three moves.

The bubble goes.  Its fragments are the pieces of the scan that stand
clear of the sphere the helmet is built on, so they are found by how far
they sit from it and not by how big they are.  The star is on that same
clear of the helmet as the bubble was -- it is a raised emblem -- so it
is kept by where it is.

The flakes go.  A panel of the helmet is thousands of faces and a flake
is dozens, and on the head the flakes are the pieces that stand on their
own rather than being welded to a bigger panel.

And then the crown is built.  The helmet is very nearly a sphere, and
the fit is good to a couple of millimetres over a head this size, so the
missing part of it is a piece of that sphere.  It is built as one
smooth cap and set just outside the helmet, so that it covers the torn
edge of the old shell instead of leaving it standing against the new
surface, and it is tapered back down to the shell at its own rim so
that the join between them is not a step to be seen.  The opening for
the visor is cut from the cap, a little inside the line of the visor,
so the chrome bezel round the visor closes over the join.

The cap is textured with the model's own white, taken from the clean
plate on the forehead, so that it is the same white as the helmet
around it and not a second white.

Usage:
  blender -b -P scripts/build_yxz_helmet.py -- \
    --source <glb> --output <glb> [--radius 0.289] [--bubble-radius 0.300] \
    [--dome-radius 0.2905] [--min-flake 320] [--report-only]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from mathutils.kdtree import KDTree


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def shells(bm):
    """Every face of the mesh, grouped by the shell it belongs to."""
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
    groups.sort(key=lambda group: min(face.index for face in group))
    return groups


def circular_smooth(values, passes):
    """Average a periodic list with itself, keeping the period."""
    count = len(values)
    current = list(values)
    for _ in range(passes):
        following = []
        for index in range(count):
            total = 0.0
            weight = 0.0
            for offset in range(-2, 3):
                sample = current[(index + offset) % count]
                factor = 3.0 - abs(offset)
                total += sample * factor
                weight += factor
            following.append(total / weight)
        current = following
    return current


def face_colour(face, uv_layer, pixels, width, height):
    """The colour of the texture under the middle of a face."""
    if uv_layer is None or pixels is None:
        return None
    total = [0.0, 0.0, 0.0]
    count = 0
    for loop in face.loops:
        uv = loop[uv_layer].uv
        x = min(width - 1, max(0, int(uv.x * width)))
        y = min(height - 1, max(0, int(uv.y * height)))
        offset = (y * width + x) * 4
        total[0] += pixels[offset]
        total[1] += pixels[offset + 1]
        total[2] += pixels[offset + 2]
        count += 1
    if not count:
        return None
    return [channel / count for channel in total]


def load_texture(body, uv_layer):
    """The base colour image of the body's own material, as flat pixels."""
    if not body.data.materials:
        return None, None, 0
    material = body.data.materials[0]
    if not material.use_nodes:
        return None, None, 0
    for node in material.node_tree.nodes:
        if node.type != "TEX_IMAGE" or not node.image:
            continue
        image = node.image
        width, height = image.size
        pixels = [0.0] * (width * height * 4)
        image.pixels.foreach_get(pixels)
        return pixels, width, height
    return None, None, 0


def main() -> None:
    source = Path(value_after("--source"))
    output = Path(value_after("--output"))
    centre = Vector([float(v) for v in
                     value_after("--centre", "0.038,-0.001,0.094").split(",")])
    radius = float(value_after("--radius", "0.289"))
    bubble_radius = float(value_after("--bubble-radius", "0.300"))
    dome_radius = float(value_after("--dome-radius", "0.2905"))
    dome_tip = float(value_after("--dome-tip", "0.2884"))
    crown_lift = float(value_after("--crown-lift", "0.004"))
    blade_degrees = float(value_after("--blade-degrees", "88.0"))
    rim_fall = float(value_after("--rim-fall", "2.0"))
    rim_floor = math.radians(float(value_after("--rim-floor", "34.0")))
    min_flake = int(value_after("--min-flake", "200"))
    segments = int(value_after("--segments", "160"))
    rings = int(value_after("--rings", "56"))
    # How far the new cap reaches down over the shell it is put on.
    # The shell is cut along the cap's own lower edge, so the two
    # surfaces never share a pixel, and the cap's edge sits outside the
    # shell it is covering, so it hides the tear it was built to hide.
    cap_overlap = float(value_after("--cap-overlap", "1.5"))
    report_only = "--report-only" in sys.argv
    trim_only = "--trim-only" in sys.argv

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    body = max(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: len(obj.data.vertices),
    )

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    pixels, tex_width, tex_height = load_texture(body, uv_layer)

    # The star is a raised emblem on the forehead, and it stands clear of
    # the helmet by about the same as the bubble did, so it is kept by
    # where it is rather than by how big it is.
    keep_box = [float(v) for v in
                value_after("--keep-box", "0.15,-0.22,0.22,0.28,0.14,0.42").split(",")]

    def in_keep_box(point):
        return all(keep_box[axis] <= point[axis] <= keep_box[axis + 3]
                   for axis in range(3))

    def radius_of(point):
        return (point - centre).length

    # --- the bubble comes off -------------------------------------------
    # The bubble is the skin of geometry that stands clear of the sphere
    # the helmet is built on.  It is taken off face by face rather than
    # shell by shell, because the scan welded the bubble to the helmet
    # in places and there is no shell that is only bubble.
    doomed = []
    doomed_set = set()
    bubble_face_count = 0
    bubble_low = [1e9, 1e9, 1e9]
    bubble_high = [-1e9, -1e9, -1e9]
    for face in bm.faces:
        middle = face.calc_center_median()
        distance = radius_of(middle)
        if distance <= bubble_radius:
            continue
        # Only the head is looked at.  The bubble is on the head; the
        # rest of the character is a long way from the head's centre and
        # is not glass.
        if distance > 0.42:
            continue
        # The bubble is a skin over the head.  It does not go below the
        # head, and the shoulders and the wings are below it.
        if middle.z < centre.z - 0.16:
            continue
        if in_keep_box(middle):
            continue
        doomed.append(face)
        doomed_set.add(face)
        bubble_face_count += 1
        for axis in range(3):
            bubble_low[axis] = min(bubble_low[axis], middle[axis])
            bubble_high[axis] = max(bubble_high[axis], middle[axis])

    # --- the flakes come off --------------------------------------------
    # A flake is a piece of the crown that stands on its own.  The panels
    # of the helmet are thousands of faces and welded to their
    # neighbours; a flake is dozens and is not.
    groups = shells(bm)
    # The pieces of the star come off as well.
    #
    # The star on the forehead is a mark of the design, and the scan
    # left it in three pieces.  Three pieces of a star on a smooth white
    # helmet read as damage rather than as a star: what the viewer sees
    # is a scatter of bright triangles with hard edges and gaps between
    # them, sitting on the forehead where the face is, and it is the
    # thing that most says the model is broken.
    #
    # The box is where the pieces are.  The head is turned in its rest
    # pose, so the forehead is not the front of the head in the file --
    # it is off to one side -- and the box was measured off the shipped
    # asset rather than guessed at.
    star_box = [float(v) for v in
                value_after("--star-box",
                            "0.0,-0.30,0.17,0.20,-0.18,0.30").split(",")]
    max_decal_faces = int(value_after("--max-decal-faces", "3000"))
    star_luma = float(value_after("--star-luma", "0.65"))

    def in_star_box(point):
        return all(star_box[axis] <= point[axis] <= star_box[axis + 3]
                   for axis in range(3))

    star_pieces = []
    # The star is a badge of the design and it is kept unless the caller
    # says otherwise.
    #
    # It used to be taken off here, every time, because the crown of the
    # helmet had been rebuilt over the top of it and a star lying under a
    # smooth cap is a star nobody sees.  But the crown is only rebuilt
    # over the tear now, and the tear does not reach the badge, so the
    # badge is still there to keep and there is nothing to hide.
    keep_star = "--keep-star" in sys.argv
    for group in groups:
        if keep_star:
            break
        if len(group) > max_decal_faces:
            continue
        middle = [face.calc_center_median() for face in group]
        if not middle:
            continue
        average = Vector((sum(p.x for p in middle) / len(middle),
                          sum(p.y for p in middle) / len(middle),
                          sum(p.z for p in middle) / len(middle)))
        if not in_star_box(average):
            continue
        # Only the bright pieces go.  The visor is a dark thing set into
        # the front of the helmet and it lives in the same box; taking a
        # dark island out would put a hole in the screen, which is the
        # one part of the head that must not have a hole in it.
        colours = []
        for face in group:
            colour = face_colour(face, uv_layer, pixels, tex_width, tex_height)
            if colour is not None:
                colours.append(colour)
        if not colours:
            continue
        luma = sum(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
                   for c in colours) / len(colours)
        if luma < star_luma:
            continue
        star_pieces.append(len(group))
        for face in group:
            if face not in doomed_set:
                doomed_set.add(face)
                doomed.append(face)

    flakes = []
    for group in groups:
        if len(group) >= min_flake:
            continue
        middle = [face.calc_center_median() for face in group]
        if not middle:
            continue
        average = Vector((sum(p.x for p in middle) / len(middle),
                          sum(p.y for p in middle) / len(middle),
                          sum(p.z for p in middle) / len(middle)))
        # Only the crown is cleaned this way.  Further down the head the
        # small pieces are the trim, the chrome round the visor and the
        # little panels, and they are wanted.
        if average.z < 0.24 or radius_of(average) < 0.26:
            continue
        if not in_keep_box(average):
            flakes.append(group)
    flake_faces = sum(len(group) for group in flakes)
    for group in flakes:
        for face in group:
            if face not in doomed_set:
                doomed_set.add(face)
                doomed.append(face)

    # --- the blades come off ---------------------------------------------
    # A panel of the helmet lies on the sphere, so its faces point
    # straight out from the centre of the head.  A blade of torn shell
    # standing up out of the helmet points somewhere else entirely, and
    # those are the pieces that read as a saw edge along the crown.  The
    # test is the angle between the face and the radius, and a panel is
    # within a degree or so of it.
    blades = []
    for face in bm.faces:
        middle = face.calc_center_median()
        distance = radius_of(middle)
        if distance < 0.255 or distance > 0.32:
            continue
        if middle.z < centre.z - 0.05:
            continue
        if in_keep_box(middle):
            continue
        radial = (middle - centre).normalized()
        if face.normal.dot(radial) < math.cos(math.radians(blade_degrees)):
            blades.append(face)
    blade_faces = len(blades)
    for face in blades:
        if face not in doomed_set:
            doomed_set.add(face)
            doomed.append(face)

    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bmesh.ops.delete(
            bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
        )
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # --- what is left, and where ----------------------------------------
    groups = shells(bm)
    body_group = max(groups, key=len)

    tree = KDTree(len(bm.verts))
    for vertex in bm.verts:
        tree.insert(vertex.co, vertex.index)
    tree.balance()

    # The visor is the dark screen set into the front of the helmet.  It
    # is found by the colour of the texture under it, because it is the
    # only dark thing on the head, and it is what the opening in the new
    # crown has to be shaped around.
    visor_faces = []
    for face in bm.faces:
        middle = face.calc_center_median()
        if radius_of(middle) > 0.285 or radius_of(middle) < 0.15:
            continue
        if middle.x < centre.x:
            continue
        colour = face_colour(face, uv_layer, pixels, tex_width, tex_height)
        if colour is None:
            continue
        luma = 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]
        if luma < 0.42:
            visor_faces.append(face)

    def cut_elevation(point):
        """The bearing and the elevation of a point, on the head's own
        sphere.  Everything about the shape of the crown is worked out
        in these two numbers."""
        direction = (point - centre).normalized()
        phi = math.atan2(direction.y, direction.x)
        if phi < 0:
            phi += math.tau
        theta = math.asin(max(-1.0, min(1.0, direction.z)))
        column = int(phi / math.tau * phi_count) % phi_count
        return theta, column

    report = {
        "source": str(source),
        "facesAfterTrim": len(bm.faces),
        "bubbleFaces": bubble_face_count,
        "flakeFaces": flake_faces,
        "bladeFaces": blade_faces,
        "visorFaces": len(visor_faces),
        "shells": len(groups),
        "bubbleBox": [round(v, 3) for v in bubble_low + bubble_high],
        "starPieces": star_pieces,
    }
    print("YXZ_HELMET " + json.dumps(report))

    if report_only or trim_only:
        if trim_only:
            bm.to_mesh(body.data)
            body.data.update()
            bm.free()
            bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")
        bm.free()
        return

    # --- the map of what the head is covered with ------------------------
    # The vertex normals are read below to tell a piece of shell that
    # lies flat on the dome from a flake that has been torn up off it, so
    # they have to be brought up to date with the deletions first.
    bm.normal_update()
    phi_count = segments
    theta_count = rings * 2
    covered = [[False] * theta_count for _ in range(phi_count)]
    visored = [[False] * theta_count for _ in range(phi_count)]

    def direction_slot(direction):
        phi = math.atan2(direction.y, direction.x)
        if phi < 0:
            phi += math.tau
        theta = math.asin(max(-1.0, min(1.0, direction.z)))
        column = int(phi / math.tau * phi_count) % phi_count
        row = int((theta + math.pi / 2) / math.pi * theta_count)
        row = max(0, min(theta_count - 1, row))
        return column, row

    for vertex in bm.verts:
        distance = radius_of(vertex.co)
        if abs(distance - radius) > 0.02:
            continue
        radial = (vertex.co - centre).normalized()
        # Only a piece of shell that lies flat on the dome counts as
        # covering it.  The scan left a drift of torn flakes lying over
        # the helmet, and they lie over it too: they are on the dome's
        # radius and they would fill the map of the tear in, and then
        # the tear would never be found and the crown would be built on
        # the wrong line.  A flake that has been torn up off the dome
        # has a normal that does not point out of the head.
        # Blender 5 removed BMLoop.normal, so the vertex normal is read
        # from the vertex itself.  It has to be up to date before it is
        # read, or it is the normal of the mesh as it was loaded.
        normal = vertex.normal
        if normal.length < 1e-6:
            continue
        normal = normal.normalized()
        if normal.dot(radial) < math.cos(math.radians(25.0)):
            continue
        column, row = direction_slot(radial)
        covered[column][row] = True

    for face in visor_faces:
        middle = face.calc_center_median()
        column, row = direction_slot((middle - centre).normalized())
        # The visor is a screen and it is not a point: it fills the whole
        # opening, so the opening is grown to the size of the visor.
        for dcolumn in range(-4, 5):
            for drow in range(-4, 5):
                if dcolumn * dcolumn + drow * drow > 25:
                    continue
                row2 = max(0, min(theta_count - 1, row + drow))
                column2 = (column + dcolumn) % phi_count
                visored[column2][row2] = True
                covered[column2][row2] = False

    # --- the rim of the new crown ----------------------------------------
    # For each bearing, the lowest hole in the helmet.  The crown has to
    # reach below that everywhere, or the hole is not closed.
    tear = [math.pi / 2] * phi_count
    for column in range(phi_count):
        lowest = None
        for row in range(theta_count):
            theta = (row + 0.5) / theta_count * math.pi - math.pi / 2
            if theta < math.radians(35.0):
                continue
            if covered[column][row] or visored[column][row]:
                continue
            if lowest is None or theta < lowest:
                lowest = theta
        if lowest is not None:
            tear[column] = lowest

    # Fill the bearings that have no hole at all from their neighbours,
    # then take the shape down a little so that it is smooth without
    # leaving a gap anywhere.
    for _ in range(4):
        known = [c for c in range(phi_count) if tear[c] < math.pi / 2]
        if not known:
            break
        for column in range(phi_count):
            if tear[column] < math.pi / 2:
                continue
            neighbours = [tear[(column + offset) % phi_count] for offset in range(-8, 9)]
            neighbours = [n for n in neighbours if n < math.pi / 2]
            if neighbours:
                tear[column] = min(neighbours)

    # The line of the tear is jagged, and a cap built to follow it would
    # be jagged too.  So the shell is cut along a smooth line instead,
    # below the tear everywhere, and the crown is built above that line.
    # The line is pulled towards the lowest point of the tear so that it
    # is smooth, and then held under the tear so that nothing is left
    # open above it.
    floor = min(tear)
    shaped = [floor + (tear[c] - floor) * 0.55 for c in range(phi_count)]
    shaped = circular_smooth(shaped, 30)
    margin = math.radians(4.0)
    for column in range(phi_count):
        shaped[column] = min(shaped[column], tear[column] - margin)
        shaped[column] = max(shaped[column], rim_floor)
    # The line of the tear jumps about, because a tear does, and a cap
    # built on a line that jumps about has a notch in it.  So the line
    # is smoothed again after the holding above, and this is the line
    # the cap is actually put on.
    shaped = circular_smooth(shaped, 24)

    rim_degrees = [round(math.degrees(value), 1) for value in shaped]
    print("YXZ_HELMET_RIM " + json.dumps({
        "floor": round(math.degrees(floor), 1),
        "min": round(min(rim_degrees), 1),
        "max": round(max(rim_degrees), 1),
        "sample": rim_degrees[::12],
    }))

    # --- where the cap's own edge goes -----------------------------------
    # The cap is put on over the torn edge of the shell, and it reaches
    # down past the line the shell was cut along so that the tear is
    # under the cap and not beside it.
    #
    # The shell is then cut along the cap's lower edge rather than along
    # the line above it, and that is the whole of the difference between
    # a head that reads as whole and a head that reads as shattered.
    # The two surfaces used to share a band of nine degrees: the shell
    # was left standing in the band and the cap was drawn over it, both
    # of them a fraction of a millimetre apart, and the depth test could
    # not choose between them.  What that looks like is a drift of torn
    # white flakes over the top of the head with shadows under them.
    #
    # The visor is the screen set into the front of the helmet, and the
    # cap's edge may not come down over it: the screen is the face.  So
    # the edge of the screen is measured, bearing by bearing, and the
    # cap's edge is held just above it.  Where there is no screen the
    # edge is free, and it goes as low as the tear needs it to.
    visor_top = [-math.pi] * phi_count
    for face in visor_faces:
        middle = face.calc_center_median()
        theta, column = cut_elevation(middle)
        # The screen is the one dark thing on the front of the head, and
        # only its upper edge matters.  The rest of the head has dark
        # parts of its own -- the chest, the shadow under the rim -- and
        # they are not the screen, and letting them in would put the
        # edge of the new crown at the wrong height.
        direction = (middle - centre).normalized()
        if direction.dot(Vector((1.0, 0.0, 0.0))) < math.cos(math.radians(70.0)):
            continue
        if theta > math.radians(55.0) or theta < math.radians(-45.0):
            continue
        if radius_of(middle) < 0.20:
            continue
        if theta > visor_top[column]:
            visor_top[column] = theta

    cap_bottom = []
    for column in range(phi_count):
        value = shaped[column] - math.radians(rim_fall) - math.radians(cap_overlap)
        if visor_top[column] > -math.pi:
            value = max(value, visor_top[column] - math.radians(cap_overlap))
        cap_bottom.append(max(value, math.radians(rim_floor)))
    cap_bottom = circular_smooth(cap_bottom, 6)
    cap_bottom = [max(value, math.radians(rim_floor)) for value in cap_bottom]
    print("YXZ_HELMET_CAP " + json.dumps({
        "min": round(math.degrees(min(cap_bottom)), 1),
        "max": round(math.degrees(max(cap_bottom)), 1),
        "sample": [round(math.degrees(value), 1)
                   for value in cap_bottom[::12]],
        "visorTop": [round(math.degrees(value), 1)
                     for value in visor_top[::12]],
    }))

    # --- the shell is cut along that line -------------------------------
    # How far out from the middle of the head the shell reaches just
    # below the line the cap is put on.  The cap's own edge is set just
    # outside that, so it lies over the shell it covers rather than
    # inside it, and the join is a line rather than a ledge.
    edge_radius = [0.0] * phi_count
    for face in bm.faces:
        middle = face.calc_center_median()
        distance = radius_of(middle)
        if distance > radius + 0.012:
            continue
        theta, column = cut_elevation(middle)
        if theta > cap_bottom[column]:
            continue
        if cap_bottom[column] - theta > math.radians(6.0):
            continue
        if distance > edge_radius[column]:
            edge_radius[column] = distance
    for column in range(phi_count):
        edge_radius[column] = (edge_radius[column] + 0.0006
                               if edge_radius[column] > 0.0 else radius)
    edge_radius = circular_smooth(edge_radius, 8)
    report["edgeRadius"] = [round(value, 4) for value in edge_radius[::12]]

    above = []
    doomed_faces = set()
    for face in bm.faces:
        middle = face.calc_center_median()
        theta, column = cut_elevation(middle)
        if theta > cap_bottom[column]:
            above.append(face)
            doomed_faces.add(face)
            continue
        # A face is judged by its middle, but a long face can reach a
        # long way above its own middle, and those are the blades that
        # stand up out of the crown and catch the light.
        for vertex in face.verts:
            vtheta, vcolumn = cut_elevation(vertex.co)
            if vtheta > cap_bottom[vcolumn]:
                above.append(face)
                doomed_faces.add(face)
                break

    # An island the cut passes through is a decal the cut has sliced in
    # half, and half a decal is worse than none.
    #
    # The star on the forehead is a raised emblem that stands on the
    # helmet as a shell of its own, and the crown's rim comes down
    # through the middle of it.  What that leaves is a torn violet streak
    # lying across a smooth white dome, with a scatter of white shards
    # round it, and it is the single most obviously broken thing on the
    # character.
    #
    # A small island is never part of the helmet's shell -- the shell is
    # one big welded piece -- so anything small enough to be a decal and
    # small enough to be sliced is taken whole.  The helmet under it is
    # untouched, so what is left is a clean surface where the decal was,
    # and the crown is built over the space above it.
    decals = []
    for group in shells(bm):
        if len(group) > max_decal_faces:
            continue
        inside = [face for face in group if face in doomed_faces]
        if not inside or len(inside) == len(group):
            continue
        decals.append((group, len(inside), len(group)))
    for group, _, _ in decals:
        for face in group:
            if face not in doomed_faces:
                doomed_faces.add(face)
                above.append(face)
    # `above` is a list because the cut wants the order it found them in,
    # but a face may already be on it, and bmesh refuses a delete that
    # names the same face twice.
    above = list(dict.fromkeys(above))
    if decals:
        report["decalsRemoved"] = [
            {"inside": inside, "total": total} for _, inside, total in decals
        ]

    # The edge of the cut is the join between the old shell and the new
    # crown.  It is found as the edges with a face on one side that is
    # going and a face on the other that is not, and the ring of them is
    # followed round to find the cut itself.  There are other rings: the
    # rim of the visor, the star standing on its own, the little holes
    # the scan left.  The cut is the longest of them by far.
    cut_edges = set()
    for face in above:
        for edge in face.edges:
            other = [f for f in edge.link_faces if f is not face]
            if other and other[0] not in doomed_faces:
                cut_edges.add(edge)

    adjacency = {}
    for edge in cut_edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)

    loops = []
    seen = set()
    for edge in cut_edges:
        if edge in seen:
            continue
        stack = [edge]
        component = []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            for vertex in current.verts:
                for other in adjacency.get(vertex, []):
                    if other not in seen:
                        stack.append(other)
        loops.append(component)
    loops.sort(key=len, reverse=True)
    loop_report = []
    for component in loops[:6]:
        vertices = {v for edge in component for v in edge.verts}
        elevations = []
        for vertex in vertices:
            theta, _ = cut_elevation(vertex.co)
            elevations.append(math.degrees(theta))
        loop_report.append({
            "edges": len(component),
            "low": round(min(elevations), 1) if elevations else None,
            "high": round(max(elevations), 1) if elevations else None,
        })
    print("YXZ_HELMET_LOOPS " + json.dumps(loop_report))

    bmesh.ops.delete(bm, geom=above, context="FACES")
    bmesh.ops.delete(
        bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS"
    )
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # The white of the crown is the white of the helmet.  It is taken
    # from the clean plate on the forehead, which is the only broad,
    # unbroken white on the head.
    uv_value = Vector((0.5, 0.5))
    if uv_layer is not None and pixels is not None:
        candidates = []
        for vertex in bm.verts:
            distance = radius_of(vertex.co)
            if abs(distance - radius) > 0.012:
                continue
            link = vertex.link_loops
            if not link:
                continue
            uv = link[0][uv_layer].uv
            colour = face_colour(
                type("F", (), {"loops": [link[0]]})(),
                uv_layer, pixels, tex_width, tex_height,
            )
            if colour is None:
                continue
            luma = 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]
            if luma < 0.70:
                continue
            candidates.append((luma, uv.x, uv.y))
        if candidates:
            candidates.sort()
            # The whitest plate of the helmet, so that the crown is the
            # same white as the shell it sits on.
            brightest = candidates[-1]
            uv_value = Vector((brightest[1], brightest[2]))
            report["crownWhite"] = [round(brightest[0], 3),
                                    round(brightest[1], 4), round(brightest[2], 4)]
            report["crownWhitePool"] = len(candidates)

    crown = build_crown(bm, cap_bottom, centre, radius + crown_lift, rings,
                        uv_layer, uv_value, rim_fall, edge_radius)

    report["crownFaces"] = crown
    report["facesFinal"] = len(bm.faces)
    print("YXZ_HELMET " + json.dumps(report))

    bm.to_mesh(body.data)
    body.data.update()
    bm.free()

    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")


def build_crown(bm, boundary, centre, radius, rings, uv_layer, uv_value, rim_fall,
                edge_radius):
    """The new crown of the helmet, on the same sphere as the old shell.

    The crown is a cap of a sphere, and the shell it sits on is very
    nearly a sphere too, so the two agree over the whole head.  The cap
    is set a hair outside the shell, which puts it over the torn edge of
    the old shell instead of leaving the tear standing against it, and
    its own rim is a smooth curve taken from the line the shell was cut
    along.
    """
    if uv_layer is None or len(boundary) < 16:
        return 0
    made = 0
    crown_faces = []
    crown_faces = []
    count = len(boundary)
    top = math.pi / 2

    def point_at(phi, elevation):
        return Vector((
            math.cos(elevation) * math.cos(phi),
            math.cos(elevation) * math.sin(phi),
            math.sin(elevation),
        ))

    # The rim of the cap is the line the shell was cut along, so the two
    # surfaces meet and never overlap.
    rim_elevation = list(boundary)

    grid = []
    for step in range(rings):
        fraction = step / (rings - 1)
        row = []
        for column in range(count):
            phi = math.tau * column / count
            elevation = top + (rim_elevation[column] - top) * fraction
            # The cap stands a little proud of the shell over the crown,
            # which is what puts it over the torn edge, and it starts on
            # the shell's own surface at its own rim, so that the join
            # is a line and not a step.
            above = elevation - rim_elevation[column]
            t = max(0.0, min(1.0, above / math.radians(rim_fall)))
            t = t * t * (3.0 - 2.0 * t)
            reach = edge_radius[column] + (radius - edge_radius[column]) * t
            row.append(bm.verts.new(centre + point_at(phi, elevation) * reach))
        grid.append(row)

    # The top of the head is a single point.
    pole = bm.verts.new(centre + Vector((0.0, 0.0, 1.0)) * radius)

    for column in range(count):
        follow = (column + 1) % count
        try:
            face = bm.faces.new((grid[0][column], grid[0][follow], pole))
        except ValueError:
            continue
        face.smooth = True
        crown_faces.append(face)
        made += 1
    for step in range(len(grid) - 1):
        for column in range(count):
            follow = (column + 1) % count
            try:
                face = bm.faces.new((grid[step][column], grid[step][follow],
                                     grid[step + 1][follow], grid[step + 1][column]))
            except ValueError:
                continue
            face.smooth = True
            crown_faces.append(face)
            made += 1

    # The crown is the model's own white, taken from the clean plate on
    # the forehead, so that it is the same white as the helmet around it.
    for face in crown_faces:
        for loop in face.loops:
            loop[uv_layer].uv = uv_value

    # The cap has to face outwards, like the shell it sits on.  Which
    # way round it was built depends on the way the ring was walked, and
    # a cap facing inwards is a cap lit from behind.
    bm.normal_update()
    for face in crown_faces:
        middle = face.calc_center_median()
        radial = (middle - centre).normalized()
        if face.normal.dot(radial) < 0.0:
            face.normal_flip()
    return made


if __name__ == "__main__":
    main()
