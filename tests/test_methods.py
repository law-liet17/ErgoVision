"""Tests for showing the most urgent method first, with no combined score (feature 3).

Run with:  python tests/test_methods.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["ERGOVISION_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from ergonomics import Modifiers, compute_angles, methods, score_angles  # noqa: E402
from ergonomics.landmarks import build_frame  # noqa: E402
from ergonomics.tools import TOOLS, run_tool  # noqa: E402
from test_scoring import standing_body  # noqa: E402


def lab_result(**pose):
    modifiers = pose.pop("modifiers", Modifiers())
    return score_angles(compute_angles(build_frame(standing_body(**pose), 1000, 1000)), modifiers)


class TestOwnActionLevels(unittest.TestCase):
    def test_every_tool_describes_itself_in_its_own_terms(self):
        for tool_id in TOOLS:
            m = run_tool(tool_id, {})["method"]
            for key in ("name", "area", "score_text", "label", "action"):
                self.assertTrue(m[key], "%s has no %s" % (tool_id, key))
            self.assertIn(m["urgency"], range(5), tool_id)

    def test_rula_keeps_its_own_score_and_action_level(self):
        result = lab_result(trunk_deg=70, neck_deg=30, arm_deg=100, elbow_deg=10,
                            modifiers=Modifiers(load_kg=12, static_posture=True))
        rula = next(m for m in result["methods"] if m["id"] == "rula")
        self.assertEqual(rula["score_text"], "%d/7" % result["rula"]["grand_score"])
        self.assertEqual(rula["label"], "Action level %d" % result["rula"]["action_level"])
        self.assertEqual(rula["action"], result["rula"]["action"])
        self.assertEqual(rula["area"], "Upper limb (neck, shoulders, arms and wrists)")

    def test_wording_follows_each_methods_own_thresholds(self):
        cases = [("niosh", {"score": 3.4, "band": {"level": 4}}, "LI over 3"),
                 ("niosh", {"score": 0.9, "band": {"level": 1}}, "LI 0.7 to 1.0"),
                 ("strain_index", {"score": 9.0, "band": {"level": 3}}, "SI over 7"),
                 ("rosa", {"score": 5, "band": {"level": 2}}, "ROSA 5"),
                 ("biomech", {"score": 7000, "band": {"level": 4}}, "Over 6400 N")]
        for tool_id, result, label in cases:
            self.assertEqual(methods.describe(tool_id, result)["label"], label, tool_id)

    def test_body_areas_match_the_brief(self):
        self.assertEqual(methods.METHODS["reba"][1], "Whole body")
        self.assertIn("Lower back", methods.METHODS["niosh"][1])
        self.assertIn("Hand and wrist", methods.METHODS["strain_index"][1])


class TestMostUrgentFirst(unittest.TestCase):
    def test_ranked_by_urgency_not_by_raw_number(self):
        # A REBA of 9 is a bigger number than a RULA of 7, but RULA 7 is the more urgent result.
        rula = {"id": "rula", "score": 7, "urgency": 4}
        reba = {"id": "reba", "score": 9, "urgency": 3}
        self.assertEqual([m["id"] for m in methods.rank([reba, rula])], ["rula", "reba"])

    def test_ties_keep_the_order_given(self):
        a, b = {"id": "a", "urgency": 2}, {"id": "b", "urgency": 2}
        self.assertEqual([m["id"] for m in methods.rank([a, b])], ["a", "b"])

    def test_lab_lists_rula_reba_owas_with_the_most_urgent_first(self):
        result = lab_result(trunk_deg=70, neck_deg=30, arm_deg=100, elbow_deg=10,
                            modifiers=Modifiers(load_kg=12, static_posture=True))
        ids = [m["id"] for m in result["methods"]]
        self.assertEqual(sorted(ids), ["owas", "reba", "rula"])
        lead, second = result["methods"][:2]
        self.assertGreaterEqual(lead["urgency"], second["urgency"])
        self.assertEqual(ids[-1], "owas")   # OWAS never leads (leg code unreliable without feet)

    def test_no_combined_score_in_the_lab_result(self):
        result = lab_result(trunk_deg=30)
        for key in ("overall", "overall_level", "risk_level", "combined"):
            self.assertNotIn(key, result)


class TestDashboardPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import store
        cls.store = store
        store.init_db()

    def add(self, ws, tool_id, inputs):
        result = run_tool(tool_id, inputs)
        self.store.create_assessment({"workstation_id": ws, "tool": tool_id, "tool_name": tool_id.upper(),
                                      "inputs": inputs, "result": result})

    def test_sorted_by_priority_label_with_the_note(self):
        calm = self.store.create_workstation({"name": "Packing table"})["id"]
        urgent = self.store.create_workstation({"name": "Floor-level pick"})["id"]
        self.add(calm, "rosa", {})
        self.add(urgent, "rosa", {})
        self.add(urgent, "niosh", {"load_kg": 25, "lifts_per_min": 6, "v_origin_cm": 5, "h_origin_cm": 60})
        board = self.store.dashboard()
        order = [w["name"] for w in board["priority"]]
        self.assertLess(order.index("Floor-level pick"), order.index("Packing table"))
        top = board["priority"][0]["priority"]
        self.assertEqual(top["label"], methods.PRIORITY_LABELS[top["level"]])
        self.assertIn("NIOSH", top["led_by"])
        self.assertEqual(board["priority_note"],
                         "Priority label for ordering fixes only. It is not a combined risk score.")


if __name__ == "__main__":
    unittest.main()
