"""Pose-model benchmark for the paper - not part of the app.

Runs several pose models on a folder of test photos, measures the joint angles
the worksheets use, and compares them with goniometer readings. The output is
one long CSV (one row per photo x model x joint) that Minitab reads directly
for the DOE / ANOVA.

    python research/benchmark.py PHOTOS_DIR TRUTH_CSV -o results.csv
    python research/benchmark.py PHOTOS_DIR --template truth.csv     # blank sheet to fill in

Models (each is skipped with a message if its package is missing):
    mediapipe      MediaPipe Pose Landmarker (the app's model), 33 points incl. hands
    yolov8         YOLOv8-pose (ultralytics), 17 COCO points - no hand points, so
                   wrist bend is recorded as "not available"
    rtmpose        RTMPose whole-body (rtmlib, ONNX), 133 points incl. hands
    ergovision     the app's full pipeline (MediaPipe + 3D angles + marker mode),
                   for reference: what the product actually reports

So that differences come from the models and not from the maths, every model's
angle is computed from its 2D image keypoints with the same formulas below
(side-on photos, sagittal plane). The ``ergovision`` rows use the app's own 3D
angles instead.
"""

import argparse
import csv
import math
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# Angles measured, in the order of the sheet. Each needs these keypoints.
JOINTS = {
    "trunk_flexion": ["shoulder_mid", "hip_mid", "nose"],
    "neck_flexion": ["ear_mid", "shoulder_mid", "hip_mid", "nose"],
    "left_upper_arm_flexion": ["left_shoulder", "left_elbow", "hip_mid", "shoulder_mid", "nose"],
    "right_upper_arm_flexion": ["right_shoulder", "right_elbow", "hip_mid", "shoulder_mid", "nose"],
    "left_elbow_flexion": ["left_shoulder", "left_elbow", "left_wrist"],
    "right_elbow_flexion": ["right_shoulder", "right_elbow", "right_wrist"],
    "left_wrist_flexion": ["left_elbow", "left_wrist", "left_hand"],
    "right_wrist_flexion": ["right_elbow", "right_wrist", "right_hand"],
    "left_knee_flexion": ["left_hip", "left_knee", "left_ankle"],
    "right_knee_flexion": ["right_hip", "right_knee", "right_ankle"],
}
META = ["camera_angle", "clothing", "markers", "marker_colour"]   # per-photo factors in the truth sheet
OUT_COLUMNS = ["photo", "model", "joint", "measured_angle", "true_angle", "error", "abs_error",
               "joint_detected", "camera_angle", "clothing", "markers"]

# A keypoint counts as detected at or above this confidence (each model scores on its own scale).
MIN_SCORE = {"mediapipe": 0.5, "yolov8": 0.5, "rtmpose": 0.3, "ergovision": 0.5}


# ---------------------------------------------------------------------------
# 2D angle maths, shared by every model
# ---------------------------------------------------------------------------

def _angle(v1, v2):
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return float("nan")
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(v1, v2) / (n1 * n2))))))


def _signed(v, ref, pos):
    """Angle of v from ref, + when v leans towards ``pos`` (as the engine's signed_angle)."""
    r = ref / (np.linalg.norm(ref) or 1.0)
    pos_perp = pos - np.dot(pos, r) * r
    return _angle(v, ref) * (1.0 if np.dot(v, pos_perp) >= 0 else -1.0)


