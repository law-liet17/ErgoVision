"""ErgoVision ergonomics engine.

Pose landmarks in, RULA/REBA scores and workspace recommendations out.

    from ergonomics import Modifiers, analyse_image, decode_image

    result = analyse_image(decode_image(open("worker.jpg", "rb").read()),
                           Modifiers(load_kg=8, static_posture=True))
    print(result["rula"]["grand_score"], result["reba"]["reba_score"])

Modules:
    geometry   - vector maths
    pose_backend - MediaPipe legacy/Tasks detection, whichever is installed
    landmarks  - MediaPipe extraction, coordinate spaces, view detection
    angles     - landmarks -> worksheet angles (the tricky part)
    rula       - RULA tables and scoring
    reba       - REBA tables and scoring
    insights   - scores -> workspace recommendations
    analysis   - the end-to-end pipeline and image overlay
"""

from .analysis import (
    NoPoseDetected,
    analyse_image,
    angles_from_dict,
    decode_image,
    score_angles,
)
from .angles import PostureAngles, compute_angles
from .pose_backend import PoseBackendUnavailable, backend_info
from .schema import Modifiers

__all__ = [
    "Modifiers",
    "PoseBackendUnavailable",
    "backend_info",
    "PostureAngles",
    "NoPoseDetected",
    "analyse_image",
    "angles_from_dict",
    "compute_angles",
    "decode_image",
    "score_angles",
]

__version__ = "0.2.0"
