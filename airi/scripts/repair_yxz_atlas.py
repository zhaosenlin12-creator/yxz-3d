"""Repair the marks the scan leaves in the YXZ base-colour atlas.

The head reads as broken rather than as painted because of five
different kinds of mark, and every one of them is in the texture
rather than in the mesh:

* The boundary between the dark screen of the visor and the pale eye
  beside it is a sawtooth, and the tooth tips are bright.  Every tooth
  is a splinter of the wrong colour on the screen.
* A violet smear and a pale blob lie across the star badge on the
  crown, which the badge never had.
* A hard bright bar lies across the screen with a cut-off end, which
  reads as a crack.
* A few patches of a blue that does not belong to the surface they sit
  on float on the visor like flakes of paint.
* Thin scratches and specks are left all over the flat parts of the
  scan, and they are what reads as shattered.

Every repair is local: a texel that is out of place is given the
colour of the place it is in.  Nothing is repainted, so the paint the
figure is supposed to have -- the panel lines, the eye, the badge --
stays exactly where it was.

Usage:
  python scripts/repair_yxz_atlas.py <source.vrm> <out.vrm>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from glb_json import read_glb, write_glb


SCREEN = 1
PALE = 2
OTHER = 0

# The places on the atlas where a hard bright bar lies across the dark
# screen.  They were found and looked at one by one, because on the
# body the bright shapes are part of the design and must be left alone.
BRIGHT_BAR_BOXES = [
    (3190, 1636, 3320, 1678),
]

# The badge on the crown, where the violet smear and the pale blob
# lie.  The mark is only repaired where it has been looked at, because
# a violet shadow elsewhere on the figure is shading, not damage.
BADGE_BOXES = [
    (890, 3340, 1030, 3430),
]

# A hard bright streak that lies across the dark screen of the visor.
# It was found by picking the texels the streak is drawn on out of the
# live render, so the box is the streak's own extent rather than a
# guess.  The streak is a line, not a block, so it is cut out along
# its axis and filled with the colour of the screen around it.
VISOR_STREAK = [
    ((1140, 3981), (1168, 3999), 8),
    ((146, 3206), (160, 3216), 6),
]

# The lower left arm of the star badge, which the scan left washed out:
# the blue of the emblem has faded to a pale wash with fine streaks
# through it, so the arm reads as a torn flap rather than as one of the
# five points of the star.  The box is the arm itself, measured on the
# live render and then read back out of the atlas, so nothing outside it
# is touched.
BADGE_ARM_BOX = (864, 3380, 964, 3450)

def replace_image(document, binary, image_name, encoded):
    image_index = next(
        index for index, image in enumerate(document.get("images", []))
        if image.get("name") == image_name
    )
    image = document["images"][image_index]
    views = document["bufferViews"]
    blobs = []
    for view in views:
        start = view.get("byteOffset", 0)
        blobs.append(binary[start:start + view["byteLength"]])
    blobs[image["bufferView"]] = encoded
    offset = 0
    packed = bytearray()
    for view, blob in zip(views, blobs):
        padding = (-offset) % 4
        packed.extend(b"\x00" * padding)
        offset += padding
        view["byteOffset"] = offset
        view["byteLength"] = len(blob)
        packed.extend(blob)
        offset += len(blob)
    document["buffers"][0]["byteLength"] = len(packed)
    image["mimeType"] = "image/png"
    return bytes(packed)


def classify(pixels):
    """Split the atlas into the dark screen, the bright paint, the rest."""
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    blue = pixels[..., 2].astype(int)
    screen = (red < 105) & (green < 145) & (blue > 40) & (blue < 205)
    pale = (red > 145) & (green > 155) & (blue > 165)
    labels = np.full(red.shape, OTHER, dtype=np.uint8)
    labels[pale] = PALE
    labels[screen] = SCREEN
    return labels


def hue_of(pixels):
    """The hue and the saturation of every texel, in degrees and 0..1."""
    source = pixels[..., :3].astype(np.float32) / 255.0
    red = source[..., 0]
    green = source[..., 1]
    blue = source[..., 2]
    high = source.max(axis=2)
    low = source.min(axis=2)
    span = np.maximum(high - low, 1e-6)
    saturation = (high - low) / np.maximum(high, 1e-6)
    hue = np.zeros(high.shape, dtype=np.float32)
    red_max = high == red
    green_max = (high == green) & ~red_max
    blue_max = (high == blue) & ~red_max & ~green_max
    hue[red_max] = 60.0 * (((green[red_max] - blue[red_max]) / span[red_max]) % 6.0)
    hue[green_max] = 60.0 * (((blue[green_max] - red[green_max]) / span[green_max]) + 2.0)
    hue[blue_max] = 60.0 * (((red[blue_max] - green[blue_max]) / span[blue_max]) + 4.0)
    return hue, saturation


def nearest_class_colour(pixels, keep):
    """The colour of the nearest texel of the class that is kept."""
    _, labels = cv2.distanceTransformWithLabels(
        (~keep).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    flat = labels.reshape(-1)
    total = int(keep.sum())
    order = np.argsort(flat, kind="stable")
    positions = np.searchsorted(flat[order], np.arange(1, total + 1))
    lookup = np.zeros(total + 1, dtype=np.int64)
    lookup[1:] = order[positions]
    chosen = lookup[flat].reshape(labels.shape)
    height, width = pixels.shape[:2]
    return pixels[chosen // width, chosen % width]


def majority_mask(mask, size):
    """The local majority of a boolean mask."""
    return cv2.medianBlur((mask.astype(np.uint8)) * 255, size) > 127


def ring_of(component, size):
    ring = cv2.dilate(component.astype(np.uint8), np.ones((size, size), np.uint8)) > 0
    return ring & ~component


def inpaint_masked(pixels, mask):
    """Fill the marked texels by continuing the colour around them.

    Taking the colour of the nearest texel would leave a staircase of
    hard steps, which reads as more damage than the mark did.  The
    fill is a smooth continuation of the colour around the hole
    instead, so the surface looks like one surface again.
    """
    if not mask.any():
        return pixels
    ys, xs = np.nonzero(mask)
    y0 = max(0, int(ys.min()) - 12)
    y1 = min(pixels.shape[0], int(ys.max()) + 13)
    x0 = max(0, int(xs.min()) - 12)
    x1 = min(pixels.shape[1], int(xs.max()) + 13)
    window = pixels[y0:y1, x0:x1].copy()
    hole = (mask[y0:y1, x0:x1]).astype(np.uint8)
    filled = cv2.inpaint(window, hole, 5, cv2.INPAINT_TELEA)
    repaired = pixels.copy()
    repaired[y0:y1, x0:x1] = filled
    return repaired


def repair_flat_noise(pixels):
    """Take the scan's speckle out of the flat parts of the atlas.

    The scan leaves thin scratches and specks on surfaces that are
    otherwise one colour, and they are what makes the head look
    shattered rather than painted.  A texel is only touched when the
    patch around it is flat: where there is real detail, such as the
    grid in the eye, the patch is not flat and nothing happens.
    """
    source = pixels.astype(np.float32)
    size = 7
    channels = [cv2.medianBlur(pixels[..., channel], size) for channel in range(3)]
    medians = np.stack(channels, axis=2).astype(np.float32)
    means = np.stack([cv2.boxFilter(source[..., c], -1, (size, size)) for c in range(3)], axis=2)
    squares = np.stack([cv2.boxFilter(source[..., c] ** 2, -1, (size, size)) for c in range(3)], axis=2)
    deviation = np.sqrt(np.maximum(squares - means * means, 0)).mean(axis=2)
    distance = np.abs(source - medians).max(axis=2)
    noisy = (deviation < 9.0) & (distance > 11.0)
    repaired = pixels.copy()
    repaired[noisy] = medians[noisy].round().astype(np.uint8)
    return repaired, int(noisy.sum())


def repair_rough_edges(pixels):
    """Take the torn edge off the dark screen of the visor.

    The boundary where the dark screen of the visor meets the pale
    shell is torn.  The scan stitched the two surfaces out of separate
    pieces and the pieces do not meet: the edge is a row of teeth, some
    of the shell's own colour reaching into the screen and some of the
    screen's reaching out into the shell.  On its own that is a rough
    edge.  What made it read as shattered was the light: the rim term
    lit every one of those teeth as if it were a surface turned away
    from the camera, so the torn edge came out as a comb of bright
    whiskers standing over the dark screen, which is what broken glass
    looks like.

    The teeth are in the texture and not in the mesh, which is worth
    knowing: a flat grey render of the same file has a smooth rim, and
    the whole of the tear is the paint.  So the edge is repainted here.
    Each dark region is read as a shape, the shape is smoothed, and the
    texels where the paint disagrees with the smoothed shape are given
    the colour of the texels beside them that agree.
    """
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    blue = pixels[..., 2].astype(int)
    screen = ((red < 115) & (green < 145) & (blue > 40) & (blue < 205)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(screen, 8)
    kernel = np.ones((3, 3), np.uint8)
    repaired = pixels.copy()
    total = 0
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] < 20000:
            continue
        x, y, width, height = stats[index, :4]
        # The region is worked on in its own window, which is both much
        # faster and a promise that nothing outside the region is read
        # or written.
        x0 = max(0, x - 40)
        y0 = max(0, y - 40)
        x1 = min(pixels.shape[1], x + width + 40)
        y1 = min(pixels.shape[0], y + height + 40)
        window = repaired[y0:y1, x0:x1]
        island = (labels[y0:y1, x0:x1] == index).astype(np.uint8)
        band = (cv2.dilate(island, kernel, iterations=25)
                - cv2.erode(island, kernel, iterations=25)) > 0
        if not band.any():
            continue
        shape = (island > 0).astype(np.uint8) * 255
        smooth = cv2.medianBlur(shape, 15)
        disagree = band & ((smooth > 127) != (shape > 127))
        if not disagree.any():
            continue
        # Each side of the edge is filled from its own side, so the
        # screen keeps its colour and the shell keeps its own.
        keep_screen = (shape > 127) & ~disagree
        keep_shell = (shape <= 127) & ~disagree
        # The fill starts as the window itself: the fade at the edge of
        # the mask reaches a texel or two beyond the texels that were
        # actually repainted, and anything the fade touches has to have
        # a colour to fade towards.
        fill = window.copy()
        fill[disagree & (smooth > 127)] = nearest_class_colour(
            window, keep_screen)[disagree & (smooth > 127)]
        fill[disagree & (smooth <= 127)] = nearest_class_colour(
            window, keep_shell)[disagree & (smooth <= 127)]
        # The fill is faded in over a texel or two, so the edge is a
        # blend rather than a step.
        alpha = cv2.GaussianBlur(disagree.astype(np.float32), (0, 0), 1.2)[..., None]
        blended = (window.astype(np.float32) * (1 - alpha)
                   + fill.astype(np.float32) * alpha).round().astype(np.uint8)
        repaired[y0:y1, x0:x1] = blended
        total += int(disagree.sum())
    return repaired, total


def repair_splinters(pixels):
    """Take out the texels that are a different colour from their place.

    A texel that belongs to the screen but sits in the middle of the
    pale paint, or a texel of pale paint that sits in the middle of
    the screen, is a splinter: the boundary of the paint is ragged and
    these are its teeth.  Each one is given the colour of the class it
    is really in, taken from the nearest texel of that class.
    """
    labels = classify(pixels)
    screen = labels == SCREEN
    pale = labels == PALE
    screen_majority = majority_mask(screen, 9)
    pale_majority = majority_mask(pale, 9)
    pale_in_screen = pale & screen_majority & ~pale_majority
    screen_in_pale = screen & pale_majority & ~screen_majority
    repaired = pixels.copy()
    if pale_in_screen.any():
        repaired = inpaint_masked(repaired, pale_in_screen)
    if screen_in_pale.any():
        repaired = inpaint_masked(repaired, screen_in_pale)
    return repaired, {"pale_in_screen": int(pale_in_screen.sum()),
                      "screen_in_pale": int(screen_in_pale.sum())}


def fill_along_normal(pixels, mask):
    """Fill a mark by continuing what lies across it.

    The smear across the star badge lies along the edge of the badge's
    arm, with the blue of the badge on one side of it and the white of
    the shell on the other.  Filling along the direction that crosses
    the edge continues the edge rather than smearing it, so every texel
    of the mark takes the colour of the texel opposite it across the
    mark.
    """
    ys, xs = np.nonzero(mask)
    points = np.stack([xs, ys], axis=1).astype(float)
    centred = points - points.mean(axis=0)
    _, _, axes = np.linalg.svd(centred, full_matrices=False)
    direction = axes[0]
    normal = np.array([-direction[1], direction[0]])
    height, width = pixels.shape[:2]
    repaired = pixels.copy()
    for px, py in zip(xs.tolist(), ys.tolist()):
        found = []
        for sign in (1, -1):
            colour = None
            distance = 1
            for step in range(1, 40):
                ax = int(round(px + sign * normal[0] * step))
                ay = int(round(py + sign * normal[1] * step))
                if ax < 0 or ay < 0 or ax >= width or ay >= height:
                    break
                if not mask[ay, ax]:
                    colour = pixels[ay, ax].astype(float)
                    distance = step
                    break
            found.append((colour, distance))
        before = found[0]
        after = found[1]
        if before[0] is None and after[0] is None:
            continue
        if before[0] is None:
            colour = after[0]
        elif after[0] is None:
            colour = before[0]
        else:
            ratio = before[1] / float(before[1] + after[1])
            colour = before[0] * (1 - ratio) + after[0] * ratio
        repaired[py, px] = np.clip(colour, 0, 255).astype(np.uint8)
    return repaired


def repair_violet(pixels):
    """Take the violet smear off the star badge."""
    hue, saturation = hue_of(pixels)
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    violet = (saturation > 0.18) & (hue > 236) & (hue < 292) & (red > green + 5)
    inside = np.zeros(violet.shape, dtype=bool)
    for x0, y0, x1, y1 in BADGE_BOXES:
        inside[y0:y1, x0:x1] = True
    violet &= inside
    joined = cv2.dilate(violet.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined.astype(np.uint8), 8)
    repaired = pixels.copy()
    report = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 40 or area > 12000:
            continue
        component = labels == index
        if int((component & violet).sum()) < 20:
            continue
        ring = ring_of(component, 9)
        if not ring.any() or float((classify(pixels) == SCREEN)[ring].mean()) < 0.6:
            # The smear is not lying on the dark paint, so it is a
            # colour the figure is supposed to have.
            continue
        grown = cv2.dilate(component.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        repaired = fill_along_normal(repaired, grown)
        report.append("violet area=%d at %d,%d"
                      % (area, int(stats[index, cv2.CC_STAT_LEFT]),
                         int(stats[index, cv2.CC_STAT_TOP])))
    return repaired, report


def repair_pink(pixels):
    """Take the pale pink blob off the star badge."""
    hue, saturation = hue_of(pixels)
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    blue = pixels[..., 2].astype(int)
    # The blob is a pale pink that is almost white, so it is found by
    # its cast rather than by its saturation: the blue of the badge
    # and the white of the shell are both cooler than red.
    pink = (red > 195) & (red > green + 6) & (blue > green + 6)
    inside = np.zeros(pink.shape, dtype=bool)
    for x0, y0, x1, y1 in BADGE_BOXES:
        inside[y0:y1, x0:x1] = True
    pink &= inside
    joined = cv2.dilate(pink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined.astype(np.uint8), 8)
    screen = classify(pixels) == SCREEN
    repaired = pixels.copy()
    report = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 20 or area > 3000:
            continue
        component = labels == index
        if int((component & pink).sum()) < 20:
            continue
        ring = ring_of(component, 9)
        if not ring.any() or float(screen[ring].mean()) < 0.55:
            continue
        grown = cv2.dilate(component.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        repaired = inpaint_masked(repaired, grown)
        report.append("pink area=%d at %d,%d"
                      % (area, int(stats[index, cv2.CC_STAT_LEFT]),
                         int(stats[index, cv2.CC_STAT_TOP])))
    return repaired, report


def repair_wrong_blue(pixels):
    """Take the islands of the wrong blue off the screen.

    The scan leaves a few patches of a blue that does not belong to
    the surface they sit on.  They read as flakes of paint sitting on
    the visor, so each one is given the colour of the screen around it.
    """
    wrong = np.all(np.abs(pixels.astype(int) - np.array([36, 71, 113])) <= 2, axis=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(wrong.astype(np.uint8), 8)
    screen = classify(pixels) == SCREEN
    repaired = pixels.copy()
    report = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 12 or area > 3000:
            continue
        component = labels == index
        ring = ring_of(component, 11)
        if not ring.any() or float(screen[ring].mean()) < 0.7:
            continue
        grown = cv2.dilate(component.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        repaired = inpaint_masked(repaired, grown)
        report.append("wrong-blue area=%d" % area)
    return repaired, report


def repair_bright_bar(pixels):
    """Take the hard bright bar off the screen.

    The bar is a long bright streak lying on the dark screen with a
    cut-off end.  It is found by being brighter than the screen, by
    being long and thin, and by having the screen all around it.
    """
    screen = classify(pixels) == SCREEN
    mask = np.zeros(pixels.shape[:2], dtype=bool)
    report = []
    for x0, y0, x1, y1 in BRIGHT_BAR_BOXES:
        window = pixels[y0:y1, x0:x1]
        red = window[..., 0].astype(int)
        green = window[..., 1].astype(int)
        blue = window[..., 2].astype(int)
        bright = (red > 90) & (green > 110) & (blue > 130) & (blue < 235)
        local_screen = screen[y0:y1, x0:x1]
        # Only the long horizontal part of the bright shape is the bar;
        # the rim of the shell it starts from is not.
        ridge = cv2.morphologyEx(bright.astype(np.uint8), cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(ridge, 8)
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < 60 or area > 4000:
                continue
            component = labels == index
            ring = ring_of(component, 9)
            if not ring.any() or float(local_screen[ring].mean()) < 0.5:
                continue
            near = cv2.dilate(component.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
            patch = bright & near
            mask[y0:y1, x0:x1] |= patch
            x = int(stats[index, cv2.CC_STAT_LEFT])
            y = int(stats[index, cv2.CC_STAT_TOP])
            width = int(stats[index, cv2.CC_STAT_WIDTH])
            height = int(stats[index, cv2.CC_STAT_HEIGHT])
            report.append("bar area=%d at %d,%d %dx%d" % (area, x0 + x, y0 + y, width, height))
    if not mask.any():
        return pixels, report
    grown = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    repaired = pixels.copy()
    repaired = inpaint_masked(repaired, grown)
    return repaired, report


def repair_visor_streak(pixels):
    """Take the hard bright streak off the screen of the visor.

    The streak is a hard bright line lying across the dark screen with
    a cut off end, and it reads as a crack in the glass.  It is found
    by being bright, by lying on the screen, and by running along the
    line it was measured on.
    """
    red = pixels[..., 0].astype(int)
    green = pixels[..., 1].astype(int)
    blue = pixels[..., 2].astype(int)
    bright = (red > 110) & (green > 170) & (blue > 185)
    screen = (red < 115) & (green < 145) & (blue > 40) & (blue < 205)
    height, width = pixels.shape[:2]
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    mask = np.zeros((height, width), dtype=bool)
    report = []
    for (x0, y0), (x1, y1), half in VISOR_STREAK:
        axis = np.array([x1 - x0, y1 - y0], dtype=float)
        length = float(np.linalg.norm(axis))
        if length < 1e-6:
            continue
        axis = axis / length
        normal = np.array([-axis[1], axis[0]])
        across = (grid_x - x0) * normal[0] + (grid_y - y0) * normal[1]
        along = (grid_x - x0) * axis[0] + (grid_y - y0) * axis[1]
        band = (np.abs(across) <= half) & (along >= -4) & (along <= length + 4)
        patch = bright & band
        if not patch.any():
            continue
        mask |= patch
        report.append("streak area=%d at %d,%d" % (int(patch.sum()), x0, y0))
    if not mask.any():
        return pixels, report
    # The streak lies along the edge of the screen, so half of it belongs
    # to the screen and half to the shell beside it.  Filling it with the
    # colour of the screen alone would leave a dark scratch where a
    # bright one was; it is given the colour of the nearest texel that
    # is *not* the streak, so each side of it is continued from its own
    # side and the hard edge that made it read as a crack goes away with
    # it.
    filled = nearest_class_colour(pixels, ~mask)
    repaired = pixels.copy()
    repaired[mask] = filled[mask]
    softened = cv2.GaussianBlur(repaired.astype(np.float32), (0, 0), 1.6)
    repaired[mask] = softened[mask].round().astype(np.uint8)
    return repaired, report


def repair_badge_arm(pixels):
    """Put the blue back into the lower left arm of the star badge.

    The scan washed the emblem out on that arm: what should be the
    blue of the star is a pale wash with fine streaks through it, so
    the arm reads as a torn flap rather than as a point of the star.
    The wash is told from the shell around it by its cast: it is still
    blue enough to belong to the emblem, while the shell beside it is
    a neutral grey.
    """
    x0, y0, x1, y1 = BADGE_ARM_BOX
    window = pixels[y0:y1, x0:x1]
    source = window.astype(np.float32)
    red = source[..., 0]
    green = source[..., 1]
    blue = source[..., 2]
    value = window.max(axis=2).astype(float)
    # The emblem's own blue.
    emblem = (blue > red + 55) & (blue > 140) & (red < 130) & (green < 190)
    if not emblem.any():
        return pixels, []
    # Everything in the box that is not the emblem and is still blue
    # enough to belong to it is the wash.  The shell beside the arm is a
    # cool grey rather than a blue, so it is left alone, and the deeper
    # parts of the arm are left alone too: they are the arm's own
    # shading and not the wash.
    inside = np.zeros(emblem.shape, dtype=bool)
    inside[:] = True
    mask = inside & ~emblem & (value >= 140) & ((blue - red) >= 12)
    if not mask.any():
        return pixels, []
    # The blue is taken from the emblem itself and spread smoothly, so
    # the arm keeps the shading the rest of the star has instead of the
    # stepped edges a nearest-texel fill leaves behind.
    field = cv2.GaussianBlur(
        nearest_class_colour(window, emblem).astype(np.float32), (0, 0), 5)
    # The fill is faded in over a couple of texels, so the edge between
    # the arm and the star is a blend rather than a step.  The fade is
    # also taken to nothing at the edge of the box, so the repair does
    # not leave a rectangle behind where the box ended.
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.6)
    edge = np.ones(mask.shape, dtype=np.float32)
    ramp = 14
    for axis, length in ((0, mask.shape[0]), (1, mask.shape[1])):
        profile = np.ones(length, dtype=np.float32)
        profile[:ramp] = np.linspace(0, 1, ramp)
        profile[-ramp:] = np.linspace(1, 0, ramp)
        edge = edge * (profile.reshape(-1, 1) if axis == 0 else profile.reshape(1, -1))
    alpha = (alpha * edge)[..., None]
    repaired = (source * (1 - alpha) + field * alpha).round().astype(np.uint8)
    out = pixels.copy()
    out[y0:y1, x0:x1] = repaired
    return out, ["badge-arm area=%d" % int(mask.sum())]


def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    document, binary = read_glb(source)
    image = next(item for item in document["images"]
                 if item.get("name", "").startswith("Color_"))
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    original = Image.open(io.BytesIO(binary[start:start + view["byteLength"]])).convert("RGB")
    pixels = np.asarray(original).copy()
    before = pixels.copy()

    pixels, violet_report = repair_violet(pixels)
    pixels, pink_report = repair_pink(pixels)
    pixels, wrong_report = repair_wrong_blue(pixels)
    pixels, bar_report = repair_bright_bar(pixels)
    pixels, rough_count = repair_rough_edges(pixels)
    pixels, streak_report = repair_visor_streak(pixels)
    pixels, arm_report = repair_badge_arm(pixels)
    pixels, noise_count = repair_flat_noise(pixels)
    pixels, splinter_report = repair_splinters(pixels)

    for entry in violet_report:
        print("YXZ_ATLAS violet %s" % entry)
    for entry in pink_report:
        print("YXZ_ATLAS %s" % entry)
    for entry in wrong_report:
        print("YXZ_ATLAS %s" % entry)
    for entry in bar_report:
        print("YXZ_ATLAS %s" % entry)
    print("YXZ_ATLAS rough_edges texels=%d" % rough_count)
    for entry in streak_report:
        print("YXZ_ATLAS %s" % entry)
    for entry in arm_report:
        print("YXZ_ATLAS %s" % entry)
    print("YXZ_ATLAS flat_noise texels=%d" % noise_count)
    print("YXZ_ATLAS splinters %s" % splinter_report)

    changed = np.any(before != pixels, axis=2)
    print("YXZ_ATLAS changed_texels=%d" % int(changed.sum()))

    out = Path("docs/yxz-audit/atlas-repair")
    out.mkdir(parents=True, exist_ok=True)
    boxes = {
        "star": (880, 3300, 1030, 3440),
        "bar": (3180, 1610, 3360, 1700),
        "eye": (3400, 1630, 3500, 1730),
        "screen": (1060, 3920, 1200, 4060),
        "streak": (1100, 3940, 1220, 4040),
        "arm": (870, 3370, 960, 3440),
    }
    for name, (x0, y0, x1, y1) in boxes.items():
        strip = np.concatenate([before[y0:y1, x0:x1], pixels[y0:y1, x0:x1]], axis=1)
        Image.fromarray(strip).resize(
            ((x1 - x0) * 4, (y1 - y0) * 4), Image.LANCZOS).save(out / ("%s.png" % name))

    encoded = io.BytesIO()
    Image.fromarray(pixels).save(encoded, format="PNG", optimize=False)
    packed = replace_image(document, binary, image["name"], encoded.getvalue())
    output.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output, document, packed)
    print("YXZ_ATLAS wrote=%s bytes=%d" % (output, len(encoded.getvalue())))


if __name__ == "__main__":
    main()
