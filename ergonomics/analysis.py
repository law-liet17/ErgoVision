"""The pipeline: image bytes -> landmarks -> angles -> RULA/REBA -> insights.

Also holds the reverse path used by the ``/score`` endpoint, where the frontend
sends angles it already has (plus new task modifiers) and wants the scores
recomputed without re-uploading the photo.
"""

import base64
import copy
import threading

import cv2
import numpy as np

from . import insights as insights_mod
from . import methods, reba, rula
from .angles import PostureAngles, SideAngles, compute_angles
from .landmarks import LM, build_frame, classify_view, quality_warnings
from .pose_backend import PoseBackendUnavailable, backend_info, get_backend
from .schema import Modifiers, is_missing
from .tools import owas as owas_tool

# Detection is not thread safe, so one inference at a time.
_POSE_LOCK = threading.Lock()


class NoPoseDetected(Exception):
    """Raised when MediaPipe cannot find a body in the frame."""


class MultiplePeople(Exception):
    """More than one person is in the frame and nobody has said which is the worker."""

    def __init__(self, frames, image):
        super().__init__("%d people found. Choose the worker to assess." % len(frames))
        self.frames = frames
        self.people = [{"number": i, "box": f.box} for i, f in enumerate(frames, 1)]
        self.image = {"width": image.shape[1], "height": image.shape[0]}
        scale = min(1.0, 960.0 / image.shape[1])
        small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
        self.preview = encode_jpeg(small, quality=78)


# Person selection -----------------------------------------------------------
DUPLICATE_IOU = 0.6   # two detections overlapping this much are the same body
MAX_JUMP = 0.3        # a tracked worker never jumps further (frame widths) between samples


def person_box(frame):
    """Normalised [x0, y0, x1, y1] around a detected body, slightly padded."""
    pts = np.array([frame.pixels[name][:2] for name in LM])
    (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
    pad_x, pad_y = 0.08 * (x1 - x0), 0.06 * (y1 - y0)
    box = [(x0 - pad_x) / frame.width, (y0 - pad_y) / frame.height,
           (x1 + pad_x) / frame.width, (y1 + pad_y) / frame.height]
    return [round(float(min(1.0, max(0.0, v))), 4) for v in box]


def box_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _centre_gap(a, b):
    return float(np.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2))


def pick_person(frames, box):
    """The detected body that is the person in ``box``: most overlap, else the nearest.

    Returns ``None`` when nobody is near - the chosen worker has left the frame,
    and scoring whoever is left would score the wrong person.
    """
    best = max(frames, key=lambda f: (box_iou(f.box, box), -_centre_gap(f.box, box)))
    if box_iou(best.box, box) == 0 and _centre_gap(best.box, box) > MAX_JUMP:
        return None
    return best


def detect_people(image, static=True, complexity=1):
    """Every body in one BGR image, numbered left to right."""
    height, width = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    backend = get_backend(static=static, complexity=complexity)
    with _POSE_LOCK:
        results = backend.detect_all(rgb)

    frames = []
    for result in results:   # most confident first, so a duplicate keeps the better one
        frame = build_frame(result, width, height)
        if frame is None:
            continue
        frame.box = person_box(frame)
        if all(box_iou(frame.box, kept.box) < DUPLICATE_IOU for kept in frames):
            frames.append(frame)
    frames.sort(key=lambda f: f.box[0] + f.box[2])
    for frame in frames:
        frame.people = len(frames)
    return frames


def decode_image(data):
    """Decode raw bytes into a BGR image."""
    buf = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the uploaded file as an image.")
    return image


def detect_frame(image, static=True, complexity=1, person=None):
    """Find the worker's body in one BGR image.

    ``person`` is a normalised box chosen earlier (a click on the photo, or the
    worker's box in the previous video frame). Without one, a single body is
    returned as before and several raise :class:`MultiplePeople`.
    """
    frames = detect_people(image, static=static, complexity=complexity)
    if not frames:
        raise NoPoseDetected(
            "No body detected. Use a photo where the whole worker is visible, "
            "ideally from the side."
        )
    if person is not None:
        frame = pick_person(frames, person)
        if frame is None:
            raise NoPoseDetected("The chosen worker is not in this frame.")
        return frame
    if len(frames) > 1:
        raise MultiplePeople(frames, image)
    return frames[0]


