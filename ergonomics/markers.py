"""Marker mode: coloured stickers on the joints correct the pose under loose clothing.

A pose model guesses where a joint is from the shape of the body, and a loose
kurta, apron or coat hides that shape. Bright tape on the shoulder, elbow,
wrist, hip, knee and ankle gives a direct fix: each sticker found near a
detected joint moves that joint onto the sticker.

    stickers = find_stickers(image, "green")
    corrected = snap_to_stickers(frame, stickers)   # moves the joints in place

Only the joints that have a sticker next to them move; with marker mode off
nothing here runs and the pose is exactly what the model returned.
"""

import cv2
import numpy as np

# OpenCV HSV ranges (H 0-179) for tape colours that rarely occur on skin or in a workshop.
COLOURS = {
    "green":  [((40, 100, 80), (85, 255, 255))],     # fluorescent / lime green
    "pink":   [((140, 90, 90), (172, 255, 255))],    # fluorescent pink / magenta
    "yellow": [((20, 120, 120), (34, 255, 255))],
    "orange": [((5, 150, 150), (19, 255, 255))],
    "blue":   [((95, 120, 70), (130, 255, 255))],
}

# Joints a sticker can correct (both sides).
MARKER_JOINTS = [f"{side}_{part}" for side in ("left", "right")
                 for part in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")]

MIN_AREA = 0.00001    # smallest sticker, as a share of the image area
MAX_AREA = 0.004      # largest - anything bigger is clothing or background, not tape
MAX_ASPECT = 2.5      # tape patches are compact; stripes and edges are long and thin
MIN_FILL = 0.55       # share of its bounding box a patch fills (disc 0.79, square 1.0)
REACH = 0.35          # a sticker only corrects a joint within this many torso lengths
VISIBLE = 0.5         # joints the model sees clearly take stickers before hidden ones
SEEN = 0.9            # visibility given to a joint a sticker has pinned down
TOO_MANY = len(MARKER_JOINTS)   # more patches than joints to tape: the colour is in the clothes or scene
HAND = ("index", "pinky", "thumb")   # move with the wrist, or the wrist angle would flip


def find_stickers(image, colour, box=None):
    """Centres (x, y in pixels) of sticker-sized, compact blobs of ``colour``.

    ``box`` (normalised [x0, y0, x1, y1], the worker's box) keeps only patches on
    or right around the worker, so a wall stripe or a coloured bin is ignored.
    """
    if colour not in COLOURS:
        raise ValueError("marker colour must be one of %s" % ", ".join(COLOURS))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for low, high in COLOURS[colour]:
        mask |= cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    height, width = image.shape[:2]
    lo, hi = max(12.0, MIN_AREA * width * height), MAX_AREA * width * height
    stickers = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        a = cv2.contourArea(c)
        _, _, w, h = cv2.boundingRect(c)
        if not (lo <= a <= hi) or max(w, h) > MAX_ASPECT * max(1, min(w, h)) or a < MIN_FILL * w * h:
            continue
        m = cv2.moments(c)
        x, y = m["m10"] / m["m00"], m["m01"] / m["m00"]
        if box is None or (box[0] * width <= x <= box[2] * width and box[1] * height <= y <= box[3] * height):
            stickers.append((x, y))
    return stickers


def snap_to_stickers(frame, stickers):
    """Move each joint that has a sticker close by onto that sticker.

    Clearly visible joints are paired first, closest first, and every sticker is
    used once - so in a side view the near-side elbow takes the elbow sticker and
    the hidden far-side elbow stays where the model put it. The 3D landmark moves by the same
    amount, converted with the torso's metres-per-pixel, because the angles are
    measured in 3D. Returns ``(corrections [{joint, moved_px, ...}], stickers left unused)``.
    """
    if not stickers:
        return [], 0
    torso_px = float(np.linalg.norm(
        (frame.pixels["left_shoulder"][:2] + frame.pixels["right_shoulder"][:2]) / 2
        - (frame.pixels["left_hip"][:2] + frame.pixels["right_hip"][:2]) / 2)) or 1.0
    reach = REACH * torso_px
    pairs = []
    for joint in MARKER_JOINTS:
        px = frame.pixels[joint][:2]
        for i, (sx, sy) in enumerate(stickers):
            d = float(np.hypot(sx - px[0], sy - px[1]))
            if d <= reach:
                pairs.append((frame.visibility.get(joint, 0.0) < VISIBLE, d, joint, i))

    # metres per pixel, from the same torso measured in both spaces
    scale = frame.torso_length / torso_px if frame.has_world else 0.0

    used_joints, used_stickers, corrections = set(), set(), []
    for _, d, joint, i in sorted(pairs):
        if joint in used_joints or i in used_stickers:
            continue
        used_joints.add(joint)
        used_stickers.add(i)
        sx, sy = stickers[i]
        old = frame.pixels[joint].copy()
        dx, dy = sx - old[0], sy - old[1]
        side, part = joint.split("_")
        for name in [joint] + ([f"{side}_{h}" for h in HAND] if part == "wrist" else []):
            if name not in frame.pixels:
                continue
            frame.pixels[name][0] += dx
            frame.pixels[name][1] += dy
            if frame.has_world:
                frame.world[name][0] += dx * scale
                frame.world[name][1] += dy * scale
        frame.visibility[joint] = max(frame.visibility.get(joint, 0.0), SEEN)
        corrections.append({"joint": joint, "moved_px": round(d, 1),
                            "from": [round(float(old[0]), 1), round(float(old[1]), 1)],
                            "to": [round(sx, 1), round(sy, 1)]})
    corrections.sort(key=lambda c: MARKER_JOINTS.index(c["joint"]))
    return corrections, len(stickers) - len(used_stickers)


def apply_markers(image, frame, colour):
    """Find the stickers and correct the frame; returns the report for the API."""
    stickers = find_stickers(image, colour, frame.box)
    corrections, unused = snap_to_stickers(frame, stickers)
    return {"colour": colour, "stickers_found": len(stickers), "corrected": corrections,
            "stickers_unused": unused, "colour_in_scene": len(stickers) > TOO_MANY}


def draw_markers(image, report):
    """Ring every corrected joint and draw where the model had put it."""
    for c in report["corrected"]:
        old = tuple(int(round(v)) for v in c["from"])
        new = tuple(int(round(v)) for v in c["to"])
        cv2.line(image, old, new, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(image, old, 3, (160, 160, 160), -1, cv2.LINE_AA)
        cv2.circle(image, new, 9, (255, 255, 255), 2, cv2.LINE_AA)
    return image
