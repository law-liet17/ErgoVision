# Pose-model benchmark (for the paper)

`benchmark.py` runs several pose models on your test photos, measures the
worksheet joint angles, and compares them with goniometer readings. It writes
one CSV that Minitab opens directly for the DOE / ANOVA. It is not part of the
app; the app keeps only the winning model.

## 1. Install (once)

```bash
pip install -r requirements.txt -r research/requirements.txt
python download_model.py
```

YOLOv8 weights (6.5 MB) download to `research/weights/` and the RTMPose ONNX
models to `~/.cache/rtmlib/` the first time they run.

## 2. Photos and the goniometer sheet

Put the test photos in one folder, then make a blank sheet for them:

```bash
python research/benchmark.py path/to/photos --template truth.csv
```

Fill in one row per photo, in degrees, and leave a cell **empty** for any angle
you did not measure:

| column | meaning |
|---|---|
| `photo` | file name in the folder |
| `camera_angle` | factor, e.g. `side`, `oblique`, `front` (or the angle in degrees) |
| `clothing` | factor, e.g. `fitted`, `loose`, `saree`, `apron` |
| `markers` | `yes` if the worker wore stickers, else `no` |
| `marker_colour` | `green`, `pink`, `yellow`, `orange` or `blue` (used by the `ergovision` row) |
| `trunk_flexion` | from vertical, + forward |
| `neck_flexion` | from the trunk line, + forward |
| `left/right_upper_arm_flexion` | from the trunk line pointing down, + forward |
| `left/right_elbow_flexion` | 0 = straight arm |
| `left/right_wrist_flexion` | 0 = straight wrist |
| `left/right_knee_flexion` | 0 = straight leg |

## 3. Run

```bash
python research/benchmark.py path/to/photos truth.csv -o results.csv
python research/benchmark.py path/to/photos truth.csv -m mediapipe,yolov8     # a subset
```

One row per photo × model × joint:

| column | values |
|---|---|
| `photo`, `model`, `joint` | `model` is `mediapipe`, `yolov8`, `rtmpose` or `ergovision` |
| `measured_angle`, `true_angle` | degrees; empty when missing |
| `error`, `abs_error` | measured − true, and its size; empty when either is missing |
| `joint_detected` | `yes`, `no` (keypoints below the model's confidence bar), or `not available` (the model has no such keypoint - YOLOv8 has no hand points, so no wrist bend) |
| `camera_angle`, `clothing`, `markers` | copied from the sheet, ready to use as factors |

## How the angles are measured

So that differences come from the models and not from the maths, `mediapipe`,
`yolov8` and `rtmpose` angles are all computed from each model's **2D image
keypoints with the same formulas** (sagittal plane, side-on photos). The
`ergovision` rows are the app's own output - MediaPipe with 3D angles, the
visibility check from multi-photo mode, and marker mode when `markers` is `yes`
- so the paper can also report what the product itself measures.

A keypoint counts as detected at confidence ≥ 0.5 (MediaPipe, YOLOv8, the app)
or ≥ 0.3 (RTMPose, whose scores run lower); change `MIN_SCORE` in the script to
test other bars.

## In Minitab

File › Open › `results.csv` (comma-delimited, first row = names). Empty cells
arrive as missing (`*`). For example, Stat › ANOVA › General Linear Model with
response `abs_error` and factors `model`, `camera_angle`, `clothing`, `markers`
(and `joint`), after subsetting out rows with `joint_detected` ≠ `yes`.
