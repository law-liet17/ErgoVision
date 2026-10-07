"""MediaPipe Pose landmark handling: extraction, scaling and view detection.

Two coordinate spaces are produced for every frame:

* ``pixels``  - 2D, x scaled by image width and y by image height.  Raw
  MediaPipe x/y are normalised independently (x by width, y by height), so
  using them directly skews every angle by the aspect ratio.
* ``world``   - 3D metric landmarks (``pose_world_landmarks``), origin at the
  hip centre, axes aligned with the image (x right, y down, z depth).

Sagittal/frontal decomposition needs 3D, so ``world`` is preferred when
available; ``pixels`` is the fallback and is also what we draw with.
"""

from dataclasses import dataclass, field

import numpy as np

from .geometry import length, midpoint, project_out, unit

# MediaPipe Pose (BlazePose, 33 landmarks) indices we care about.
LM = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_pinky": 17,
    "right_pinky": 18,
    "left_index": 19,
    "right_index": 20,
    "left_thumb": 21,
    "right_thumb": 22,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
    "left_heel": 29,
    "right_heel": 30,
    "left_foot_index": 31,
    "right_foot_index": 32,
}

# Landmarks whose visibility we require for a usable assessment.
CORE = ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]


@dataclass
class Frame:
    """One analysed frame: points in both spaces plus derived body axes."""

    pixels: dict = field(default_factory=dict)
    world: dict = field(default_factory=dict)
    visibility: dict = field(default_factory=dict)
    width: int = 0
    height: int = 0
    has_world: bool = False

    # --- point access -----------------------------------------------------
    def p(self, name):
        """Point in the primary space (world if available, else pixels)."""
        return self.world[name] if self.has_world else self.pixels[name]

    def mid(self, a, b):
        return midpoint(self.p(a), self.p(b))

    def vis(self, *names):
        """Lowest visibility among the named landmarks (0..1)."""
        vals = [self.visibility.get(n, 0.0) for n in names]
        return float(min(vals)) if vals else 0.0

    # --- body axes --------------------------------------------------------
    @property
    def up_global(self):
        """Gravity up in the primary space (image y grows downward)."""
        n = 3 if self.has_world else 2
        v = np.zeros(n)
        v[1] = -1.0
        return v

    @property
    def shoulder_mid(self):
        return self.mid("left_shoulder", "right_shoulder")

    @property
    def hip_mid(self):
        return self.mid("left_hip", "right_hip")

    @property
    def ear_mid(self):
        return self.mid("left_ear", "right_ear")

    @property
    def trunk_up(self):
        """Trunk long axis, hips -> shoulders."""
        return unit(self.shoulder_mid - self.hip_mid)

    @property
    def lateral(self):
        """Person's own left-to-right axis, orthogonal to the trunk axis."""
        raw = self.p("right_shoulder") - self.p("left_shoulder")
        return unit(project_out(raw, self.trunk_up))

    @property
    def forward(self):
        """Anterior direction (where the body faces), orthogonal to trunk.

        Taken from the nose, which stays anterior to the shoulder line in every
        realistic posture; the feet are a backup when the nose projection is
        ambiguous (e.g. a pure front or back view).
        """
        nose_vec = project_out(self.p("nose") - self.shoulder_mid, self.trunk_up)
        cand = project_out(nose_vec, self.lateral)
        if length(cand) > 1e-6:
            return unit(cand)
        try:
            toes = self.mid("left_foot_index", "right_foot_index")
            heels = self.mid("left_heel", "right_heel")
            cand = project_out(project_out(toes - heels, self.trunk_up), self.lateral)
        except KeyError:
            pass
        return unit(cand)

    def side_axis(self, side):
        """Outward (abduction) direction for the given arm."""
        return self.lateral if side == "right" else -self.lateral

    # --- global (gravity referenced) frame --------------------------------
    @property
    def forward_global(self):
        return unit(project_out(self.forward, self.up_global))

    @property
    def lateral_global(self):
        return unit(project_out(self.lateral, self.up_global))

    @property
    def torso_length(self):
        return length(self.shoulder_mid - self.hip_mid)


def _points(landmark_list, sx, sy, sz=None, three_d=False):
    out = {}
    for name, idx in LM.items():
        lm = landmark_list[idx]
        if three_d:
            out[name] = np.array([lm.x * sx, lm.y * sy, lm.z * (sz or 1.0)], dtype=float)
        else:
            out[name] = np.array([lm.x * sx, lm.y * sy], dtype=float)
    return out


