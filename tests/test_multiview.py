"""Tests for the multi-photo assessment (feature 1).

Run with:  python tests/test_multiview.py
"""

import math
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ergonomics import Modifiers, analysis, compute_angles, multiview, score_angles  # noqa: E402
from ergonomics.analysis import angles_from_dict  # noqa: E402
from ergonomics.landmarks import LM, build_frame  # noqa: E402
from test_scoring import standing_body  # noqa: E402

BLANK = np.zeros((1000, 1000, 3), np.uint8)
HIDE_LEFT_HAND = {"left_wrist": 0.1, "left_index": 0.1, "left_pinky": 0.1}


def photo(view="side", hide=None, **pose):
    """A synthetic detection of the worker; `view="front"` turns them 90 deg to the camera."""
    results = standing_body(**pose)
    if view == "front":
        for lms in (results.pose_world_landmarks.landmark, results.pose_landmarks.landmark):
            world = lms is results.pose_world_landmarks.landmark
            for lm in lms:
                # Rotate about the vertical axis: forward (x) goes into depth, lateral (z) across.
                x, z = ((lm.x, lm.z) if world else ((lm.x - 0.5) * 2, lm.z * 2))
                x, z = z, -x
                lm.x, lm.z = (x, z) if world else (0.5 + x / 2, z / 2)
    for name, vis in (hide or {}).items():
        results.pose_landmarks.landmark[LM[name]].visibility = vis
    return build_frame(results, 1000, 1000)


def run_views(frames, modifiers=None):
    """analyse_views with the pose model replaced by prepared frames."""
    queue = list(frames)
    with mock.patch.object(multiview, "detect_frame", side_effect=lambda *a, **k: queue.pop(0)):
        return multiview.analyse_views([BLANK] * len(frames), modifiers or Modifiers())


class TestViewSelection(unittest.TestCase):
    def test_synthetic_views_classify(self):
        self.assertEqual(multiview.classify_view(photo("side"))["view"], "side")
        self.assertEqual(multiview.classify_view(photo("front"))["view"], "front")

    def test_flexion_comes_from_the_side_photo(self):
        # The front photo shows a different (smaller) bend; the side photo must win.
        result = run_views([photo("front", trunk_deg=10), photo("side", trunk_deg=40)])
        self.assertAlmostEqual(result["angles"]["trunk_flexion"], 40, delta=1.5)
        self.assertEqual(result["sources"]["trunk_flexion"]["photo"], 2)
        self.assertEqual(result["sources"]["trunk_flexion"]["view"], "side")

    def test_abduction_and_twist_come_from_the_front_photo(self):
        result = run_views([photo("side"), photo("front")])
        for key in ("left.upper_arm_abduction", "right.upper_arm_abduction", "trunk_twist"):
            self.assertEqual(result["sources"][key]["photo"], 2, key)
            self.assertEqual(result["sources"][key]["view"], "front", key)

    def test_higher_visibility_wins_within_the_same_view(self):
        dim = {"left_shoulder": 0.6, "left_elbow": 0.6, "left_wrist": 0.6}
        result = run_views([photo("side", hide=dim, elbow_deg=30), photo("side", elbow_deg=90)])
        self.assertEqual(result["sources"]["left.elbow_flexion"]["photo"], 2)
        self.assertAlmostEqual(result["angles"]["left"]["elbow_flexion"], 90, delta=1.5)

    def test_every_angle_names_its_photo(self):
        result = run_views([photo("side"), photo("front")])
        for key in ("trunk_flexion", "neck_flexion", "left.elbow_flexion", "right_knee_flexion"):
            self.assertIn(result["sources"][key]["photo"], (1, 2), key)
        used = sorted(k for p in result["photos"] for k in p["used_for"])
        self.assertEqual(used, sorted(result["sources"]))

    def test_no_side_photo_is_warned(self):
        result = run_views([photo("front"), photo("front")])
        self.assertTrue(any("side-on" in w for w in result["warnings"]))


