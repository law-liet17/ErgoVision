"""Tests for the ErgoVision scoring engine.

Run with:  python -m unittest discover -s tests -v
       or:  python tests/test_scoring.py
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ergonomics import Modifiers, compute_angles, score_angles  # noqa: E402
from ergonomics import reba, rula  # noqa: E402
from ergonomics.landmarks import LM, build_frame, classify_view  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic pose fixtures
# ---------------------------------------------------------------------------

class _LM:
    def __init__(self, x, y, z, visibility=1.0):
        self.x, self.y, self.z, self.visibility = x, y, z, visibility


class _List:
    def __init__(self, landmarks):
        self.landmark = landmarks


class _Results:
    def __init__(self, points):
        """`points` maps landmark name -> (x, y, z) in metres, hip centre at origin.

        Image coordinates are a 1:1 orthographic projection of x and y, so the
        pixel space stays consistent with the world space (1000x1000 image).
        """
        world, image = [], []
        for name, idx in sorted(LM.items(), key=lambda kv: kv[1]):
            while len(world) < idx:
                world.append(_LM(0.0, 0.0, 0.0, 0.0))
                image.append(_LM(0.5, 0.5, 0.0, 0.0))
            x, y, z = points[name]
            world.append(_LM(x, y, z))
            image.append(_LM(0.5 + x / 2.0, 0.5 + y / 2.0, z / 2.0))
        self.pose_world_landmarks = _List(world)
        self.pose_landmarks = _List(image)


def rot_sagittal(v, deg):
    """Rotate a point forward (towards +x) about the hip, in the x/y plane."""
    t = math.radians(deg)
    x, y, z = v
    return (x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t), z)


def standing_body(trunk_deg=0.0, neck_deg=0.0, arm_deg=0.0, elbow_deg=0.0, knee_deg=0.0):
    """Build a side-on standing worker with the requested joint angles.

    Angles are the anatomical ones the worksheets use: trunk flexion from
    vertical, neck flexion from the trunk, upper arm flexion from the trunk,
    elbow flexion (0 = straight), knee flexion (0 = straight).
    """
    lat = 0.1   # half hip width / z offset for the left side
    sh_lat = 0.2

    # Upper body defined in trunk-local coordinates then rotated by trunk_deg.
    trunk_len, neck_len, upper_arm, forearm, hand = 0.5, 0.25, 0.3, 0.25, 0.08
    sh_mid_local = (0.0, -trunk_len, 0.0)
    neck_dir_local = rot_sagittal((0.0, -neck_len, 0.0), neck_deg)
    ear_local = tuple(a + b for a, b in zip(sh_mid_local, neck_dir_local))
    nose_local = (ear_local[0] + 0.12, ear_local[1] + 0.03, 0.0)

    # Arm: hangs along the trunk, rotated forward by arm_deg, then the forearm
    # rotated a further elbow_deg.
    # Note the negative sign: rot_sagittal rotates *up* vectors forward, so a
    # downward-pointing segment needs the opposite sense to flex forward.
    arm_vec_local = rot_sagittal((0.0, upper_arm, 0.0), -arm_deg)
    fore_vec_local = rot_sagittal((0.0, forearm, 0.0), -(arm_deg + elbow_deg))
    hand_vec_local = rot_sagittal((0.0, hand, 0.0), -(arm_deg + elbow_deg))

    def up(v):
        return rot_sagittal(v, trunk_deg)

    sh_mid = up(sh_mid_local)
    ear = up(ear_local)
    nose = up(nose_local)
    arm_vec = up(arm_vec_local)
    fore_vec = up(fore_vec_local)
    hand_vec = up(hand_vec_local)

    def add(a, b, z=0.0):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2] + z)

    points = {}
    for side, z in (("left", lat), ("right", -lat)):
        sz = sh_lat if side == "left" else -sh_lat
        points[f"{side}_hip"] = (0.0, 0.0, z)
        points[f"{side}_shoulder"] = (sh_mid[0], sh_mid[1], sz)
        points[f"{side}_ear"] = (ear[0], ear[1], z * 0.7)
        points[f"{side}_eye"] = (ear[0] + 0.06, ear[1] - 0.01, z * 0.5)
        elbow = add((sh_mid[0], sh_mid[1], sz), arm_vec)
        wrist = add(elbow, fore_vec)
        points[f"{side}_elbow"] = elbow
        points[f"{side}_wrist"] = wrist
        points[f"{side}_index"] = add(wrist, hand_vec, 0.01)
        points[f"{side}_pinky"] = add(wrist, hand_vec, -0.01)
        points[f"{side}_thumb"] = add(wrist, hand_vec, 0.02)

        # Legs: thigh straight down, shank rotated back by knee_deg.
        knee = (0.0, 0.45, z)
        shank = rot_sagittal((0.0, 0.45, 0.0), -knee_deg)
        ankle = add(knee, shank)
        points[f"{side}_knee"] = knee
        points[f"{side}_ankle"] = ankle
        points[f"{side}_heel"] = (ankle[0] - 0.05, ankle[1] + 0.03, z)
        points[f"{side}_foot_index"] = (ankle[0] + 0.12, ankle[1] + 0.03, z)

    points["nose"] = nose
    return _Results(points)


def angles_for(**kwargs):
    results = standing_body(**kwargs)
    frame = build_frame(results, 1000, 1000)
    return compute_angles(frame), frame


# ---------------------------------------------------------------------------
# Angle extraction
# ---------------------------------------------------------------------------

class TestAngleExtraction(unittest.TestCase):

    def test_upright_worker_is_neutral(self):
        """The regression test for the old `abs(180 - angle)` bug."""
        angles, _ = angles_for()
        self.assertAlmostEqual(angles.trunk_flexion, 0.0, delta=1.0)
        self.assertAlmostEqual(angles.neck_flexion, 0.0, delta=1.5)
        self.assertAlmostEqual(angles.left.upper_arm_flexion, 0.0, delta=1.0)
        self.assertAlmostEqual(angles.left.elbow_flexion, 0.0, delta=1.0)
        self.assertAlmostEqual(angles.left_knee_flexion, 0.0, delta=1.0)

    def test_trunk_flexion_is_measured_from_vertical(self):
        angles, _ = angles_for(trunk_deg=45.0)
        self.assertAlmostEqual(angles.trunk_flexion, 45.0, delta=1.5)

    def test_trunk_extension_is_negative(self):
        angles, _ = angles_for(trunk_deg=-15.0)
        self.assertLess(angles.trunk_flexion, -10.0)

    def test_neck_is_measured_from_the_trunk_not_gravity(self):
        """Bending the whole upper body must not create neck flexion."""
        angles, _ = angles_for(trunk_deg=40.0, neck_deg=0.0)
        self.assertAlmostEqual(angles.neck_flexion, 0.0, delta=2.0)
        self.assertAlmostEqual(angles.neck_flexion_gravity, 40.0, delta=2.5)

        angles, _ = angles_for(trunk_deg=40.0, neck_deg=25.0)
        self.assertAlmostEqual(angles.neck_flexion, 25.0, delta=2.5)

    def test_upper_arm_is_measured_from_the_trunk(self):
        angles, _ = angles_for(trunk_deg=60.0, arm_deg=0.0)
        self.assertAlmostEqual(angles.left.upper_arm_flexion, 0.0, delta=1.5)
        angles, _ = angles_for(arm_deg=75.0)
        self.assertAlmostEqual(angles.left.upper_arm_flexion, 75.0, delta=1.5)
        self.assertAlmostEqual(angles.left.upper_arm_elevation, 75.0, delta=1.5)

    def test_elbow_flexion_zero_is_a_straight_arm(self):
        angles, _ = angles_for(elbow_deg=90.0)
        self.assertAlmostEqual(angles.left.elbow_flexion, 90.0, delta=1.5)
        angles, _ = angles_for(elbow_deg=0.0)
        self.assertAlmostEqual(angles.left.elbow_flexion, 0.0, delta=1.0)

    def test_knee_flexion(self):
        angles, _ = angles_for(knee_deg=45.0)
        self.assertAlmostEqual(angles.left_knee_flexion, 45.0, delta=1.5)

    def test_side_view_is_detected(self):
        _, frame = angles_for()
        view = classify_view(frame)
        self.assertEqual(view["view"], "side")
        self.assertEqual(view["facing"], "right")

    def test_aspect_ratio_does_not_change_angles(self):
        """Pixel scaling must use width for x and height for y."""
        results = standing_body(trunk_deg=30.0)
        square = compute_angles(build_frame(results, 1000, 1000))
        wide = compute_angles(build_frame(results, 1920, 1080))
        self.assertAlmostEqual(square.trunk_flexion, wide.trunk_flexion, delta=0.5)


# ---------------------------------------------------------------------------
# Table lookups (transcription check against the printed worksheets)
# ---------------------------------------------------------------------------

class TestRulaTables(unittest.TestCase):

    def test_table_a_corners_and_spot_values(self):
        self.assertEqual(rula.lookup_table_a(1, 1, 1, 1), 1)
        self.assertEqual(rula.lookup_table_a(6, 3, 4, 2), 9)
        self.assertEqual(rula.lookup_table_a(2, 2, 3, 1), 3)
        self.assertEqual(rula.lookup_table_a(5, 3, 4, 2), 8)
        self.assertEqual(rula.lookup_table_a(3, 1, 2, 2), 4)

    def test_table_b_spot_values(self):
        self.assertEqual(rula.lookup_table_b(1, 1, 1), 1)
        self.assertEqual(rula.lookup_table_b(1, 1, 2), 3)
        self.assertEqual(rula.lookup_table_b(4, 3, 1), 6)
        self.assertEqual(rula.lookup_table_b(6, 6, 2), 9)

    def test_table_c_spot_values(self):
        self.assertEqual(rula.lookup_table_c(1, 1), 1)
        self.assertEqual(rula.lookup_table_c(5, 4), 5)
        self.assertEqual(rula.lookup_table_c(8, 7), 7)
        self.assertEqual(rula.lookup_table_c(12, 12), 7)  # clamps into the table

    def test_table_shapes(self):
        self.assertEqual(len(rula.TABLE_A_ROWS), 18)
        self.assertTrue(all(len(r) == 8 for r in rula.TABLE_A_ROWS.values()))
        self.assertEqual(len(rula.TABLE_B_ROWS), 6)
        self.assertTrue(all(len(r) == 12 for r in rula.TABLE_B_ROWS.values()))
        self.assertEqual(len(rula.TABLE_C), 8)
        self.assertTrue(all(len(r) == 7 for r in rula.TABLE_C))


class TestRebaTables(unittest.TestCase):

    def test_table_a_spot_values(self):
        self.assertEqual(reba.lookup_table_a(1, 1, 1), 1)
        self.assertEqual(reba.lookup_table_a(2, 3, 2), 5)
        self.assertEqual(reba.lookup_table_a(3, 5, 4), 9)

    def test_table_b_spot_values(self):
        self.assertEqual(reba.lookup_table_b(1, 1, 1), 1)
        self.assertEqual(reba.lookup_table_b(3, 2, 2), 5)
        self.assertEqual(reba.lookup_table_b(6, 2, 3), 9)

    def test_table_c_spot_values(self):
        self.assertEqual(reba.lookup_table_c(1, 1), 1)
        self.assertEqual(reba.lookup_table_c(5, 6), 7)
        self.assertEqual(reba.lookup_table_c(12, 12), 12)

    def test_table_shapes(self):
        self.assertEqual(len(reba.TABLE_A_ROWS), 15)
        self.assertTrue(all(len(r) == 4 for r in reba.TABLE_A_ROWS.values()))
        self.assertEqual(len(reba.TABLE_B_ROWS), 6)
        self.assertTrue(all(len(r) == 6 for r in reba.TABLE_B_ROWS.values()))
        self.assertEqual(len(reba.TABLE_C), 12)
        self.assertTrue(all(len(r) == 12 for r in reba.TABLE_C))


# ---------------------------------------------------------------------------
# Component banding
# ---------------------------------------------------------------------------

NEUTRAL_CTX = Modifiers().resolved({}, "right")


class TestComponents(unittest.TestCase):

    def test_rula_upper_arm_bands(self):
        band = lambda deg: rula.upper_arm_component(deg, NEUTRAL_CTX).score
        self.assertEqual(band(0), 1)
        self.assertEqual(band(15), 1)
        self.assertEqual(band(-15), 1)
        self.assertEqual(band(-40), 2)   # extension beyond 20 deg
        self.assertEqual(band(30), 2)
        self.assertEqual(band(70), 3)
        self.assertEqual(band(120), 4)

    def test_rula_upper_arm_adjustments(self):
        ctx = dict(NEUTRAL_CTX, shoulder_raised=True, arm_abducted=True)
        self.assertEqual(rula.upper_arm_component(70, ctx).score, 5)
        ctx = dict(NEUTRAL_CTX, arm_supported=True)
        self.assertEqual(rula.upper_arm_component(0, ctx).score, 1)  # clamped at 1
        self.assertEqual(rula.upper_arm_component(70, ctx).score, 2)

    def test_lower_arm_band_uses_flexion_not_interior_angle(self):
        band = lambda deg: rula.lower_arm_component(deg, NEUTRAL_CTX).score
        self.assertEqual(band(90), 1)    # right angle -> comfortable
        self.assertEqual(band(0), 2)     # straight arm -> penalised
        self.assertEqual(band(140), 2)

    def test_rula_wrist_bands(self):
        band = lambda deg: rula.wrist_component(deg, NEUTRAL_CTX).score
        self.assertEqual(band(0), 1)
        self.assertEqual(band(12), 2)
        self.assertEqual(band(-12), 2)   # extension scores like flexion
        self.assertEqual(band(30), 3)
        ctx = dict(NEUTRAL_CTX, wrist_deviated=True)
        self.assertEqual(rula.wrist_component(30, ctx).score, 4)

    def test_rula_neck_extension_is_worst_band(self):
        self.assertEqual(rula.neck_component(-20, NEUTRAL_CTX).score, 4)
        self.assertEqual(rula.neck_component(5, NEUTRAL_CTX).score, 1)
        self.assertEqual(rula.neck_component(15, NEUTRAL_CTX).score, 2)
        self.assertEqual(rula.neck_component(35, NEUTRAL_CTX).score, 3)

    def test_rula_trunk_bands(self):
        band = lambda deg: rula.trunk_component(deg, NEUTRAL_CTX).score
        self.assertEqual(band(0), 1)
        self.assertEqual(band(15), 2)
        self.assertEqual(band(40), 3)
        self.assertEqual(band(75), 4)

    def test_reba_leg_knee_adjustment(self):
        ctx = dict(NEUTRAL_CTX, sitting=False, legs_bilateral=True)
        self.assertEqual(reba.legs_component(10, ctx).score, 1)
        self.assertEqual(reba.legs_component(45, ctx).score, 2)
        self.assertEqual(reba.legs_component(80, ctx).score, 3)
        seated = dict(ctx, sitting=True)
        self.assertEqual(reba.legs_component(90, seated).score, 1)

    def test_force_and_coupling(self):
        self.assertEqual(rula.force_score(dict(NEUTRAL_CTX, load_kg=1))[0], 0)
        self.assertEqual(rula.force_score(dict(NEUTRAL_CTX, load_kg=5))[0], 1)
        self.assertEqual(
            rula.force_score(dict(NEUTRAL_CTX, load_kg=5, load_static_or_repeated=True))[0], 2)
        self.assertEqual(rula.force_score(dict(NEUTRAL_CTX, load_kg=15))[0], 3)
        self.assertEqual(reba.force_score(dict(NEUTRAL_CTX, load_kg=3))[0], 0)
        self.assertEqual(reba.force_score(dict(NEUTRAL_CTX, load_kg=8))[0], 1)
        self.assertEqual(reba.force_score(dict(NEUTRAL_CTX, load_kg=12))[0], 2)
        self.assertEqual(
            reba.force_score(dict(NEUTRAL_CTX, load_kg=12, shock_or_rapid_buildup=True))[0], 3)
        self.assertEqual(reba.coupling_score(dict(NEUTRAL_CTX, coupling="poor"))[0], 2)


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def test_neutral_standing_posture_is_low_risk(self):
        angles, _ = angles_for(elbow_deg=90.0)
        result = score_angles(angles, Modifiers(legs_supported=True, legs_bilateral=True))
        self.assertEqual(result["rula"]["components"]["upper_arm"]["score"], 1)
        self.assertEqual(result["rula"]["components"]["lower_arm"]["score"], 1)
        self.assertEqual(result["rula"]["components"]["neck"]["score"], 1)
        self.assertEqual(result["rula"]["components"]["trunk"]["score"], 1)
        self.assertEqual(result["rula"]["grand_score"], 1)
        self.assertEqual(result["rula"]["action_level"], 1)
        self.assertEqual(result["reba"]["reba_score"], 1)
        self.assertEqual(result["reba"]["risk"], "negligible")

    def test_bent_over_lift_is_high_risk(self):
        """Stooped lift: trunk 55, neck 25, arm 40, elbow 80, knees 35, 12 kg."""
        angles, _ = angles_for(trunk_deg=55.0, neck_deg=25.0, arm_deg=40.0,
                               elbow_deg=80.0, knee_deg=35.0)
        mods = Modifiers(load_kg=12.0, load_static_or_repeated=True, coupling="poor",
                         repeated_actions=True, legs_supported=True, legs_bilateral=True)
        result = score_angles(angles, mods)

        # Hand-checked against the worksheets:
        # RULA  A: upper arm 2, lower arm 1, wrist 1, twist 1 -> Table A 2; +1 muscle +3 force = 6
        #       B: neck 3, trunk 3, legs 1 -> Table B 4; +1 muscle +3 force = 8 -> clamps to 7
        #       Table C[6][7] = 7  -> action level 4
        self.assertEqual(result["rula"]["components"]["trunk"]["score"], 3)
        self.assertEqual(result["rula"]["components"]["neck"]["score"], 3)
        self.assertEqual(result["rula"]["group_a"]["force"], 3)
        self.assertEqual(result["rula"]["grand_score"], 7)
        self.assertEqual(result["rula"]["action_level"], 4)

        # REBA  A: neck 2, trunk 3, legs 1+1 = 2 -> Table A 5; force +2 = 7
        #       B: upper arm 2, lower arm 1, wrist 1 -> Table B 1; coupling +2 = 3
        #       Table C[7][3] = 7; activity +1 (repeated) = 8 -> high risk
        self.assertEqual(result["reba"]["components"]["legs"]["score"], 2)
        self.assertEqual(result["reba"]["group_a"]["score"], 7)
        self.assertEqual(result["reba"]["group_b"]["score"], 3)
        self.assertEqual(result["reba"]["activity"], 1)
        self.assertEqual(result["reba"]["reba_score"], 8)
        self.assertEqual(result["reba"]["risk"], "high")

    def test_overhead_work_penalises_the_shoulder(self):
        """RULA and REBA are meant to disagree here, and this pins that down.

        Arm 120 deg overhead, head tipped back, trunk upright, posture held.
        RULA is an upper-limb tool, so it lands at action level 4.  REBA is a
        whole-body tool driven mostly by group A (trunk/neck/legs), so an
        upright trunk keeps the total low - 2 from Table C plus 1 for the static
        hold.  If a future change makes these two converge, something is wrong.
        """
        angles, _ = angles_for(arm_deg=120.0, neck_deg=-20.0, elbow_deg=60.0)
        result = score_angles(angles, Modifiers(static_posture=True))
        self.assertEqual(result["rula"]["components"]["upper_arm"]["score"], 4)
        self.assertEqual(result["rula"]["components"]["neck"]["score"], 4)
        self.assertEqual(result["rula"]["grand_score"], 7)
        self.assertEqual(result["rula"]["action_level"], 4)

        self.assertEqual(result["reba"]["components"]["upper_arm"]["score"], 4)
        self.assertEqual(result["reba"]["components"]["neck"]["score"], 2)
        self.assertEqual(result["reba"]["group_b"]["score"], 4)
        self.assertEqual(result["reba"]["reba_score"], 3)

    def test_abduction_is_not_faked_by_sagittal_elevation(self):
        """An arm raised straight forward is flexion, not abduction."""
        angles, _ = angles_for(arm_deg=120.0)
        self.assertAlmostEqual(angles.left.upper_arm_abduction, 0.0, delta=2.0)
        self.assertFalse(angles.flags["left_arm_abducted"])

    def test_shoulder_hint_does_not_fire_when_bent_over(self):
        angles, _ = angles_for(trunk_deg=55.0, neck_deg=25.0)
        self.assertFalse(angles.flags["shoulder_raised_hint"])

    def test_insights_reference_the_measured_angles(self):
        angles, _ = angles_for(trunk_deg=50.0, neck_deg=30.0)
        result = score_angles(angles, Modifiers(load_kg=10.0))
        segments = {i["segment"] for i in result["insights"]}
        self.assertIn("trunk", segments)
        self.assertIn("neck", segments)
        self.assertIn("load", segments)
        trunk_insight = next(i for i in result["insights"] if i["segment"] == "trunk")
        self.assertTrue(trunk_insight["actions"])
        self.assertAlmostEqual(trunk_insight["angle"], 50.0, delta=2.0)
        self.assertIn(result["summary"]["rula_action_level"], (1, 2, 3, 4))

    def test_modifier_overrides_beat_detection(self):
        angles, _ = angles_for()
        angles.flags["trunk_twisted"] = True
        with_twist = score_angles(angles, Modifiers())
        without = score_angles(angles, Modifiers(trunk_twisted=False))
        self.assertEqual(with_twist["rula"]["components"]["trunk"]["score"], 2)
        self.assertEqual(without["rula"]["components"]["trunk"]["score"], 1)

    def test_worst_side_governs(self):
        angles, _ = angles_for(arm_deg=10.0)
        angles.right.upper_arm_flexion = 100.0   # right arm raised overhead
        result = score_angles(angles, Modifiers())
        self.assertEqual(result["rula"]["governing_side"], "right")
        self.assertGreaterEqual(
            result["rula"]["sides"]["right"], result["rula"]["sides"]["left"])

    def test_pinned_side_is_respected(self):
        angles, _ = angles_for(arm_deg=10.0)
        angles.right.upper_arm_flexion = 100.0
        result = score_angles(angles, Modifiers(assessed_side="left"))
        self.assertEqual(result["rula"]["governing_side"], "left")




# ---------------------------------------------------------------------------
# Pose backend adapter (the layer that hides the two MediaPipe APIs)
# ---------------------------------------------------------------------------

class TestPoseBackendAdapter(unittest.TestCase):

    class _TaskLM:
        def __init__(self, x, y, z, visibility=0.0, presence=0.0):
            self.x, self.y, self.z = x, y, z
            self.visibility, self.presence = visibility, presence

    def test_visibility_falls_back_to_presence(self):
        from ergonomics.pose_backend import _normalise
        lms = [self._TaskLM(0.1, 0.2, 0.3, visibility=0.0, presence=0.9) for _ in range(33)]
        out = _normalise(lms)
        self.assertEqual(len(out), 33)
        self.assertAlmostEqual(out[0].visibility, 0.9)

    def test_visibility_defaults_to_visible_when_both_are_empty(self):
        """A Tasks build that reports neither must not mark the whole pose unusable."""
        from ergonomics.pose_backend import _normalise
        lms = [self._TaskLM(0.1, 0.2, 0.3) for _ in range(33)]
        self.assertAlmostEqual(_normalise(lms)[0].visibility, 1.0)

    def test_visibility_is_kept_when_present(self):
        from ergonomics.pose_backend import _normalise
        lms = [self._TaskLM(0.1, 0.2, 0.3, visibility=0.7, presence=0.2) for _ in range(33)]
        self.assertAlmostEqual(_normalise(lms)[0].visibility, 0.7)

    def test_result_shape_matches_what_the_engine_expects(self):
        """A Tasks-style result must build a Frame exactly like a legacy one."""
        from ergonomics.pose_backend import PoseResult, _normalise
        source = standing_body(trunk_deg=30.0)
        image = _normalise([self._TaskLM(lm.x, lm.y, lm.z, presence=1.0)
                            for lm in source.pose_landmarks.landmark])
        world = _normalise([self._TaskLM(lm.x, lm.y, lm.z, presence=1.0)
                            for lm in source.pose_world_landmarks.landmark])
        frame = build_frame(PoseResult(image, world), 1000, 1000)
        self.assertIsNotNone(frame)
        self.assertTrue(frame.has_world)
        self.assertAlmostEqual(compute_angles(frame).trunk_flexion, 30.0, delta=1.5)

    def test_empty_result_means_no_pose(self):
        from ergonomics.pose_backend import PoseResult
        self.assertIsNone(build_frame(PoseResult(None), 640, 480))


if __name__ == "__main__":
    unittest.main(verbosity=2)