def angles_2d(kp):
    """Worksheet angles from 2D keypoints ``{name: (x, y)}`` (missing names -> NaN)."""
    p = {k: np.asarray(v, float) for k, v in kp.items()}
    out = {}

    def has(*names):
        return all(n in p for n in names)

    facing = 0.0
    if has("nose", "shoulder_mid"):
        facing = 1.0 if p["nose"][0] >= p["shoulder_mid"][0] else -1.0
    up = np.array([0.0, -1.0])                     # image y points down
    if has("shoulder_mid", "hip_mid") and facing:
        trunk = p["shoulder_mid"] - p["hip_mid"]
        front = facing * np.array([-trunk[1], trunk[0]])   # perpendicular to the trunk, on the face side
        out["trunk_flexion"] = _signed(trunk, up, np.array([facing, 0.0]))
        if has("ear_mid"):
            out["neck_flexion"] = _signed(p["ear_mid"] - p["shoulder_mid"], trunk, front)
        for side in ("left", "right"):
            if has(f"{side}_shoulder", f"{side}_elbow"):
                out[f"{side}_upper_arm_flexion"] = _signed(p[f"{side}_elbow"] - p[f"{side}_shoulder"], -trunk, front)
    for side in ("left", "right"):
        if has(f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist"):
            out[f"{side}_elbow_flexion"] = 180.0 - _angle(p[f"{side}_shoulder"] - p[f"{side}_elbow"],
                                                          p[f"{side}_wrist"] - p[f"{side}_elbow"])
        if has(f"{side}_elbow", f"{side}_wrist", f"{side}_hand"):
            out[f"{side}_wrist_flexion"] = 180.0 - _angle(p[f"{side}_elbow"] - p[f"{side}_wrist"],
                                                          p[f"{side}_hand"] - p[f"{side}_wrist"])
        if has(f"{side}_hip", f"{side}_knee", f"{side}_ankle"):
            out[f"{side}_knee_flexion"] = 180.0 - _angle(p[f"{side}_hip"] - p[f"{side}_knee"],
                                                         p[f"{side}_ankle"] - p[f"{side}_knee"])
    return out


def add_midpoints(kp, scores):
    """Shoulder/hip/ear midpoints and the hand point, scored by their weaker input."""
    for mid, (a, b) in {"shoulder_mid": ("left_shoulder", "right_shoulder"),
                        "hip_mid": ("left_hip", "right_hip"), "ear_mid": ("left_ear", "right_ear")}.items():
        if a in kp and b in kp:
            kp[mid] = (np.asarray(kp[a]) + np.asarray(kp[b])) / 2
            scores[mid] = min(scores[a], scores[b])
    for side in ("left", "right"):
        a, b = f"{side}_index", f"{side}_pinky"
        if a in kp and b in kp:
            kp[f"{side}_hand"] = (np.asarray(kp[a]) + np.asarray(kp[b])) / 2
            scores[f"{side}_hand"] = min(scores[a], scores[b])
    return kp, scores


# ---------------------------------------------------------------------------
# Models: each returns ({name: (x, y)}, {name: score}) for the most prominent person
# ---------------------------------------------------------------------------

COCO17 = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
          "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip",
          "left_knee", "right_knee", "left_ankle", "right_ankle"]


