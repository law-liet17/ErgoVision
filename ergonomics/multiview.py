"""Combine 1-3 photos of the same worker doing the same task into one assessment.

RULA and REBA are defined on sagittal angles, which a side-on photo measures
well and a front-on photo badly; abduction, side bend and twist are the other
way round. So every angle is taken from the photo whose camera view suits it
and, among photos with that view, the one where the joint is most clearly
visible. A joint that is not clearly visible in any photo is left unmeasured
and reported back - it is never filled in with a guess.

    result = analyse_views([side_img, front_img], Modifiers(load_kg=12))
    result["sources"]["trunk_flexion"]   # {"photo": 1, "view": "side", ...}
    result["missing_joints"]             # alerts for joints nobody could see
"""

import copy

from .analysis import (MultiplePeople, NoPoseDetected, attach_hands, detect_frame,
                       draw_overlay, encode_jpeg, score_angles)
from .angles import PostureAngles, SideAngles, compute_angles, detect_flags
from .landmarks import classify_view
from .schema import Modifiers, is_missing

MAX_PHOTOS = 3
VISIBLE = 0.5        # landmark visibility needed to trust a joint (as CORE in landmarks.py)
VISIBLE_HAND = 0.4   # finger points are small; same bar as the hand warning in landmarks.py

# Which camera views to prefer, best first, for each kind of angle.
VIEW_ORDER = {
    "side": ("side", "oblique", "front"),    # flexion / extension
    "front": ("front", "oblique", "side"),   # abduction, side bend, twist
}


class Measure:
    """One angle (plus the angles computed alongside it) and what it needs to be seen.

    ``groups`` lists landmark groups; a group counts as visible when ANY of its
    landmarks is (the trunk needs a shoulder and a hip, not all four), and the
    measure needs every group. ``joint`` and ``row`` name it in the alert; a
    measure without them only adjusts a score, so it is not alerted.
    """

    def __init__(self, key, fields, view, groups, joint=None, row=None):
        self.key, self.fields, self.view, self.groups = key, fields, view, groups
        self.joint, self.row = joint, row


def _pair(name):
    return ("left_" + name, "right_" + name)


def _each(side, *names):
    return [(f"{side}_{n}",) for n in names]


MEASURES = [
    Measure("trunk_flexion", ["trunk_flexion"], "side",
            [_pair("shoulder"), _pair("hip")], "Trunk", "trunk"),
    Measure("neck_flexion", ["neck_flexion", "neck_flexion_gravity", "shoulder_ear_ratio"], "side",
            [_pair("ear"), _pair("shoulder")], "Neck", "neck"),
    Measure("trunk_side_bend", ["trunk_side_bend"], "front", [_pair("shoulder"), _pair("hip")]),
    Measure("trunk_twist", ["trunk_twist"], "front",
            _each("left", "shoulder", "hip") + _each("right", "shoulder", "hip")),
    Measure("neck_side_bend", ["neck_side_bend"], "front", [_pair("ear"), _pair("shoulder")]),
    Measure("neck_twist", ["neck_twist"], "front",
            _each("left", "ear", "shoulder") + _each("right", "ear", "shoulder")),
]
for _s in ("left", "right"):
    _S = _s.capitalize()
    MEASURES += [
        Measure(f"{_s}.upper_arm_flexion", [f"{_s}.upper_arm_flexion", f"{_s}.upper_arm_elevation"],
                "side", _each(_s, "shoulder", "elbow"), f"{_S} upper arm", "upper-arm"),
        Measure(f"{_s}.elbow_flexion", [f"{_s}.elbow_flexion"], "side",
                _each(_s, "shoulder", "elbow", "wrist"), f"{_S} elbow", "lower-arm"),
        Measure(f"{_s}.wrist_flexion", [f"{_s}.wrist_flexion"], "side",
                _each(_s, "elbow", "wrist", "index", "pinky"), f"{_S} wrist", "wrist"),
        Measure(f"{_s}.upper_arm_abduction", [f"{_s}.upper_arm_abduction"], "front",
                _each(_s, "shoulder", "elbow")),
        Measure(f"{_s}.wrist_deviation", [f"{_s}.wrist_deviation"], "front",
                _each(_s, "wrist", "index", "pinky")),
        Measure(f"{_s}_knee_flexion", [f"{_s}_knee_flexion", f"{_s}_hip_flexion"], "side",
                _each(_s, "hip", "knee", "ankle"), f"{_S} knee", "legs"),
    ]


def _get(angles, path):
    if "." in path:
        side, name = path.split(".")
        return getattr(angles.side(side), name)
    return getattr(angles, path)


def _set(angles, path, value):
    if "." in path:
        side, name = path.split(".")
        setattr(angles.side(side), name, value)
    else:
        setattr(angles, path, value)


def joint_visibility(frame, groups):
    """(clearly visible?, lowest group visibility) for one measure in one photo."""
    ok, worst = True, 1.0
    for group in groups:
        vis = max(frame.visibility.get(n, 0.0) for n in group)
        need = VISIBLE_HAND if group[0].endswith(("_index", "_pinky")) else VISIBLE
        ok = ok and vis >= need
        worst = min(worst, vis)
    return ok, worst


