"""Tests for marker (sticker) mode (feature 6).

Run with:  python tests/test_markers.py
"""

import copy
import os
import sys
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ergonomics import analysis, compute_angles, markers  # noqa: E402
from ergonomics.landmarks import build_frame  # noqa: E402
from test_scoring import standing_body  # noqa: E402

GREEN, PINK = (0, 255, 0), (180, 60, 255)   # BGR fluorescent tape colours


def frame_for(**pose):
    return build_frame(standing_body(**pose), 1000, 1000)


def with_stickers(points, colour=GREEN, radius=7):
    image = np.full((1000, 1000, 3), 90, np.uint8)
    for x, y in points:
        cv2.circle(image, (int(round(x)), int(round(y))), radius, colour, -1)
    return image


class TestFindStickers(unittest.TestCase):
    def test_finds_sticker_centres(self):
        found = markers.find_stickers(with_stickers([(200, 300), (640, 710)]), "green")
        self.assertEqual(len(found), 2)
        for (x, y), (ex, ey) in zip(sorted(found), [(200, 300), (640, 710)]):
            self.assertAlmostEqual(x, ex, delta=1)
            self.assertAlmostEqual(y, ey, delta=1)

    def test_ignores_specks_large_patches_and_other_colours(self):
        image = with_stickers([(200, 300)])
        cv2.circle(image, (500, 500), 1, GREEN, -1)                  # a speck
        cv2.rectangle(image, (600, 100), (900, 400), GREEN, -1)      # a green shirt, not tape
        cv2.circle(image, (300, 800), 7, PINK, -1)                   # a different colour
        self.assertEqual(len(markers.find_stickers(image, "green")), 1)
        self.assertEqual(len(markers.find_stickers(image, "pink")), 1)

    def test_ignores_stripes_and_patches_away_from_the_worker(self):
        image = with_stickers([(200, 300), (700, 300)])
        cv2.rectangle(image, (100, 500), (400, 512), GREEN, -1)      # a painted wall stripe
        self.assertEqual(len(markers.find_stickers(image, "green")), 2)
        worker_box = [0.1, 0.2, 0.4, 0.9]                            # only the left sticker is on the worker
        self.assertEqual(len(markers.find_stickers(image, "green", worker_box)), 1)

    def test_unknown_colour(self):
        with self.assertRaises(ValueError):
            markers.find_stickers(with_stickers([]), "purple")


class TestSnapToStickers(unittest.TestCase):
    def test_joints_land_on_the_stickers_and_the_angle_follows(self):
        truth = frame_for(elbow_deg=90)              # what the worker is really doing
        seen = frame_for(elbow_deg=60)               # what the model guessed under a loose sleeve
        stickers = [tuple(truth.pixels[j][:2]) for j in ("left_elbow", "left_wrist")]
        corrections, unused = markers.snap_to_stickers(seen, stickers)
        self.assertEqual(unused, 0)
        moved = {c["joint"]: c for c in corrections}
        self.assertIn("left_wrist", moved)
        np.testing.assert_allclose(seen.pixels["left_wrist"][:2], truth.pixels["left_wrist"][:2], atol=1e-6)
        self.assertAlmostEqual(compute_angles(seen).left.elbow_flexion, 90, delta=1.5)

    def test_each_sticker_corrects_one_joint(self):
        # In a side view both elbows sit on the same pixel; one sticker must not move both.
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        corrections, _ = markers.snap_to_stickers(seen, [tuple(truth.pixels["left_wrist"][:2])])
        self.assertEqual([c["joint"] for c in corrections], ["left_wrist"])
        self.assertAlmostEqual(compute_angles(seen).right.elbow_flexion, 60, delta=1.5)

    def test_a_hidden_joint_never_takes_a_visible_joints_sticker(self):
        # The far-side elbow sits a hair closer to the sticker but the model barely sees it.
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        seen.visibility["left_wrist"], seen.visibility["right_wrist"] = 0.2, 0.95
        seen.pixels["left_wrist"] = truth.pixels["left_wrist"].copy() + [1.0, 0.0]
        corrections, _ = markers.snap_to_stickers(seen, [tuple(truth.pixels["left_wrist"][:2])])
        self.assertEqual([c["joint"] for c in corrections], ["right_wrist"])

    def test_the_hand_moves_with_the_wrist(self):
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        gap = seen.pixels["left_index"] - seen.pixels["left_wrist"]
        markers.snap_to_stickers(seen, [tuple(truth.pixels["left_wrist"][:2])])
        np.testing.assert_allclose(seen.pixels["left_index"] - seen.pixels["left_wrist"], gap, atol=1e-6)
        self.assertLess(abs(compute_angles(seen).left.wrist_flexion), 45)   # not flipped round

    def test_a_sticker_far_from_every_joint_moves_nothing(self):
        seen = frame_for()
        before = copy.deepcopy(seen.pixels)
        corrections, unused = markers.snap_to_stickers(seen, [(990.0, 10.0)])
        self.assertEqual((corrections, unused), ([], 1))
        for name in before:
            np.testing.assert_array_equal(seen.pixels[name], before[name])

    def test_a_pinned_joint_counts_as_visible(self):
        # Both wrists share a pixel in this side view; the better-seen (near) one takes the sticker.
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        seen.visibility["left_wrist"], seen.visibility["right_wrist"] = 0.6, 0.3
        corrections, _ = markers.snap_to_stickers(seen, [tuple(truth.pixels["left_wrist"][:2])])
        self.assertEqual([c["joint"] for c in corrections], ["left_wrist"])
        self.assertGreaterEqual(seen.visibility["left_wrist"], markers.SEEN)
        self.assertEqual(seen.visibility["right_wrist"], 0.3)


class TestMarkerModeInThePipeline(unittest.TestCase):
    def analyse(self, image, frame, colour):
        with mock.patch.object(analysis, "detect_frame", return_value=copy.deepcopy(frame)):
            return analysis.analyse_image(image, annotate=True, markers=colour)

    def test_without_marker_mode_nothing_changes(self):
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        image = with_stickers([tuple(truth.pixels["left_wrist"][:2])])
        off = self.analyse(image, seen, None)
        self.assertNotIn("markers", off)
        self.assertAlmostEqual(off["angles"]["left"]["elbow_flexion"], 60, delta=1.5)

    def test_marker_mode_corrects_and_reports(self):
        truth, seen = frame_for(elbow_deg=90), frame_for(elbow_deg=60)
        image = with_stickers([tuple(truth.pixels["left_wrist"][:2])])
        on = self.analyse(image, seen, "green")
        self.assertEqual(on["markers"]["stickers_found"], 1)
        self.assertEqual([c["joint"] for c in on["markers"]["corrected"]], ["left_wrist"])
        self.assertAlmostEqual(on["angles"]["left"]["elbow_flexion"], 90, delta=1.5)

    def test_marker_mode_with_no_stickers_in_view(self):
        seen = frame_for(elbow_deg=60)
        on = self.analyse(with_stickers([]), seen, "green")
        self.assertEqual(on["markers"]["corrected"], [])
        self.assertAlmostEqual(on["angles"]["left"]["elbow_flexion"], 60, delta=1.5)


if __name__ == "__main__":
    unittest.main()