class MediaPipeModel:
    name = "mediapipe"

    def __init__(self):
        from ergonomics.landmarks import LM
        from ergonomics.pose_backend import get_backend
        self.backend, self.lm = get_backend(static=True), LM

    def keypoints(self, image):
        h, w = image.shape[:2]
        people = self.backend.detect_all(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if not people:
            return {}, {}
        lms = people[0].pose_landmarks.landmark     # most confident first
        kp = {n: (lms[i].x * w, lms[i].y * h) for n, i in self.lm.items()}
        return kp, {n: float(lms[i].visibility) for n, i in self.lm.items()}


class YoloModel:
    name = "yolov8"

    def __init__(self, weights=os.path.join(ROOT, "research", "weights", "yolov8n-pose.pt")):
        from ultralytics import YOLO
        os.makedirs(os.path.dirname(weights), exist_ok=True)   # downloaded here on first use
        self.model = YOLO(weights)

    def keypoints(self, image):
        res = self.model(image, verbose=False)[0]
        if res.keypoints is None or len(res.keypoints) == 0:
            return {}, {}
        best = int(np.argmax(res.boxes.conf.cpu().numpy()))
        xy = res.keypoints.xy[best].cpu().numpy()
        conf = res.keypoints.conf[best].cpu().numpy()
        return ({n: tuple(xy[i]) for i, n in enumerate(COCO17)},
                {n: float(conf[i]) for i, n in enumerate(COCO17)})


class RtmPoseModel:
    """RTMPose whole-body via rtmlib: COCO 17 body, then feet, face, left hand (91-111), right hand (112-132)."""
    name = "rtmpose"
    HAND = {"left": 91, "right": 112}   # hand root; index MCP = +5, pinky MCP = +17

    def __init__(self):
        from rtmlib import Wholebody
        self.model = Wholebody(mode="balanced", backend="onnxruntime", device="cpu")

    def keypoints(self, image):
        kps, scores = self.model(image)
        if kps is None or len(kps) == 0:
            return {}, {}
        best = int(np.argmax(scores.mean(axis=1)))
        k, s = kps[best], scores[best]
        kp = {n: tuple(k[i]) for i, n in enumerate(COCO17)}
        sc = {n: float(s[i]) for i, n in enumerate(COCO17)}
        for side, root in self.HAND.items():
            for name, off in (("index", 5), ("pinky", 17)):
                kp[f"{side}_{name}"], sc[f"{side}_{name}"] = tuple(k[root + off]), float(s[root + off])
        return kp, sc


class ErgoVisionModel:
    """The app's own pipeline: MediaPipe + 3D angles (+ marker mode when the photo has stickers)."""
    name = "ergovision"
    APP_ANGLE = {
        "trunk_flexion": lambda a: a["trunk_flexion"], "neck_flexion": lambda a: a["neck_flexion"],
        **{f"{s}_upper_arm_flexion": (lambda s: lambda a: a[s]["upper_arm_flexion"])(s) for s in ("left", "right")},
        **{f"{s}_elbow_flexion": (lambda s: lambda a: a[s]["elbow_flexion"])(s) for s in ("left", "right")},
        **{f"{s}_wrist_flexion": (lambda s: lambda a: a[s]["wrist_flexion"])(s) for s in ("left", "right")},
        **{f"{s}_knee_flexion": (lambda s: lambda a: a[f"{s}_knee_flexion"])(s) for s in ("left", "right")},
    }

    def __init__(self):
        from ergonomics import analysis, multiview
        self.analysis, self.multiview = analysis, multiview

    def measure(self, image, marker_colour=None):
        """{joint: (angle or None, detected yes/no)} from the app's own result."""
        try:
            frame = self.analysis.detect_frame(image)
        except self.analysis.MultiplePeople as many:
            frame = max(many.frames, key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]))
        except self.analysis.NoPoseDetected:
            return {j: (None, "no") for j in JOINTS}
        if marker_colour:
            from ergonomics.markers import apply_markers
            apply_markers(image, frame, marker_colour)
        from ergonomics.angles import compute_angles
        angles = compute_angles(frame).to_dict()
        out = {}
        for joint in JOINTS:
            m = next(m for m in self.multiview.MEASURES if _measure_key(joint) == m.key)
            seen, _ = self.multiview.joint_visibility(frame, m.groups)
            value = self.APP_ANGLE[joint](angles)
            out[joint] = (value, "yes" if seen and value is not None else "no")
        return out


def _measure_key(joint):
    """benchmark joint name -> the app's multiview measure key."""
    for side in ("left", "right"):
        for part in ("upper_arm_flexion", "elbow_flexion", "wrist_flexion"):
            if joint == f"{side}_{part}":
                return f"{side}.{part}"
    return joint


MODELS = {"mediapipe": MediaPipeModel, "yolov8": YoloModel, "rtmpose": RtmPoseModel, "ergovision": ErgoVisionModel}


def measure_2d(model, image):
    """{joint: (angle or None, 'yes' | 'no' | 'not available')} for a keypoint model."""
    kp, scores = model.keypoints(image)
    kp, scores = add_midpoints(dict(kp), dict(scores))
    angles = angles_2d(kp) if kp else {}
    out = {}
    for joint, needs in JOINTS.items():
        if not kp:
            out[joint] = (None, "no")
            continue
        if any(n not in kp for n in needs if n != "nose"):
            out[joint] = (None, "not available")      # the model has no such keypoint (e.g. YOLO hands)
            continue
        ok = all(scores.get(n, 0.0) >= MIN_SCORE[model.name] for n in needs if n != "nose")
        value = angles.get(joint)
        out[joint] = (value if ok and value is not None and not math.isnan(value) else None, "yes" if ok else "no")
    return out


# ---------------------------------------------------------------------------
# Truth sheet and output
# ---------------------------------------------------------------------------