def analyse_image(image, modifiers=None, annotate=True, static=True, complexity=1, person=None):
    """Run the whole assessment on one BGR image (on ``person`` if several are in it)."""
    modifiers = modifiers or Modifiers()
    height, width = image.shape[:2]
    frame = detect_frame(image, static=static, complexity=complexity, person=person)

    angles = compute_angles(frame)
    view = classify_view(frame)
    warnings = quality_warnings(frame, view)

    payload = score_angles(angles, modifiers)
    attach_hands(payload, frame)
    payload["view"] = view
    payload["warnings"] = warnings
    payload["image"] = {"width": width, "height": height}
    payload["person"] = {"box": frame.box, "people_found": frame.people}
    if annotate:
        payload["annotated_image"] = encode_jpeg(
            draw_overlay(image.copy(), frame, angles, payload)
        )
    return payload


def score_angles(angles, modifiers):
    """Score an existing :class:`PostureAngles` with a set of modifiers."""
    rula_result = rula.score(angles, modifiers)
    reba_result = reba.score(angles, modifiers)
    side = rula_result["governing_side"]
    findings = insights_mod.generate(_unmeasured_as_none(angles), rula_result, reba_result, modifiers)
    # No fix advice for a joint nobody could see: it would quote a made-up angle.
    findings = [f for f in findings if not _segment_hidden(f["segment"], angles, side)]
    summary = insights_mod.summarise(angles, rula_result, reba_result, findings)
    angle_dict = angles.to_dict()
    arm = angle_dict.get(side) or {}
    owas_code = owas_tool.from_angles(angle_dict, angles.flags, modifiers.load_kg)
    owas_result = owas_tool.run(owas_code)
    return {
        "angles": angle_dict,
        "flags": angles.flags,
        "confidence": angles.confidence,
        "rula": rula_result,
        "reba": reba_result,
        "owas": owas_result,
        # Each method with its own score and action level, most urgent first. OWAS
        # follows: its leg code is unreliable with the feet out of shot, so it never leads.
        "methods": methods.rank([methods.describe("rula", rula_result),
                                 methods.describe("reba", reba_result)]) + [methods.describe("owas", owas_result)],
        "insights": findings,
        "summary": summary,
        # ready-to-send inputs for the other tools, so a photo can seed them
        "derived": {
            "owas": owas_code,
            "biomech": {
                "load_kg": modifiers.load_kg,
                "trunk_flexion_deg": angle_dict.get("trunk_flexion") or 0,
                "upper_arm_flexion_deg": arm.get("upper_arm_flexion") or 0,
                "elbow_flexion_deg": arm.get("elbow_flexion") or 0,
            },
            "niosh": {"load_kg": modifiers.load_kg,
                      "a_origin_deg": abs(angle_dict.get("trunk_twist") or 0)},
        },
    }


def _unmeasured_as_none(angles):
    """Copy of ``angles`` with NaN replaced by None, which the insight text expects."""
    clean = copy.deepcopy(angles)
    for obj in (clean, clean.left, clean.right):
        for name, value in vars(obj).items():
            if is_missing(value):
                setattr(obj, name, None)
    return clean


def _segment_hidden(segment, angles, side):
    """Was the angle behind an insight's body segment not measured at all?"""
    arm = angles.side(side)
    measured = {
        "trunk": [angles.trunk_flexion], "neck": [angles.neck_flexion],
        "shoulder": [arm.upper_arm_flexion], "elbow": [arm.elbow_flexion],
        "wrist": [arm.wrist_flexion],
        "legs": [angles.left_knee_flexion, angles.right_knee_flexion],
    }.get(segment)
    return bool(measured) and all(is_missing(v) for v in measured)


def attach_hands(payload, frame):
    """Add the hand position, and seed the lifting tools' inputs from it."""
    payload["hands"] = hand_offsets(frame)
    if payload["hands"]:
        payload["derived"]["biomech"]["hand_horizontal_m"] = payload["hands"]["horizontal_m"]
        payload["derived"]["niosh"]["h_origin_cm"] = round(payload["hands"]["horizontal_m"] * 100 + 10)
        payload["derived"]["niosh"]["v_origin_cm"] = round(max(0.0, payload["hands"]["height_m"]) * 100)


def hand_offsets(frame):
    """Where the hands are relative to the hips, in metres (needs 3D landmarks).

    horizontal_m: forward distance from the hip centre to the wrists (approximates
    the NIOSH H and the biomechanical load moment arm); height_m: wrist height
    above the hip centre (negative = below the hips).
    """
    if not frame.has_world:
        return None
    wrists = (frame.p("left_wrist") + frame.p("right_wrist")) / 2.0
    rel = wrists - frame.hip_mid
    forward = float(np.dot(rel, frame.forward_global))
    up = float(-rel[1])
    return {"horizontal_m": round(max(0.0, forward), 3), "height_m": round(up, 3)}


# ---------------------------------------------------------------------------
# Rehydrating angles sent back by the client
# ---------------------------------------------------------------------------

