"""Tests for the non-vision assessment tools.

Run with:  python tests/test_tools.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ergonomics.tools import TOOLS, catalogue, run_tool  # noqa: E402
from ergonomics.tools import art, biomech, fit, kim, niosh, owas, rapp, rosa, strain_index  # noqa: E402


class TestNiosh(unittest.TestCase):

    def test_multipliers(self):
        self.assertAlmostEqual(niosh.hm(25), 1.0)
        self.assertAlmostEqual(niosh.hm(50), 0.5)
        self.assertEqual(niosh.hm(64), 0.0)
        self.assertAlmostEqual(niosh.vm(75), 1.0)
        self.assertAlmostEqual(niosh.vm(0), 0.775)
        self.assertAlmostEqual(niosh.dm(25), 1.0)
        self.assertAlmostEqual(niosh.dm(50), 0.91)
        self.assertAlmostEqual(niosh.am(90), 0.712)
        self.assertEqual(niosh.am(136), 0.0)

    def test_frequency_table(self):
        self.assertAlmostEqual(niosh.fm(0.2, "1h", 50), 1.00)
        self.assertAlmostEqual(niosh.fm(1, "8h", 50), 0.75)
        self.assertAlmostEqual(niosh.fm(10, "8h", 50), 0.0)      # V < 75 cut-off
        self.assertAlmostEqual(niosh.fm(10, "8h", 100), 0.13)
        self.assertAlmostEqual(niosh.fm(9, "8h", 100), 0.15)
        self.assertAlmostEqual(niosh.fm(15, "1h", 100), 0.28)
        self.assertAlmostEqual(niosh.fm(2.5, "2h", 50), 0.79)    # 2.5 rounds up to 3

    def test_coupling_table(self):
        self.assertAlmostEqual(niosh.cm("fair", 50), 0.95)
        self.assertAlmostEqual(niosh.cm("fair", 80), 1.00)
        self.assertAlmostEqual(niosh.cm("poor", 80), 0.90)

    def test_hand_worked_example(self):
        """10 kg, H 30, V 75, no travel, no twist, 1 lift/min for 8 h, good coupling."""
        r = niosh.run({"load_kg": 10, "h_origin_cm": 30, "v_origin_cm": 75, "h_dest_cm": 30, "v_dest_cm": 75,
                       "lifts_per_min": 1, "duration": "8h", "coupling": "good"})
        # RWL = 23 x (25/30) x 1 x 1 x 1 x 0.75 x 1 = 14.375
        self.assertAlmostEqual(r["rwl"], 14.38, places=2)
        self.assertAlmostEqual(r["score"], 0.70, places=2)
        self.assertEqual(r["band"]["label"], "low")

    def test_destination_can_govern(self):
        r = niosh.run({"load_kg": 12, "h_origin_cm": 30, "v_origin_cm": 75, "h_dest_cm": 60, "v_dest_cm": 150,
                       "lifts_per_min": 1, "duration": "8h", "coupling": "good"})
        self.assertEqual(r["governing"], "destination")
        self.assertGreater(r["score"], 1.0)

    def test_composite_index(self):
        tasks = [
            {"name": "a", "load_kg": 10, "h_origin_cm": 30, "v_origin_cm": 75, "lifts_per_min": 1, "coupling": "good"},
            {"name": "b", "load_kg": 8, "h_origin_cm": 40, "v_origin_cm": 100, "lifts_per_min": 2, "coupling": "good"},
        ]
        r = niosh.composite(tasks, "8h")
        singles = [niosh.run(dict(t, h_dest_cm=t["h_origin_cm"], v_dest_cm=t["v_origin_cm"], duration="8h"))["score"] for t in tasks]
        self.assertGreaterEqual(r["score"], max(singles))     # CLI is never below the worst single task
        self.assertEqual(len(r["steps"]), 2)


class TestStrainIndex(unittest.TestCase):

    def test_worked_example(self):
        r = strain_index.run({"intensity": "hard", "duration_pct": 40, "efforts_per_min": 12,
                              "posture": "fair", "speed": "fair", "hours_per_day": 8})
        self.assertAlmostEqual(r["score"], 6 * 1.5 * 1.5 * 1.5 * 1.0 * 1.0, places=2)
        self.assertEqual(r["band"]["label"], "very high")

    def test_minimum(self):
        r = strain_index.run({"intensity": "light", "duration_pct": 5, "efforts_per_min": 2,
                              "posture": "very_good", "speed": "slow", "hours_per_day": 0.5})
        self.assertAlmostEqual(r["score"], 0.06, places=2)
        self.assertEqual(r["band"]["level"], 0)

    def test_band_edges(self):
        self.assertEqual(strain_index.si_level(3.0), 1)
        self.assertEqual(strain_index.si_level(3.1), 2)
        self.assertEqual(strain_index.si_level(7.0), 2)
        self.assertEqual(strain_index.si_level(7.1), 3)


class TestRosa(unittest.TestCase):

    def test_ideal_workstation(self):
        r = rosa.run({"chair_duration": "1to4h", "monitor_duration": "1to4h", "phone_duration": "1to4h",
                      "mouse_duration": "1to4h", "keyboard_duration": "1to4h"})
        self.assertEqual(r["sections"]["chair"], 2)
        self.assertEqual(r["score"], 2)
        self.assertEqual(r["band"]["level"], 0)

    def test_table_spot_values(self):
        self.assertEqual(rosa.TABLE_A[9][6], 9)
        self.assertEqual(rosa.TABLE_A[5][2], 4)
        self.assertEqual(rosa.TABLE_B[3][7], 8)
        self.assertEqual(rosa.TABLE_C[7][7], 9)

    def test_bad_chair_drives_score(self):
        r = rosa.run({"chair_height": 3, "no_room_under_desk": True, "height_not_adjustable": True,
                      "seat_pan": 2, "pan_not_adjustable": True, "armrest": 2, "armrest_hard": True,
                      "armrest_too_wide": True, "armrest_not_adjustable": True, "backrest": 2,
                      "surface_too_high": True, "backrest_not_adjustable": True, "chair_duration": "gt4h"})
        self.assertEqual(r["sections"]["chair"], 10)
        self.assertEqual(r["score"], 10)
        self.assertEqual(r["band"]["label"], "very high")

    def test_duration_can_lower(self):
        short = rosa.run({"monitor": 3, "monitor_duration": "lt1h", "chair_duration": "lt1h"})
        long_ = rosa.run({"monitor": 3, "monitor_duration": "gt4h", "chair_duration": "lt1h"})
        self.assertLess(short["sections"]["monitor"], long_["sections"]["monitor"])


class TestOwas(unittest.TestCase):

    def test_lookup(self):
        self.assertEqual(owas.lookup(1, 1, 1, 1), 1)
        self.assertEqual(owas.lookup(2, 3, 7, 3), 4)
        self.assertEqual(owas.lookup(4, 3, 4, 1), 4)
        self.assertEqual(owas.lookup(3, 2, 3, 3), 2)
        self.assertEqual(owas.lookup(1, 3, 4, 3), 3)

    def test_table_complete(self):
        self.assertEqual(len(owas.TABLE), 12)
        for legs in owas.TABLE.values():
            self.assertEqual(len(legs), 7)
            self.assertTrue(all(len(l) == 3 for l in legs))

    def test_from_angles(self):
        code = owas.from_angles({"trunk_flexion": 45, "trunk_twist": 5, "left": {"upper_arm_flexion": 20},
                                 "right": {"upper_arm_flexion": 100}, "left_knee_flexion": 40, "right_knee_flexion": 40},
                                {}, load_kg=15)
        self.assertEqual(code, {"back": 2, "arms": 2, "legs": 4, "load": 2})
        code = owas.from_angles({"trunk_flexion": 5, "left": {}, "right": {}, "left_knee_flexion": 0, "right_knee_flexion": 0},
                                {"probably_sitting": True}, 0)
        self.assertEqual(code["legs"], 1)
        self.assertEqual(code["back"], 1)

    def test_run(self):
        r = owas.run({"back": 2, "arms": 3, "legs": 4, "load": 3})
        self.assertEqual(r["score"], 4)
        self.assertEqual(r["band"]["level"], 4)
        self.assertEqual(r["code"], "2343")


class TestArt(unittest.TestCase):

    def test_zero_task(self):
        r = art.run({"arm_movements": "infrequent", "repetition": "le10", "force_level": "light", "head": "neutral",
                     "back": "neutral", "arm": "neutral", "wrist": "neutral", "grip": "power", "breaks": "regular",
                     "pace": "self", "other": "none", "duration": "4to8h"})
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["band"]["level"], 0)

    def test_duration_multiplier(self):
        base = {"arm_movements": "very_frequent", "repetition": "gt20", "force_level": "strong", "force_time": "most"}
        full = art.run(dict(base, duration="4to8h"))
        half = art.run(dict(base, duration="lt2h"))
        self.assertAlmostEqual(half["score"], full["score"] * 0.5)
        self.assertEqual(full["task_score"], 6 + 6 + 8 + 1)   # wrist defaults to bent_some (1)
        self.assertEqual(full["band"]["label"], "medium")      # 21 is the top of the medium band
        self.assertGreaterEqual(art.run(dict(base, duration="gt8h"))["band"]["level"], 3)   # 22+ is HSE's high band


class TestRapp(unittest.TestCase):

    def test_all_green(self):
        r = rapp.run({"equipment": "small_trolley", "load_kg": 40, "pattern": "good"})
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["band"]["level"], 0)

    def test_red_factor_forces_high(self):
        r = rapp.run({"equipment": "small_trolley", "load_kg": 40, "pattern": "good", "posture": "poor"})
        self.assertEqual(r["worst_colour"], "red")
        self.assertEqual(r["band"]["label"], "high")

    def test_purple_load(self):
        r = rapp.run({"equipment": "small_trolley", "load_kg": 500})
        self.assertEqual(r["band"]["level"], 4)


class TestKim(unittest.TestCase):

    def test_worked_example(self):
        r = kim.run({"activity": "lifting", "quantity": 100, "load_kg": 15, "sex": "male",
                     "posture": "slight_bend", "conditions": "good"})
        self.assertEqual(r["score"], 4 * (2 + 2 + 0))
        self.assertEqual(r["band"]["label"], "medium")

    def test_female_reference_is_stricter(self):
        m = kim.load_rating(12, "male")
        f = kim.load_rating(12, "female")
        self.assertGreater(f, m)

    def test_time_rating(self):
        self.assertEqual(kim.time_rating("lifting", 5), 1)
        self.assertEqual(kim.time_rating("lifting", 1000), 10)
        self.assertEqual(kim.time_rating("carrying", 5000), 6)


class TestBiomech(unittest.TestCase):

    def test_upright_unloaded_is_body_weight_only(self):
        r = biomech.run({"body_mass_kg": 75, "stature_cm": 175, "load_kg": 0, "trunk_flexion_deg": 0,
                         "upper_arm_flexion_deg": 0, "elbow_flexion_deg": 0})
        self.assertLess(r["l5s1"]["compression_n"], 600)
        self.assertEqual(r["band"]["level"], 0)

    def test_stooped_lift_exceeds_action_limit(self):
        r = biomech.run({"body_mass_kg": 80, "stature_cm": 178, "load_kg": 20, "trunk_flexion_deg": 80,
                         "upper_arm_flexion_deg": 30, "elbow_flexion_deg": 10})
        self.assertGreater(r["l5s1"]["compression_n"], biomech.ACTION_LIMIT_N)
        self.assertGreaterEqual(r["band"]["level"], 3)

    def test_monotonic_in_load_and_flexion(self):
        base = {"body_mass_kg": 75, "stature_cm": 175, "upper_arm_flexion_deg": 20, "elbow_flexion_deg": 20}
        c1 = biomech.run(dict(base, load_kg=5, trunk_flexion_deg=20))["l5s1"]["compression_n"]
        c2 = biomech.run(dict(base, load_kg=15, trunk_flexion_deg=20))["l5s1"]["compression_n"]
        c3 = biomech.run(dict(base, load_kg=15, trunk_flexion_deg=60))["l5s1"]["compression_n"]
        self.assertLess(c1, c2)
        self.assertLess(c2, c3)

    def test_hand_override(self):
        base = {"body_mass_kg": 75, "stature_cm": 175, "load_kg": 15, "trunk_flexion_deg": 20}
        near = biomech.run(dict(base, hand_horizontal_m=0.25))["l5s1"]["compression_n"]
        far = biomech.run(dict(base, hand_horizontal_m=0.60))["l5s1"]["compression_n"]
        self.assertLess(near, far)


class TestFit(unittest.TestCase):

    def test_landmarks_from_stature(self):
        lm = fit.landmarks(175)
        self.assertAlmostEqual(lm["elbow"], 110.2, places=1)
        self.assertAlmostEqual(lm["shoulder"], 143.15, delta=0.1)

    def test_recommended_band_and_mismatch(self):
        r = fit.run({"stature_cm": 175, "work_type": "light", "surface_height_cm": 120})
        self.assertEqual(r["recommended"]["work_height"], [100, 105])
        self.assertGreaterEqual(r["band"]["level"], 2)
        ok = fit.run({"stature_cm": 175, "work_type": "light", "surface_height_cm": 103})
        self.assertEqual(ok["band"]["level"], 0)

    def test_percentile_fallback(self):
        r = fit.run({"sex": "female", "percentile": 5})
        self.assertEqual(r["stature_cm"], 151)
        self.assertEqual(r["score"], 0)     # nothing measured, nothing mismatched


class TestRegistry(unittest.TestCase):

    def test_catalogue_and_dispatch(self):
        c = catalogue()
        ids = {t["id"] for t in c["tools"]}
        self.assertTrue({"niosh", "strain_index", "rosa", "owas", "art", "rapp", "kim", "biomech", "fit", "rula", "reba"} <= ids)
        for tid in TOOLS:
            r = run_tool(tid, {})
            self.assertIn("band", r)
            self.assertIn(r["band"]["level"], range(5))
            self.assertTrue(r["insights"])
            self.assertTrue(r["breakdown"])
        with self.assertRaises(KeyError):
            run_tool("nope", {})

    def test_schemas_have_unique_keys(self):
        for tid, mod in TOOLS.items():
            keys = [f["key"] for g in mod.SCHEMA["groups"] for f in g["fields"]]
            self.assertEqual(len(keys), len(set(keys)), tid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
