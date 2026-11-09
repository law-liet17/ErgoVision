"""Tests for the research benchmark script (feature 7).

Run with:  python tests/test_benchmark.py
"""

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import benchmark  # noqa: E402
from ergonomics.landmarks import build_frame  # noqa: E402
from test_scoring import standing_body  # noqa: E402

POSE = dict(trunk_deg=30, neck_deg=20, arm_deg=60, elbow_deg=40, knee_deg=25)


def keypoints(mirror=False, **pose):
    """2D keypoints of the synthetic side-on worker (optionally facing the other way)."""
    frame = build_frame(standing_body(**pose), 1000, 1000)
    kp = {n: (1000 - p[0] if mirror else p[0], p[1]) for n, p in frame.pixels.items()}
    return kp, {n: 1.0 for n in kp}


class FakeModel:
    def __init__(self, name, kp, scores):
        self.name, self.kp, self.scores = name, kp, scores

    def keypoints(self, image):
        return dict(self.kp), dict(self.scores)


class TestAngles(unittest.TestCase):
    def check(self, mirror):
        kp, sc = benchmark.add_midpoints(*keypoints(mirror, **POSE))
        a = benchmark.angles_2d(kp)
        self.assertAlmostEqual(a["trunk_flexion"], 30, delta=1)
        self.assertAlmostEqual(a["neck_flexion"], 20, delta=1)
        self.assertAlmostEqual(a["left_upper_arm_flexion"], 60, delta=1)
        self.assertAlmostEqual(a["left_elbow_flexion"], 40, delta=1)
        self.assertAlmostEqual(a["left_knee_flexion"], 25, delta=1)
        self.assertAlmostEqual(a["left_wrist_flexion"], 0, delta=1)

    def test_facing_right(self):
        self.check(mirror=False)

    def test_facing_left_gives_the_same_signs(self):
        self.check(mirror=True)

    def test_backward_lean_is_negative(self):
        kp, _ = benchmark.add_midpoints(*keypoints(trunk_deg=-15))
        self.assertAlmostEqual(benchmark.angles_2d(kp)["trunk_flexion"], -15, delta=1)


class TestDetection(unittest.TestCase):
    def test_a_model_without_hand_points_reports_wrist_not_available(self):
        kp, sc = keypoints(**POSE)
        coco = {n: kp[n] for n in benchmark.COCO17}
        out = benchmark.measure_2d(FakeModel("yolov8", coco, {n: 0.9 for n in coco}), None)
        self.assertEqual(out["left_wrist_flexion"], (None, "not available"))
        self.assertEqual(out["left_elbow_flexion"][1], "yes")

    def test_a_low_confidence_joint_is_not_detected(self):
        kp, sc = keypoints(**POSE)
        sc["left_knee"] = 0.1
        out = benchmark.measure_2d(FakeModel("mediapipe", kp, sc), None)
        self.assertEqual(out["left_knee_flexion"], (None, "no"))
        self.assertEqual(out["right_knee_flexion"][1], "yes")

    def test_nobody_in_the_photo(self):
        out = benchmark.measure_2d(FakeModel("mediapipe", {}, {}), None)
        self.assertTrue(all(v == (None, "no") for v in out.values()))


class TestCsv(unittest.TestCase):
    def test_one_command_writes_the_minitab_sheet(self):
        tmp = tempfile.mkdtemp()
        cv2.imwrite(os.path.join(tmp, "p1.jpg"), np.zeros((50, 50, 3), np.uint8))
        template = benchmark.write_template(tmp, os.path.join(tmp, "truth.csv"))
        with open(template, newline="") as fh:
            rows = list(csv.DictReader(fh))
        rows[0].update(camera_angle="side", clothing="loose", markers="no", trunk_flexion="28", left_elbow_flexion="45")
        with open(template, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        kp, sc = keypoints(**POSE)
        fake = FakeModel("mediapipe", kp, sc)
        out = os.path.join(tmp, "results.csv")
        with mock.patch.dict(benchmark.MODELS, {"mediapipe": lambda: fake}, clear=True):
            benchmark.main([tmp, template, "-o", out, "-m", "mediapipe"])

        with open(out, newline="") as fh:
            result = list(csv.DictReader(fh))
        self.assertEqual(list(result[0]), benchmark.OUT_COLUMNS)
        self.assertEqual(len(result), len(benchmark.JOINTS))
        trunk = next(r for r in result if r["joint"] == "trunk_flexion")
        self.assertEqual((trunk["true_angle"], trunk["camera_angle"], trunk["clothing"], trunk["markers"]),
                         ("28.0", "side", "loose", "no"))
        self.assertAlmostEqual(float(trunk["error"]), 2.0, delta=1)
        neck = next(r for r in result if r["joint"] == "neck_flexion")
        self.assertEqual((neck["true_angle"], neck["error"]), ("", ""))   # not measured -> blank, not 0


if __name__ == "__main__":
    unittest.main()