_SIDE_FIELDS = (
    "upper_arm_flexion", "upper_arm_abduction", "upper_arm_elevation",
    "elbow_flexion", "wrist_flexion", "wrist_deviation",
)
_BODY_FIELDS = (
    "trunk_flexion", "trunk_side_bend", "trunk_twist", "neck_flexion",
    "neck_flexion_gravity", "neck_side_bend", "neck_twist",
    "left_knee_flexion", "right_knee_flexion", "left_hip_flexion",
    "right_hip_flexion", "shoulder_ear_ratio",
)


def angles_from_dict(data):
    """Rebuild a :class:`PostureAngles` from a JSON payload (``/score``)."""
    data = data or {}
    angles = PostureAngles()
    for field in _BODY_FIELDS:
        value = data.get(field)
        setattr(angles, field, float("nan") if value is None else float(value))
    for side in ("left", "right"):
        raw = data.get(side) or {}
        arm = SideAngles(side=side)
        for field in _SIDE_FIELDS:
            value = raw.get(field)
            setattr(arm, field, float("nan") if value is None else float(value))
        arm.confidence = float(raw.get("confidence") or 0.0)
        setattr(angles, side, arm)
    angles.confidence = data.get("confidence") or {}
    angles.flags = data.get("flags") or {}
    return angles


# ---------------------------------------------------------------------------
# Overlay drawing
# ---------------------------------------------------------------------------

RISK_COLOURS = {          # BGR
    "negligible": (120, 200, 120),
    "low": (120, 200, 120),
    "medium": (60, 200, 250),
    "high": (60, 120, 250),
    "very high": (60, 60, 240),
}

SKELETON = [
    ("left_shoulder", "right_shoulder"), ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"), ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"), ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"), ("left_hip", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
    ("left_ear", "left_shoulder"), ("right_ear", "right_shoulder"),
]


def draw_overlay(image, frame, angles, payload):
    """Draw the skeleton plus the angles that drove the score."""
    colour = RISK_COLOURS.get(payload["reba"]["risk"], (200, 200, 200))
    side = payload["rula"]["governing_side"]
    arm = angles.side(side)

    def pt(name):
        p = frame.pixels[name]
        return int(round(p[0])), int(round(p[1]))

    for a, b in SKELETON:
        cv2.line(image, pt(a), pt(b), (230, 230, 230), 2, cv2.LINE_AA)
    for name in LM:
        if frame.visibility.get(name, 0) >= 0.5:
            cv2.circle(image, pt(name), 4, colour, -1, cv2.LINE_AA)

    # trunk and neck reference lines
    hip_mid = tuple(int(round(v)) for v in (
        (frame.pixels["left_hip"] + frame.pixels["right_hip"]) / 2)[:2])
    sh_mid = tuple(int(round(v)) for v in (
        (frame.pixels["left_shoulder"] + frame.pixels["right_shoulder"]) / 2)[:2])
    ear_mid = tuple(int(round(v)) for v in (
        (frame.pixels["left_ear"] + frame.pixels["right_ear"]) / 2)[:2])
    cv2.line(image, hip_mid, sh_mid, colour, 3, cv2.LINE_AA)
    cv2.line(image, sh_mid, ear_mid, colour, 3, cv2.LINE_AA)
    cv2.line(image, hip_mid, (hip_mid[0], max(0, hip_mid[1] - 120)), (180, 180, 180), 1, cv2.LINE_AA)

    labels = [
        (sh_mid, "neck", angles.neck_flexion),
        (hip_mid, "trunk", angles.trunk_flexion),
        (pt(f"{side}_shoulder"), "arm", arm.upper_arm_flexion),
        (pt(f"{side}_elbow"), "elbow", arm.elbow_flexion),
        (pt(f"{side}_wrist"), "wrist", arm.wrist_flexion),
        (pt(f"{side}_knee"), "knee", getattr(angles, f"{side}_knee_flexion")),
    ]
    for (x, y), name, value in labels:
        if is_missing(value):  # not measured in this photo
            continue
        text = "%s %.0f" % (name, value)
        cv2.putText(image, text, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, text, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    colour, 1, cv2.LINE_AA)

    banner = "RULA %d (level %d)   REBA %d (%s)" % (
        payload["rula"]["grand_score"], payload["rula"]["action_level"],
        payload["reba"]["reba_score"], payload["reba"]["risk"],
    )
    cv2.rectangle(image, (0, 0), (image.shape[1], 40), (20, 20, 25), -1)
    cv2.putText(image, banner, (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2, cv2.LINE_AA)
    return image


def encode_jpeg(image, quality=82):
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