def build_frame(results, width, height):
    """Build a :class:`Frame` from a MediaPipe Pose result."""
    if not results.pose_landmarks:
        return None

    lms = results.pose_landmarks.landmark
    frame = Frame(width=width, height=height)
    frame.pixels = _points(lms, width, height)
    frame.visibility = {name: float(lms[idx].visibility) for name, idx in LM.items()}

    world = getattr(results, "pose_world_landmarks", None)
    if world is not None:
        # World landmarks are already metric and isotropic (metres).
        frame.world = _points(world.landmark, 1.0, 1.0, 1.0, three_d=True)
        frame.has_world = True
    return frame


# ---------------------------------------------------------------------------
# View classification
# ---------------------------------------------------------------------------

def classify_view(frame):
    """Work out whether the camera sees the person from the side or the front.

    RULA/REBA angles are sagittal-plane measurements, so a side view is the
    correct capture.  The shoulder line tells us the rotation: seen from the
    front it spans the image horizontally, seen from the side it collapses.

    Returns a dict with the view, the estimated rotation of the shoulder line
    away from the camera plane, and the facing direction.
    """
    sh_l = frame.pixels["left_shoulder"]
    sh_r = frame.pixels["right_shoulder"]
    torso = length(frame.pixels["left_shoulder"] - frame.pixels["left_hip"]) or 1.0
    spread = abs(sh_r[0] - sh_l[0]) / torso  # ~0.8-1.0 front-on, ~0.0-0.3 side-on

    rotation = None
    if frame.has_world:
        w = frame.world["right_shoulder"] - frame.world["left_shoulder"]
        # Angle of the shoulder line out of the camera plane: 0 = front, 90 = side.
        rotation = abs(np.degrees(np.arctan2(abs(w[2]), abs(w[0]))))

    if spread < 0.38:
        view = "side"
    elif spread > 0.68:
        view = "front"
    else:
        view = "oblique"

    # Which way is the person facing in the image? (+1 = towards image right)
    facing = 1 if frame.forward_global[0] >= 0 else -1

    # Which side of the body is nearer the camera / better tracked?
    left_vis = frame.vis("left_shoulder", "left_hip", "left_elbow", "left_wrist")
    right_vis = frame.vis("right_shoulder", "right_hip", "right_elbow", "right_wrist")
    near_side = "left" if left_vis >= right_vis else "right"

    return {
        "view": view,
        "shoulder_spread_ratio": round(float(spread), 3),
        "shoulder_rotation_deg": None if rotation is None else round(float(rotation), 1),
        "facing": "right" if facing > 0 else "left",
        "near_side": near_side,
        "left_visibility": round(left_vis, 3),
        "right_visibility": round(right_vis, 3),
    }


def quality_warnings(frame, view_info):
    """Human readable warnings about capture quality."""
    warnings = []
    missing = [n for n in CORE if frame.visibility.get(n, 0) < 0.5]
    if missing:
        warnings.append(
            "Low confidence on core landmarks (%s). Make sure the whole torso is in shot."
            % ", ".join(m.replace("_", " ") for m in missing)
        )
    if view_info["view"] == "front":
        warnings.append(
            "Front/back view detected. RULA and REBA are defined on sagittal (side-on) "
            "angles, so trunk, neck, upper-arm and elbow flexion will be underestimated. "
            "Re-shoot from the worker's side for a valid score."
        )
    elif view_info["view"] == "oblique":
        detail = (
            "%sdeg shoulder rotation" % view_info["shoulder_rotation_deg"]
            if view_info["shoulder_rotation_deg"] is not None
            else "spread %s" % view_info["shoulder_spread_ratio"]
        )
        warnings.append(
            "Oblique view detected (%s). Angles are projected onto the estimated "
            "sagittal plane; treat borderline scores with care." % detail
        )
    if frame.vis("left_ankle", "right_ankle") < 0.4:
        warnings.append("Feet/ankles not clearly visible - leg and knee scoring is an estimate.")
    if frame.vis("left_index", "right_index") < 0.4:
        warnings.append(
            "Hands not clearly visible - wrist angles are an estimate; set them "
            "manually if the task is hand intensive."
        )
    if not frame.has_world:
        warnings.append(
            "3D landmarks unavailable - twist, side-bend and abduction detection are disabled."
        )
    return warnings
