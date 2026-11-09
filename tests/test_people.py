"""Tests for choosing the worker when several people are in the frame (feature 2).

Run with:  python tests/test_people.py
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ERGOVISION_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from ergonomics import MultiplePeople, analysis  # noqa: E402
from test_scoring import standing_body  # noqa: E402

BLANK = np.zeros((1000, 1000, 3), np.uint8)


def body(dx, trunk=0.0):
    """A synthetic worker shifted sideways in the image by `dx` (fraction of the width)."""
    results = standing_body(trunk_deg=trunk, elbow_deg=40)
    for lm in results.pose_landmarks.landmark:
        lm.x += dx
    return results


class FakeBackend:
    """Stands in for MediaPipe: returns the next prepared list of people per call."""

    def __init__(self, *scenes):
        self.scenes, self.calls = list(scenes), 0

    def detect_all(self, rgb):
        scene = self.scenes[min(self.calls, len(self.scenes) - 1)]
        self.calls += 1
        return scene


class FrameBackend(FakeBackend):
    """Like a real detector, the same frame always gives the same people: the
    test video encodes its frame number in the brightness (see FRAME_STEP)."""

    def detect_all(self, rgb):
        return self.scenes[min(int(round(rgb.mean() / FRAME_STEP)), len(self.scenes) - 1)]


FRAME_STEP = 12


def using(backend):
    return mock.patch.object(analysis, "get_backend", return_value=backend)


class TestDetection(unittest.TestCase):
    def test_one_person_is_returned_as_before(self):
        with using(FakeBackend([body(0.0)])):
            frame = analysis.detect_frame(BLANK)
        self.assertEqual(frame.people, 1)

    def test_several_people_ask_for_a_choice_numbered_left_to_right(self):
        # The detector lists the right-hand person first; numbering must not follow that.
        with using(FakeBackend([body(0.25), body(-0.25)])):
            with self.assertRaises(MultiplePeople) as caught:
                analysis.detect_frame(BLANK)
        people = caught.exception.people
        self.assertEqual([p["number"] for p in people], [1, 2])
        self.assertLess(people[0]["box"][0], people[1]["box"][0])
        self.assertTrue(caught.exception.preview.startswith("data:image/jpeg;base64,"))

    def test_the_chosen_box_selects_only_that_person(self):
        with using(FakeBackend([body(0.25, trunk=0), body(-0.25, trunk=45)])):
            with self.assertRaises(MultiplePeople) as caught:
                analysis.detect_frame(BLANK)
        left, right = (p["box"] for p in caught.exception.people)
        for box, trunk in ((left, 45), (right, 0)):
            with using(FakeBackend([body(0.25, trunk=0), body(-0.25, trunk=45)])):
                result = analysis.analyse_image(BLANK, annotate=False, person=box)
            self.assertAlmostEqual(result["angles"]["trunk_flexion"], trunk, delta=1.5)
            self.assertEqual(result["person"]["people_found"], 2)

    def test_a_double_detection_of_one_body_is_one_person(self):
        with using(FakeBackend([body(0.0), body(0.005)])):
            frame = analysis.detect_frame(BLANK)
        self.assertEqual(frame.people, 1)


class TestTracking(unittest.TestCase):
    def frames(self, *scene):
        with using(FakeBackend(list(scene))):
            return analysis.detect_people(BLANK)

    def test_follows_the_worker_when_the_detector_reorders_people(self):
        worker = self.frames(body(-0.2, trunk=30))[0].box
        for step in range(1, 6):   # the worker walks right; a bystander stands still
            people = self.frames(body(0.3), body(-0.2 + 0.04 * step, trunk=30))
            chosen = analysis.pick_person(people, worker)
            self.assertEqual(chosen.box, self.frames(body(-0.2 + 0.04 * step, trunk=30))[0].box, step)
            worker = chosen.box

    def test_returns_nobody_when_the_worker_has_left(self):
        worker = self.frames(body(-0.3))[0].box
        self.assertIsNone(analysis.pick_person(self.frames(body(0.3)), worker))


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.app_module = app_module
        cls.client = app_module.app.test_client()

    def post(self, path, files, **form):
        data = {k: (io.BytesIO(v), name) for k, (name, v) in files.items()}
        data.update(form)
        return self.client.post(path, data=data, content_type="multipart/form-data")

    def test_photo_with_two_people_asks_which_worker(self):
        jpg = cv2.imencode(".jpg", BLANK)[1].tobytes()
        with using(FakeBackend([body(0.25), body(-0.25, trunk=45)])):
            first = self.post("/analyze", {"image": ("two.jpg", jpg)})
        self.assertEqual(first.status_code, 409)
        payload = first.get_json()
        self.assertEqual(payload["code"], "choose_person")
        self.assertEqual(len(payload["people"]), 2)
        with using(FakeBackend([body(0.25), body(-0.25, trunk=45)])):
            second = self.post("/analyze", {"image": ("two.jpg", jpg)},
                               person=json.dumps(payload["people"][0]["box"]))
        self.assertEqual(second.status_code, 200)
        self.assertAlmostEqual(second.get_json()["angles"]["trunk_flexion"], 45, delta=1.5)

    def test_bad_person_box_is_rejected(self):
        jpg = cv2.imencode(".jpg", BLANK)[1].tobytes()
        response = self.post("/analyze", {"image": ("x.jpg", jpg)}, person="[0.5, 0.5, 0.2, 0.9]")
        self.assertEqual(response.status_code, 400)

    def test_video_follows_the_chosen_worker(self):
        path = os.path.join(tempfile.mkdtemp(), "clip.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 320))
        for i in range(20):
            writer.write(np.full((320, 320, 3), i * FRAME_STEP, np.uint8))
        writer.release()
        with open(path, "rb") as fh:
            clip = fh.read()

        # Worker (bent 40 deg) walks right past a bystander (upright); the detector's order flips.
        scenes = [[body(-0.25 + 0.02 * i, trunk=40), body(0.3)][::(-1) ** i] for i in range(20)]
        ready = mock.patch.object(self.app_module, "backend_info", return_value={"ready": True})

        with ready, using(FrameBackend(*scenes)):
            asked = self.post("/analyze-video", {"video": ("clip.mp4", clip)}, sample_ms="100")
        self.assertEqual(asked.status_code, 409)
        self.assertEqual(asked.get_json()["time_s"], 0.0)
        worker = next(p for p in asked.get_json()["people"] if p["box"][0] < 0.4)

        with ready, using(FrameBackend(*scenes)):
            scored = self.post("/analyze-video", {"video": ("clip.mp4", clip)}, sample_ms="100",
                               person=json.dumps(worker["box"]))
        self.assertEqual(scored.status_code, 200, scored.get_json())
        trunks = [f["trunk"] for f in scored.get_json()["timeline"]]
        self.assertGreater(len(trunks), 5)
        for trunk in trunks:
            self.assertAlmostEqual(trunk, 40, delta=1.5)


if __name__ == "__main__":
    unittest.main()
