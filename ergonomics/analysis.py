"""The pipeline: image bytes -> landmarks -> angles -> RULA/REBA -> insights.

Also holds the reverse path used by the ``/score`` endpoint, where the frontend
sends angles it already has (plus new task modifiers) and wants the scores
recomputed without re-uploading the photo.
"""

import base64
import threading

import cv2
import numpy as np

from . import insights as insights_mod
from . import reba, rula
from .angles import PostureAngles, SideAngles, compute_angles
from .landmarks import LM, build_frame, classify_view, quality_warnings
from .pose_backend import PoseBackendUnavailable, backend_info, get_backend
from .schema import Modifiers
from .tools import owas as owas_tool

# Detection is not thread safe, so one inference at a time.
_POSE_LOCK = threading.Lock()


class NoPoseDetected(Exception):
    """Raised when MediaPipe cannot find a body in the frame."""


def decode_image(data):
    """Decode raw bytes into a BGR image."""
    buf = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the uploaded file as an image.")
    return image


def analyse_image(image, modifiers=None, annotate=True, static=True, complexity=1):
    """Run the whole assessment on one BGR image."""
    modifiers = modifiers or Modifiers()
    height, width = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    backend = get_backend(static=static, complexity=complexity)
    with _POSE_LOCK:
        results = backend.detect(rgb)

    frame = build_frame(results, width, height)
    if frame is None:
        raise NoPoseDetected(
            "No body detected. Use a photo where the whole worker is visible, "
            "ideally from the side."
        )

    angles = compute_angles(frame)
    view = classify_view(frame)
    warnings = quality_warnings(frame, view)

    payload = score_angles(angles, modifiers)
    payload["hands"] = hand_offsets(frame)
    if payload["hands"]:
        payload["derived"]["biomech"]["hand_horizontal_m"] = payload["hands"]["horizontal_m"]
        payload["derived"]["niosh"]["h_origin_cm"] = round(payload["hands"]["horizontal_m"] * 100 + 10)
        payload["derived"]["niosh"]["v_origin_cm"] = round(max(0.0, payload["hands"]["height_m"]) * 100)
    payload["view"] = view
    payload["warnings"] = warnings
    payload["image"] = {"width": width, "height": height}
    if annotate:
        payload["annotated_image"] = encode_jpeg(
            draw_overlay(image.copy(), frame, angles, payload)
        )
    return payload


def score_angles(angles, modifiers):
    """Score an existing :class:`PostureAngles` with a set of modifiers."""
    rula_result = rula.score(angles, modifiers)
    reba_result = reba.score(angles, modifiers)
    findings = insights_mod.generate(angles, rula_result, reba_result, modifiers)
    summary = insights_mod.summarise(angles, rula_result, reba_result, findings)
    angle_dict = angles.to_dict()
    side = rula_result["governing_side"]
    arm = angle_dict.get(side) or {}
    owas_code = owas_tool.from_angles(angle_dict, angles.flags, modifiers.load_kg)
    return {
        "angles": angle_dict,
        "flags": angles.flags,
        "confidence": angles.confidence,
        "rula": rula_result,
        "reba": reba_result,
        "owas": owas_tool.run(owas_code),
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
        (sh_mid, "neck %.0f" % (angles.neck_flexion or 0)),
        (hip_mid, "trunk %.0f" % (angles.trunk_flexion or 0)),
        (pt(f"{side}_shoulder"), "arm %.0f" % (arm.upper_arm_flexion or 0)),
        (pt(f"{side}_elbow"), "elbow %.0f" % (arm.elbow_flexion or 0)),
        (pt(f"{side}_wrist"), "wrist %.0f" % (arm.wrist_flexion or 0)),
        (pt(f"{side}_knee"), "knee %.0f" % (getattr(angles, f"{side}_knee_flexion") or 0)),
    ]
    for (x, y), text in labels:
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
