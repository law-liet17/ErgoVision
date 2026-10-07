"""Turn pose landmarks into the angles that the RULA and REBA charts ask for.

This is the module that bridges "what a pose model gives you" and "what the
worksheets are defined on", which are not the same thing:

=========================  ==========================================================
Worksheet asks for         How it is measured here
=========================  ==========================================================
Trunk flexion/extension    Trunk axis (hip mid -> shoulder mid) vs **gravity**,
                           projected on the sagittal plane. + = forward flexion.
Trunk side bending         Same vector, projected on the frontal plane (3D only).
Trunk twist                Rotation of the shoulder line against the hip line about
                           the trunk axis (3D only).
Neck flexion/extension     Head axis (shoulder mid -> ear mid) vs the **trunk axis**,
                           not vs gravity: the worksheets draw the neck angle from
                           the trunk line. + = head forward/down.
Upper arm flexion          Upper arm (shoulder -> elbow) vs the **trunk axis pointing
                           down**, sagittal projection. + = arm forward, - = behind.
Upper arm abduction        Same vector, frontal projection, away from the body.
Lower arm (elbow) flexion  180 - interior angle(shoulder, elbow, wrist).  A straight
                           arm is 0 deg of flexion, a right angle is 90 deg.
Wrist flexion/extension    180 - interior angle(elbow, wrist, hand), signed towards
                           the palm side (the side the elbow bends towards).
Wrist deviation            Component of the same hand vector along the radial/ulnar
                           axis (index -> pinky).
Knee flexion               180 - interior angle(hip, knee, ankle).
Hip flexion                180 - interior angle(shoulder, hip, knee) - used to guess
                           sitting vs standing.
=========================  ==========================================================

Every angle is reported in degrees, and a confidence (the lowest landmark
visibility that fed it) travels with it so the UI can grey out guesses.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from .geometry import (angle_between, joint_angle, out_of_plane_angle, project_out,
                       rotation_about, signed_angle, unit)

# --- detection thresholds (tunable, documented in docs/SCORING.md) ---------
TWIST_DEG = 20.0          # shoulder-vs-hip / ear-vs-shoulder rotation to call a twist
SIDE_BEND_DEG = 10.0      # frontal-plane lean to call a side bend
ABDUCTION_DEG = 25.0      # upper-arm abduction that earns the RULA/REBA +1
WRIST_DEVIATION_DEG = 10.0  # radial/ulnar deviation that earns the +1
LEG_ASYMMETRY_DEG = 25.0  # knee flexion difference suggesting one-legged loading
SHOULDER_RAISED_RATIO = 0.35  # ear-to-shoulder gap / torso length below this = hunched
SITTING_HIP_DEG = 55.0
SITTING_KNEE_DEG = 55.0


@dataclass
class SideAngles:
    """Arm angles for one side of the body."""

    side: str
    upper_arm_flexion: float = float("nan")     # signed, sagittal, vs trunk
    upper_arm_abduction: float = float("nan")   # signed, frontal, + = away from body
    upper_arm_elevation: float = float("nan")   # total angle from trunk-down (0..180)
    elbow_flexion: float = float("nan")         # 0 = straight
    wrist_flexion: float = float("nan")         # signed, + = palmar flexion
    wrist_deviation: float = float("nan")       # signed radial/ulnar deviation
    confidence: float = 0.0

    def to_dict(self):
        return {k: (None if isinstance(v, float) and np.isnan(v) else v)
                for k, v in asdict(self).items()}


@dataclass
class PostureAngles:
    """Every angle the two worksheets need, plus the auto-detected flags."""

    trunk_flexion: float = float("nan")
    trunk_side_bend: float = float("nan")
    trunk_twist: float = float("nan")
    neck_flexion: float = float("nan")          # vs trunk (worksheet definition)
    neck_flexion_gravity: float = float("nan")  # vs vertical (informational)
    neck_side_bend: float = float("nan")
    neck_twist: float = float("nan")
    left_knee_flexion: float = float("nan")
    right_knee_flexion: float = float("nan")
    left_hip_flexion: float = float("nan")
    right_hip_flexion: float = float("nan")
    shoulder_ear_ratio: float = float("nan")
    left: SideAngles = None
    right: SideAngles = None
    confidence: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)

    def side(self, which):
        return self.left if which == "left" else self.right

    def to_dict(self):
        out = {}
        for key, value in asdict(self).items():
            if key in ("left", "right"):
                continue
            if isinstance(value, float) and np.isnan(value):
                out[key] = None
            else:
                out[key] = value
        out["left"] = self.left.to_dict() if self.left else None
        out["right"] = self.right.to_dict() if self.right else None
        return out


def _round(value, digits=1):
    return float("nan") if value is None or np.isnan(value) else round(float(value), digits)


def _arm_angles(frame, side):
    """Upper arm, elbow and wrist angles for one arm."""
    sh = frame.p(f"{side}_shoulder")
    el = frame.p(f"{side}_elbow")
    wr = frame.p(f"{side}_wrist")
    idx = frame.p(f"{side}_index")
    pky = frame.p(f"{side}_pinky")

    trunk_down = -frame.trunk_up
    upper_arm = el - sh

    out = SideAngles(side=side)

    # Upper arm: sagittal flexion, frontal abduction, and total elevation.
    out.upper_arm_flexion = signed_angle(upper_arm, trunk_down, frame.forward)
    out.upper_arm_abduction = out_of_plane_angle(upper_arm, frame.side_axis(side))
    out.upper_arm_elevation = angle_between(upper_arm, trunk_down)

    # Lower arm: flexion, where 0 deg means a fully extended arm.
    out.elbow_flexion = 180.0 - joint_angle(sh, el, wr)

    # Wrist: split the hand vector into flexion/extension and deviation.
    forearm = wr - el
    hand = ((idx + pky) / 2.0) - wr
    flex_axis = project_out(sh - el, forearm)          # points to the palmar side
    out.wrist_flexion = signed_angle(hand, forearm, flex_axis)
    if frame.has_world:
        dev_axis = project_out(pky - idx, forearm)
        out.wrist_deviation = out_of_plane_angle(hand, dev_axis)
    else:
        # In 2D the deviation axis is degenerate; report the unsigned residual.
        out.wrist_deviation = float("nan")

    out.confidence = frame.vis(f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist")
    return out


def compute_angles(frame):
    """Compute a :class:`PostureAngles` from a :class:`~.landmarks.Frame`."""
    up = frame.up_global
    fwd_g = frame.forward_global
    lat_g = frame.lateral_global

    angles = PostureAngles()

    # --- trunk: measured against gravity --------------------------------
    trunk_vec = frame.shoulder_mid - frame.hip_mid
    angles.trunk_flexion = signed_angle(trunk_vec, up, fwd_g)
    angles.trunk_side_bend = (
        out_of_plane_angle(trunk_vec, lat_g) if frame.has_world else float("nan")
    )

    # --- neck: measured against the trunk axis ---------------------------
    neck_vec = frame.ear_mid - frame.shoulder_mid
    angles.neck_flexion = signed_angle(neck_vec, frame.trunk_up, frame.forward)
    angles.neck_flexion_gravity = signed_angle(neck_vec, up, fwd_g)
    angles.neck_side_bend = (
        out_of_plane_angle(neck_vec, frame.lateral) if frame.has_world else float("nan")
    )

    # --- twists (need real 3D) -------------------------------------------
    if frame.has_world:
        hip_line = frame.p("right_hip") - frame.p("left_hip")
        sh_line = frame.p("right_shoulder") - frame.p("left_shoulder")
        ear_line = frame.p("right_ear") - frame.p("left_ear")
        angles.trunk_twist = rotation_about(frame.trunk_up, hip_line, sh_line)
        angles.neck_twist = rotation_about(frame.trunk_up, sh_line, ear_line)

    # --- arms -------------------------------------------------------------
    angles.left = _arm_angles(frame, "left")
    angles.right = _arm_angles(frame, "right")

    # --- legs -------------------------------------------------------------
    for side in ("left", "right"):
        hip = frame.p(f"{side}_hip")
        knee = frame.p(f"{side}_knee")
        ankle = frame.p(f"{side}_ankle")
        shoulder = frame.p(f"{side}_shoulder")
        setattr(angles, f"{side}_knee_flexion", 180.0 - joint_angle(hip, knee, ankle))
        setattr(angles, f"{side}_hip_flexion", 180.0 - joint_angle(shoulder, hip, knee))

    # --- shoulder elevation hint ------------------------------------------
    # Measured along the trunk axis (not the image vertical) so that bending
    # over does not fake a raised shoulder.  Still only a hint: without a
    # relaxed baseline for this worker it never auto-applies to the score.
    torso = frame.torso_length or 1.0
    angles.shoulder_ear_ratio = float(np.dot(neck_vec, frame.trunk_up)) / torso

    # --- confidence -------------------------------------------------------
    angles.confidence = {
        "trunk": round(frame.vis("left_shoulder", "right_shoulder", "left_hip", "right_hip"), 3),
        "neck": round(frame.vis("left_ear", "right_ear", "left_shoulder", "right_shoulder"), 3),
        "left_arm": round(angles.left.confidence, 3),
        "right_arm": round(angles.right.confidence, 3),
        "left_hand": round(frame.vis("left_wrist", "left_index", "left_pinky"), 3),
        "right_hand": round(frame.vis("right_wrist", "right_index", "right_pinky"), 3),
        "legs": round(frame.vis("left_knee", "right_knee", "left_ankle", "right_ankle"), 3),
    }

    angles.flags = detect_flags(angles, frame)

    # Round everything for transport once the flags are decided.
    for name in (
        "trunk_flexion", "trunk_side_bend", "trunk_twist", "neck_flexion",
        "neck_flexion_gravity", "neck_side_bend", "neck_twist",
        "left_knee_flexion", "right_knee_flexion", "left_hip_flexion",
        "right_hip_flexion",
    ):
        setattr(angles, name, _round(getattr(angles, name)))
    angles.shoulder_ear_ratio = _round(angles.shoulder_ear_ratio, 3)
    for arm in (angles.left, angles.right):
        for name in (
            "upper_arm_flexion", "upper_arm_abduction", "upper_arm_elevation",
            "elbow_flexion", "wrist_flexion", "wrist_deviation",
        ):
            setattr(arm, name, _round(getattr(arm, name)))
        arm.confidence = round(arm.confidence, 3)

    return angles


def detect_flags(angles, frame):
    """Booleans the worksheets need that we *can* read off the pose.

    Anything genuinely invisible in a photo (load, coupling, static hold,
    repetition, wrist twist) stays a user input - see :mod:`.schema`.
    """
    def big(value, threshold):
        return bool(not np.isnan(value) and abs(value) > threshold)

    knees = [angles.left_knee_flexion, angles.right_knee_flexion]
    knee_gap = abs(knees[0] - knees[1]) if not any(np.isnan(k) for k in knees) else 0.0
    hips = [angles.left_hip_flexion, angles.right_hip_flexion]
    max_hip = max(h for h in hips if not np.isnan(h)) if hips else float("nan")
    max_knee = max(k for k in knees if not np.isnan(k)) if knees else float("nan")

    flags = {
        "trunk_twisted": big(angles.trunk_twist, TWIST_DEG),
        "trunk_side_bent": big(angles.trunk_side_bend, SIDE_BEND_DEG),
        "neck_twisted": big(angles.neck_twist, TWIST_DEG),
        "neck_side_bent": big(angles.neck_side_bend, SIDE_BEND_DEG),
        "left_arm_abducted": big(angles.left.upper_arm_abduction, ABDUCTION_DEG),
        "right_arm_abducted": big(angles.right.upper_arm_abduction, ABDUCTION_DEG),
        "left_wrist_deviated": big(angles.left.wrist_deviation, WRIST_DEVIATION_DEG),
        "right_wrist_deviated": big(angles.right.wrist_deviation, WRIST_DEVIATION_DEG),
        "legs_uneven": bool(knee_gap > LEG_ASYMMETRY_DEG),
        "probably_sitting": bool(
            not np.isnan(max_hip) and not np.isnan(max_knee)
            and max_hip > SITTING_HIP_DEG and max_knee > SITTING_KNEE_DEG
        ),
        # Only meaningful when the head itself is reasonably upright.
        "shoulder_raised_hint": bool(
            not np.isnan(angles.shoulder_ear_ratio)
            and angles.shoulder_ear_ratio < SHOULDER_RAISED_RATIO
            and not np.isnan(angles.neck_flexion)
            and abs(angles.neck_flexion) < 30
        ),
        "knee_asymmetry_deg": round(float(knee_gap), 1),
    }
    return flags
