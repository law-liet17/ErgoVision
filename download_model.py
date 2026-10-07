"""Fetch the MediaPipe pose model that the Tasks API needs.

    python download_model.py                # full model (recommended, ~9 MB)
    python download_model.py --variant lite # smallest/fastest (~3 MB)
    python download_model.py --variant heavy # most accurate, slowest (~29 MB)

Only needed when the installed MediaPipe has no legacy ``mediapipe.solutions``
API - which is the case for recent Windows wheels.  Check with:

    python -c "from ergonomics import backend_info; print(backend_info())"

The file is written to ./models/ and picked up automatically.
"""

import argparse
import os
import sys
import urllib.request

from ergonomics.pose_backend import MODEL_URLS, PROJECT_ROOT, backend_info


def human(n):
    return "%.1f MB" % (n / 1024 / 1024)


def main():
    parser = argparse.ArgumentParser(description="Download a MediaPipe pose model")
    parser.add_argument("--variant", default="full", choices=["lite", "full", "heavy"])
    parser.add_argument("--dest", default=os.path.join(PROJECT_ROOT, "models"))
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    name = "pose_landmarker_%s.task" % args.variant
    url = MODEL_URLS[name]
    target = os.path.join(args.dest, name)

    if os.path.isfile(target):
        print("Already present:", target)
        print("Backend:", backend_info())
        return 0

    print("About to download:")
    print("  from", url)
    print("  to  ", target)
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 1

    os.makedirs(args.dest, exist_ok=True)
    tmp = target + ".part"

    def progress(blocks, block_size, total):
        if total > 0:
            done = min(blocks * block_size, total)
            sys.stdout.write("\r  %s / %s" % (human(done), human(total)))
            sys.stdout.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=progress)
    os.replace(tmp, target)
    print("\nSaved", target, "(%s)" % human(os.path.getsize(target)))
    print("Backend:", backend_info())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
