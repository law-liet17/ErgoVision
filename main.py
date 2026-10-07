"""Live ErgoVision viewer: webcam in, angles + RULA/REBA on screen.

    python main.py                 # default webcam
    python main.py --camera 1 --load 8 --static

Keys:  q quit   s save a snapshot   l/r pin the assessed side   a auto side
       space  freeze the frame

The scoring here is the same engine the API uses, so what you see live is what
the report will say.
"""

import argparse
import time

import cv2

from ergonomics import Modifiers, NoPoseDetected, analyse_image, backend_info


def parse_args():
    parser = argparse.ArgumentParser(description="ErgoVision live posture assessment")
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--load", type=float, default=0.0, help="hand load in kg")
    parser.add_argument("--coupling", default="good",
                        choices=["good", "fair", "poor", "unacceptable"])
    parser.add_argument("--static", action="store_true", help="posture held over 1 minute")
    parser.add_argument("--repeated", action="store_true", help="repeated more than 4x per minute")
    parser.add_argument("--sitting", action="store_true", help="seated task")
    parser.add_argument("--complexity", type=int, default=1, choices=[0, 1, 2],
                        help="MediaPipe model complexity (2 = most accurate, slowest)")
    parser.add_argument("--every", type=int, default=2,
                        help="score every Nth frame (1 = every frame)")
    return parser.parse_args()


def main():
    args = parse_args()
    modifiers = Modifiers(
        load_kg=args.load,
        coupling=args.coupling,
        static_posture=args.static,
        repeated_actions=args.repeated,
        sitting=True if args.sitting else None,
    )

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        raise SystemExit("Could not open camera %d" % args.camera)

    print(__doc__)
    print("pose backend:", backend_info())
    frame_no, last, frozen = 0, None, False
    fps_clock, fps = time.time(), 0.0

    while True:
        if not frozen:
            ok, frame = capture.read()
            if not ok:
                print("Lost the camera feed.")
                break
            frame_no += 1

            if frame_no % max(1, args.every) == 0:
                try:
                    last = analyse_image(
                        frame, modifiers=modifiers, annotate=True,
                        static=False, complexity=args.complexity,
                    )
                except NoPoseDetected:
                    last = None

        display = frame.copy()
        if last is not None:
            # analyse_image already drew the overlay onto its own copy; redraw
            # here so the live window keeps the latest camera frame underneath.
            rula_line = "RULA %d  (action level %d: %s)" % (
                last["rula"]["grand_score"], last["rula"]["action_level"],
                last["rula"]["action_name"])
            reba_line = "REBA %d  (%s risk)" % (
                last["reba"]["reba_score"], last["reba"]["risk"])
            angle_lines = [
                "trunk %5.1f   neck %5.1f" % (
                    last["angles"]["trunk_flexion"] or 0, last["angles"]["neck_flexion"] or 0),
                "arm   %5.1f   elbow %5.1f   wrist %5.1f" % (
                    (last["angles"][last["rula"]["governing_side"]]["upper_arm_flexion"] or 0),
                    (last["angles"][last["rula"]["governing_side"]]["elbow_flexion"] or 0),
                    (last["angles"][last["rula"]["governing_side"]]["wrist_flexion"] or 0)),
                "side  %s   view %s" % (
                    last["rula"]["governing_side"], last["view"]["view"]),
            ]
            colour = (60, 200, 250) if last["reba"]["risk_level"] >= 2 else (120, 220, 120)
            cv2.rectangle(display, (0, 0), (display.shape[1], 128), (18, 18, 24), -1)
            cv2.putText(display, rula_line, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
            cv2.putText(display, reba_line, (14, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
            for i, line in enumerate(angle_lines):
                cv2.putText(display, line, (14, 80 + i * 18), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (220, 220, 220), 1)
            top = last["insights"][0]["title"] if last["insights"] else "Posture looks acceptable"
            cv2.putText(display, "Top issue: " + top, (14, display.shape[0] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        else:
            cv2.putText(display, "No body detected", (14, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (80, 80, 240), 2)

        now = time.time()
        fps = 0.9 * fps + 0.1 / max(1e-6, now - fps_clock)
        fps_clock = now
        cv2.putText(display, "%.0f fps" % fps, (display.shape[1] - 90, display.shape[0] - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

        cv2.imshow("ErgoVision live", display)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" "):
            frozen = not frozen
        if key == ord("s"):
            name = "ergovision_%d.png" % int(time.time())
            cv2.imwrite(name, display)
            print("saved", name)
        if key in (ord("l"), ord("r"), ord("a")):
            modifiers.assessed_side = {"l": "left", "r": "right", "a": "auto"}[chr(key)]
            print("assessed side:", modifiers.assessed_side)

    capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