def list_photos(folder):
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXT))


def write_template(folder, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["photo"] + META + list(JOINTS))
        for photo in list_photos(folder):
            writer.writerow([photo, "side", "", "no", ""] + [""] * len(JOINTS))
    return path


def read_truth(path):
    """{photo: {"meta": {...}, "angles": {joint: float}}} from the wide goniometer sheet."""
    truth = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            angles = {}
            for joint in JOINTS:
                raw = (row.get(joint) or "").strip()
                if raw and raw != "*":
                    angles[joint] = float(raw)
            truth[photo] = {"meta": {k: (row.get(k) or "").strip() for k in META}, "angles": angles}
    return truth


def _fmt(value):
    return "" if value is None else "%.1f" % (round(value, 1) + 0.0)   # empty = missing for Minitab; no "-0.0"


def run(photos_dir, truth_path, out_path, model_names):
    truth = read_truth(truth_path)
    missing = [p for p in truth if not os.path.isfile(os.path.join(photos_dir, p))]
    if missing:
        print("warning: %d photo(s) in the truth sheet are not in the folder: %s" % (len(missing), ", ".join(missing[:5])))

    models = []
    for name in model_names:
        try:
            models.append(MODELS[name]())
        except ImportError as exc:
            print("skipping %s: %s  (pip install -r research/requirements.txt)" % (name, exc))
    if not models:
        raise SystemExit("no model could be loaded")

    rows, timing = [], {m.name: [] for m in models}
    for photo, sheet in truth.items():
        path = os.path.join(photos_dir, photo)
        image = cv2.imread(path)
        if image is None:
            continue
        meta = sheet["meta"]
        for model in models:
            t0 = time.perf_counter()
            if model.name == "ergovision":
                colour = meta["marker_colour"].lower() if meta["markers"].lower() in ("yes", "y", "1") else None
                measured = model.measure(image, colour or None)
            else:
                measured = measure_2d(model, image)
            timing[model.name].append(time.perf_counter() - t0)
            for joint in JOINTS:
                true = sheet["angles"].get(joint)
                value, detected = measured[joint]
                error = None if value is None or true is None else value - true
                rows.append({"photo": photo, "model": model.name, "joint": joint,
                             "measured_angle": _fmt(value), "true_angle": _fmt(true),
                             "error": _fmt(error), "abs_error": _fmt(None if error is None else abs(error)),
                             "joint_detected": detected, "camera_angle": meta["camera_angle"],
                             "clothing": meta["clothing"], "markers": meta["markers"] or "no"})

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summarise(rows, timing)
    return rows


def summarise(rows, timing):
    print("\n%-12s %8s %10s %10s %8s" % ("model", "MAE (deg)", "detected", "compared", "s/photo"))
    for name, times in timing.items():
        mine = [r for r in rows if r["model"] == name]
        errs = [float(r["abs_error"]) for r in mine if r["abs_error"]]
        possible = [r for r in mine if r["joint_detected"] != "not available"]
        found = sum(r["joint_detected"] == "yes" for r in possible)
        print("%-12s %8s %10s %10d %8.2f" % (
            name, "%.1f" % (sum(errs) / len(errs)) if errs else "-",
            "%d/%d" % (found, len(possible)), len(errs), sum(times) / len(times) if times else 0))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("photos", help="folder of test photos")
    ap.add_argument("truth", nargs="?", help="goniometer CSV (one row per photo, one column per joint)")
    ap.add_argument("-o", "--out", default="benchmark_results.csv", help="output CSV for Minitab")
    ap.add_argument("-m", "--models", default=",".join(MODELS), help="comma list: " + ", ".join(MODELS))
    ap.add_argument("--template", metavar="CSV", help="write a blank truth sheet for the photos and stop")
    args = ap.parse_args(argv)
    if args.template:
        print("wrote", write_template(args.photos, args.template))
        return
    if not args.truth:
        ap.error("give the truth CSV, or --template to create one")
    run(args.photos, args.truth, args.out, [m.strip() for m in args.models.split(",") if m.strip()])
    print("\nwrote", args.out)


if __name__ == "__main__":
    main()
