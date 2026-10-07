"""Build-time smoke test: prove the detector really runs inside the image.

Checking that the model file exists is not enough - the container failure we hit
was MediaPipe itself refusing to run, with the file sitting right there. This
runs one real detection on a blank frame: "no body found" is the correct answer
and means the whole path works.
"""
import cv2
import numpy as np

from ergonomics import NoPoseDetected, analyse_image, backend_info, decode_image

info = backend_info()
print("backend:", info)
assert info.get("ready"), "pose model not ready: %s" % info

blank = cv2.imencode(".jpg", np.full((480, 320, 3), 60, np.uint8))[1].tobytes()
try:
    analyse_image(decode_image(blank), annotate=False)
    print("detector ran and found a body in a blank frame?! - unexpected, but it ran")
except NoPoseDetected:
    print("detector ran, no body in the blank frame - correct")
