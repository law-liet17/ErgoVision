"""Pose detection backend - works with either MediaPipe generation.

MediaPipe ships two APIs and which one you get depends on the wheel:

* **legacy solutions** - ``mediapipe.solutions.pose.Pose``, model weights bundled
  inside the package, nothing to download.
* **Tasks API** - ``mediapipe.tasks.python.vision.PoseLandmarker``, needs a
  ``pose_landmarker_*.task`` model file on disk.  Recent wheels (0.10.3x and
  later on Windows) ship *only* this one, with no ``mediapipe.solutions`` at all.

Both are wrapped so the rest of the engine only ever sees an object with
``.pose_landmarks.landmark`` and ``.pose_world_landmarks.landmark``.

Model file resolution order for the Tasks backend:
  1. ``$ERGOVISION_POSE_MODEL``
  2. ``models/pose_landmarker_*.task`` next to the project
  3. ``~/.cache/ergovision/pose_landmarker_*.task``
Run ``python download_model.py`` once to fetch it.
"""

import os
import threading

MODEL_NAMES = (
    "pose_landmarker_full.task",
    "pose_landmarker_heavy.task",
    "pose_landmarker_lite.task",
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIRS = (
    os.path.join(PROJECT_ROOT, "models"),
    os.path.join(os.path.expanduser("~"), ".cache", "ergovision"),
)

MODEL_URLS = {
    "pose_landmarker_lite.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    "pose_landmarker_full.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_full/float16/1/pose_landmarker_full.task",
    "pose_landmarker_heavy.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task",
}

_LOCK = threading.Lock()
_CACHE = {}


class PoseBackendUnavailable(RuntimeError):
    """Neither MediaPipe API could be initialised."""


# ---------------------------------------------------------------------------
# result adapter
# ---------------------------------------------------------------------------

class _LandmarkList:
    __slots__ = ("landmark",)

    def __init__(self, landmarks):
        self.landmark = landmarks


class PoseResult:
    """What the engine consumes: image landmarks plus optional world landmarks."""

    __slots__ = ("pose_landmarks", "pose_world_landmarks")

    def __init__(self, image_landmarks, world_landmarks=None):
        self.pose_landmarks = _LandmarkList(image_landmarks) if image_landmarks else None
        self.pose_world_landmarks = _LandmarkList(world_landmarks) if world_landmarks else None


class _Point:
    """A landmark with a usable ``visibility`` whichever API produced it."""

    __slots__ = ("x", "y", "z", "visibility")

    def __init__(self, x, y, z, visibility):
        self.x, self.y, self.z, self.visibility = x, y, z, visibility


def _normalise(landmarks):
    """Copy Tasks landmarks and repair the visibility field.

    Some Tasks builds return 0.0 for every ``visibility``; ``presence`` is then
    the usable signal, and if that is empty too we assume the landmark is
    visible rather than silently marking the whole pose unreliable.
    """
    vis = [float(getattr(lm, "visibility", 0.0) or 0.0) for lm in landmarks]
    if max(vis, default=0.0) <= 0.0:
        vis = [float(getattr(lm, "presence", 0.0) or 0.0) for lm in landmarks]
    if max(vis, default=0.0) <= 0.0:
        vis = [1.0] * len(landmarks)
    return [_Point(lm.x, lm.y, lm.z, v) for lm, v in zip(landmarks, vis)]


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------

def _legacy_available():
    try:
        import mediapipe as mp
        return hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    except Exception:
        return False


def find_model(name=None):
    """Locate a ``.task`` model file, or return ``None``."""
    explicit = name or os.environ.get("ERGOVISION_POSE_MODEL")
    if explicit and os.path.isfile(explicit):
        return explicit
    for directory in MODEL_DIRS:
        for candidate in MODEL_NAMES:
            path = os.path.join(directory, candidate)
            if os.path.isfile(path):
                return path
    return None


class _LegacyBackend:
    name = "mediapipe.solutions.pose"

    def __init__(self, static, complexity):
        import mediapipe as mp
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=static,
            model_complexity=complexity,
            smooth_landmarks=not static,
            enable_segmentation=False,
            min_detection_confidence=0.5,
        )

    def detect(self, rgb):
        out = self._pose.process(rgb)
        if not out.pose_landmarks:
            return PoseResult(None)
        world = getattr(out, "pose_world_landmarks", None)
        return PoseResult(
            list(out.pose_landmarks.landmark),
            list(world.landmark) if world else None,
        )


class _TasksBackend:
    name = "mediapipe.tasks PoseLandmarker"

    def __init__(self, static, complexity, model_path=None):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        path = find_model(model_path)
        if path is None:
            raise PoseBackendUnavailable(
                "This MediaPipe build has no legacy solutions API, so a pose model "
                "file is required and none was found.\n"
                "Fix it with:  python download_model.py\n"
                "or set ERGOVISION_POSE_MODEL to a pose_landmarker_*.task file."
            )
        self._mp = mp
        self.model_path = path
        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            output_segmentation_masks=False,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def detect(self, rgb):
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        out = self._landmarker.detect(image)
        if not out.pose_landmarks:
            return PoseResult(None)
        world = out.pose_world_landmarks[0] if out.pose_world_landmarks else None
        return PoseResult(
            _normalise(out.pose_landmarks[0]),
            _normalise(world) if world else None,
        )


def get_backend(static=True, complexity=1, model_path=None):
    """Return a cached backend instance (creating one is slow)."""
    key = ("legacy" if _legacy_available() else "tasks", bool(static), int(complexity))
    with _LOCK:
        if key not in _CACHE:
            if key[0] == "legacy":
                _CACHE[key] = _LegacyBackend(static, complexity)
            else:
                _CACHE[key] = _TasksBackend(static, complexity, model_path)
        return _CACHE[key]


def backend_info():
    """What the engine would use right now, for /health and error messages."""
    if _legacy_available():
        return {"backend": "mediapipe.solutions.pose", "model": "bundled", "ready": True}
    model = find_model()
    return {
        "backend": "mediapipe.tasks PoseLandmarker",
        "model": model,
        "ready": model is not None,
        "hint": None if model else "run: python download_model.py",
    }