class TestHiddenJoint(unittest.TestCase):
    def setUp(self):
        # A bent elbow: with a dead-straight synthetic arm the wrist's palm side is undefined.
        self.result = run_views([photo("side", hide=HIDE_LEFT_HAND, elbow_deg=40),
                                 photo("front", hide=HIDE_LEFT_HAND, elbow_deg=40)],
                                Modifiers(assessed_side="left"))

    def test_alert_instead_of_an_angle(self):
        self.assertIsNone(self.result["angles"]["left"]["wrist_flexion"])
        messages = [m["message"] for m in self.result["missing_joints"]]
        self.assertIn("Left wrist is not visible. Upload another photo showing this joint, "
                      "or the wrist score cannot be calculated.", messages)
        self.assertNotIn("left.wrist_flexion", self.result["sources"])

    def test_the_other_wrist_is_still_measured(self):
        self.assertIsNotNone(self.result["angles"]["right"]["wrist_flexion"])
        self.assertNotIn("right.wrist_flexion", [m["key"] for m in self.result["missing_joints"]])

    def test_score_is_marked_as_a_minimum(self):
        for tool in ("rula", "reba"):
            wrist = self.result[tool]["components"]["wrist"]
            self.assertTrue(wrist["missing"], tool)
            self.assertIsNone(wrist["angle"], tool)
            self.assertTrue(self.result[tool]["is_minimum"], tool)
            self.assertIn("wrist (left)", self.result[tool]["missing_rows"], tool)

    def test_no_fix_advice_for_the_hidden_wrist(self):
        self.assertFalse([f for f in self.result["insights"] if f["segment"] == "wrist"])


class TestMissingAngleScoring(unittest.TestCase):
    def test_missing_angles_score_the_lowest_band(self):
        # Before this feature a NaN wrist fell through every band test and scored the maximum.
        data = compute_angles(photo("side", arm_deg=100, elbow_deg=10)).to_dict()
        for key in ("upper_arm_flexion", "elbow_flexion", "wrist_flexion"):
            data["left"][key] = None
        result = score_angles(angles_from_dict(data), Modifiers(assessed_side="left"))
        for row in ("upper_arm", "lower_arm", "wrist"):
            self.assertEqual(result["rula"]["components"][row]["base"], 1, row)
            self.assertTrue(result["rula"]["components"][row]["missing"], row)

    def test_both_knees_hidden(self):
        hide = {n: 0.1 for n in ("left_knee", "right_knee", "left_ankle", "right_ankle")}
        result = run_views([photo("side", hide=hide)])
        self.assertTrue(result["reba"]["components"]["legs"]["missing"])
        self.assertEqual(len([m for m in result["missing_joints"] if m["row"] == "legs"]), 2)


class TestSinglePhotoUnchanged(unittest.TestCase):
    def test_full_visibility_gives_a_complete_score(self):
        frame = photo("side", trunk_deg=35, arm_deg=60, elbow_deg=40)
        result = score_angles(compute_angles(frame), Modifiers())
        self.assertFalse(result["rula"]["is_minimum"])
        self.assertFalse(result["reba"]["is_minimum"])

    def test_analyse_image_matches_one_photo_through_analyse_views(self):
        frame = photo("side", trunk_deg=35, arm_deg=60, elbow_deg=40)
        with mock.patch.object(analysis, "detect_frame", return_value=frame):
            single = analysis.analyse_image(BLANK, Modifiers(), annotate=False)
        multi = run_views([frame])
        self.assertEqual(single["rula"]["grand_score"], multi["rula"]["grand_score"])
        self.assertEqual(single["reba"]["reba_score"], multi["reba"]["reba_score"])
        self.assertNotIn("sources", single)  # /analyze output keeps its old shape

    def test_too_many_photos(self):
        with self.assertRaises(ValueError):
            multiview.analyse_views([BLANK] * 4)


if __name__ == "__main__":
    unittest.main()