def merge(photos):
    """Pick every angle from the best photo.

    ``photos`` is a list of dicts with ``index`` (1-based), ``frame``,
    ``angles`` and ``view``. Returns ``(angles, sources, missing)``.
    """
    merged = PostureAngles(left=SideAngles(side="left"), right=SideAngles(side="right"))
    sources, missing = {}, []
    for m in MEASURES:
        order = VIEW_ORDER[m.view]
        candidates = []
        for p in photos:
            ok, vis = joint_visibility(p["frame"], m.groups)
            if ok and not any(is_missing(_get(p["angles"], f)) for f in m.fields):
                candidates.append((order.index(p["view"]["view"]), -vis, p["index"], p, vis))
        if not candidates:
            if m.joint:
                best = max(joint_visibility(p["frame"], m.groups)[1] for p in photos)
                missing.append({
                    "key": m.key, "joint": m.joint, "row": m.row,
                    "best_visibility": round(best, 2),
                    "message": "%s is not visible. Upload another photo showing this joint, "
                               "or the %s score cannot be calculated." % (m.joint, m.row),
                })
            continue
        _, _, index, photo, vis = min(candidates, key=lambda c: c[:3])
        for f in m.fields:
            _set(merged, f, _get(photo["angles"], f))
        sources[m.key] = {"photo": index, "view": photo["view"]["view"],
                          "visibility": round(vis, 3), "preferred_view": photo["view"]["view"] == m.view}

    def seen(key):
        return sources.get(key, {}).get("visibility", 0.0)

    merged.left.confidence = seen("left.upper_arm_flexion")
    merged.right.confidence = seen("right.upper_arm_flexion")
    merged.confidence = {
        "trunk": seen("trunk_flexion"), "neck": seen("neck_flexion"),
        "left_arm": seen("left.elbow_flexion"), "right_arm": seen("right.elbow_flexion"),
        "left_hand": seen("left.wrist_flexion"), "right_hand": seen("right.wrist_flexion"),
        "legs": min(seen("left_knee_flexion"), seen("right_knee_flexion")),
    }
    merged.flags = detect_flags(merged, None)
    return merged, sources, missing


def _only_from(angles, sources, index):
    """Copy of the merged angles keeping only those taken from photo ``index``."""
    out = copy.deepcopy(angles)
    for m in MEASURES:
        if sources.get(m.key, {}).get("photo") != index:
            for f in m.fields:
                _set(out, f, float("nan"))
    return out


def analyse_views(images, modifiers=None, annotate=True, complexity=1):
    """Assess one worker from 1-3 BGR photos of the same task."""
    if not 1 <= len(images) <= MAX_PHOTOS:
        raise ValueError("Send between 1 and %d photos of the same worker and task." % MAX_PHOTOS)
    modifiers = modifiers or Modifiers()

    photos, warnings = [], []
    for index, image in enumerate(images, 1):
        try:
            frame = detect_frame(image, static=True, complexity=complexity)
        except NoPoseDetected:
            warnings.append("Photo %d: no body detected, so it was left out." % index)
            continue
        except MultiplePeople as many:
            # Photos of one task are framed on the worker, so take the largest body.
            frame = max(many.frames, key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]))
            warnings.append("Photo %d: %d people found - the largest one was assessed. Crop the "
                            "photo to the worker if that is not them." % (index, len(many.frames)))
        photos.append({"index": index, "image": image, "frame": frame,
                       "angles": compute_angles(frame), "view": classify_view(frame)})
    if not photos:
        raise NoPoseDetected("No body detected in any of the photos. Use photos where the "
                             "whole worker is visible, at least one of them from the side.")

    merged, sources, missing = merge(photos)
    payload = score_angles(merged, modifiers)

    # The photo the trunk came from anchors the hand position and the summary view.
    main_index = sources.get("trunk_flexion", {}).get("photo", photos[0]["index"])
    main = next(p for p in photos if p["index"] == main_index)
    attach_hands(payload, main["frame"])
    payload["view"] = main["view"]
    payload["image"] = {"width": main["frame"].width, "height": main["frame"].height}

    if not any(p["view"]["view"] == "side" for p in photos):
        warnings.append("None of the photos is side-on. Trunk, neck, arm and knee bends were "
                        "taken from a front or angled photo and may be underestimated - add a "
                        "photo taken from the worker's side.")
    if not any(p["frame"].has_world for p in photos):
        warnings.append("3D landmarks unavailable - twist, side-bend and abduction detection are disabled.")
    payload["warnings"] = warnings
    payload["sources"] = sources
    payload["missing_joints"] = missing

    payload["photos"] = []
    for p in photos:
        used = [key for key, src in sources.items() if src["photo"] == p["index"]]
        entry = {"index": p["index"], "view": p["view"], "used_for": used,
                 "width": p["frame"].width, "height": p["frame"].height}
        if annotate:
            own = _only_from(merged, sources, p["index"])
            entry["annotated_image"] = encode_jpeg(draw_overlay(p["image"].copy(), p["frame"], own, payload))
        payload["photos"].append(entry)
    if annotate:
        payload["annotated_image"] = next(e["annotated_image"] for e in payload["photos"]
                                          if e["index"] == main_index)
    return payload
