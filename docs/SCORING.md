# From pose landmarks to RULA and REBA

This is the part that is easy to get wrong: the charts are drawn for a human
observer with a goniometer standing beside the worker, and a pose model gives you
33 points in a picture. The gap between those two is all in this document.

Code: [`ergonomics/angles.py`](../ergonomics/angles.py) does the measuring,
[`ergonomics/rula.py`](../ergonomics/rula.py) and
[`ergonomics/reba.py`](../ergonomics/reba.py) do the chart lookups.

---

## 1. The three rules that fix most mistakes

**Rule 1 - know your reference line for each joint.** Not everything is measured
from vertical:

| Joint | Measured against | Why |
|---|---|---|
| Trunk | **gravity** (vertical) | The worksheet draws the trunk angle from an upright standing line. |
| Neck | **the trunk axis** | The worksheet draws the neck angle from the trunk line, so bending the whole upper body must not read as neck flexion. |
| Upper arm | **the trunk axis, pointing down** | Same reason: an arm hanging relaxed is 0 deg whether the worker is upright or stooped. |
| Lower arm | **the upper arm** | It is the elbow's own flexion. |
| Wrist | **the forearm** | |
| Knee | **the thigh** | |

Getting this wrong is the most common bug in home-made RULA tools: measuring the
neck or the arm against vertical makes a stooped worker look like they also have
a flexed neck and an extended shoulder, and the same posture then scores twice.

**Rule 2 - `0 deg` means different things for different rows.** For the trunk,
neck, upper arm and wrist, 0 deg is the *neutral* posture (straight/upright). For
the lower arm and the knee, the chart's angle is **flexion measured from full
extension**, so a straight arm is 0 deg and a right angle is 90 deg. If you feed
the interior joint angle (shoulder-elbow-wrist = 170 deg for a nearly straight
arm) straight into the 60-100 deg band you get the answer backwards.

```
elbow_flexion = 180 - interior_angle(shoulder, elbow, wrist)
knee_flexion  = 180 - interior_angle(hip, knee, ankle)
```

**Rule 3 - direction matters, so never use `abs()` too early.** 20 deg of trunk
extension and 20 deg of trunk flexion are different rows; neck extension is the
*worst* neck band in RULA (4) while 5 deg of neck flexion is the best (1). The
engine keeps a signed angle (`+` = forward flexion, `-` = extension) and only
takes the magnitude where the chart itself is symmetric - the wrist, where
flexion and extension score the same.

---

## 2. Coordinate spaces

MediaPipe gives two sets of landmarks and both are used:

* **Image landmarks** - `x`, `y` normalised to `[0, 1]`. `x` is normalised by the
  image **width** and `y` by the **height**, so on a 1920x1080 photo one unit of
  `x` is 1.78x longer than one unit of `y`. Using the raw values distorts every
  angle. The engine multiplies by width and height first
  (`landmarks.Frame.pixels`).
* **World landmarks** (`pose_world_landmarks`) - metres, origin at the hip
  centre, isotropic. These are used as the primary space because they allow a
  real sagittal/frontal split, which is what twist, side bending and abduction
  need. Depth from a single camera is the least reliable channel, so anything
  derived only from depth is treated as a flag to confirm, not a measurement.

### The body frame

Everything is built from three axes derived from the body itself, so the result
does not depend on where the camera happens to be:

```
trunk_up = normalise(shoulder_mid - hip_mid)          # the person's own "up"
lateral  = normalise(right_shoulder - left_shoulder)  # their left -> right, made perpendicular to trunk_up
forward  = the nose direction, made perpendicular to both  # anterior
```

`gravity up` is the image's vertical `(0, -1, 0)` (y grows downward in image
space). That assumes the camera is held upright, which is also the assumption a
human observer makes when they judge "the trunk is bent 45 degrees".

Two projections are then used everywhere:

```python
signed_angle(v, ref, pos)        # angle of v inside the ref/pos plane, -180..180
out_of_plane_angle(v, normal)    # how far v leaves that plane,          -90..90
```

Sagittal measurements (flexion/extension) are `signed_angle` in the
`(up, forward)` plane. Frontal measurements (abduction, side bending) are
`out_of_plane_angle` about the lateral axis. Using a signed in-plane angle for
abduction is a trap: as soon as the arm passes horizontal the reference axis
reverses and `atan2` reports ~180 deg of "abduction" for a purely forward raise.
That bug is pinned by `test_abduction_is_not_faked_by_sagittal_elevation`.

---

## 3. Every worksheet row, and where its number comes from

### RULA group A (arm and wrist)

| Step | Chart bands | Engine |
|---|---|---|
| 1. Upper arm | 20 ext-20 flex = 1, >20 ext or 20-45 = 2, 45-90 = 3, >90 = 4; **+1** shoulder raised, **+1** abducted, **-1** arm supported | `signed_angle(elbow - shoulder, trunk_down, forward)`; abduction from `out_of_plane_angle`; raised shoulder and support are user inputs |
| 2. Lower arm | 60-100 = 1, <60 or >100 = 2; **+1** working across the midline or out to the side | `180 - interior(shoulder, elbow, wrist)` |
| 3. Wrist | 0 = 1, 1-15 = 2, >15 = 3; **+1** deviated from the midline | `signed_angle(hand, forearm, palmar_axis)`, magnitude; the palmar side is taken from the direction the elbow bends towards, so no thumb landmark is needed |
| 4. Wrist twist | mid-range = 1, near end of range = 2 | user input - forearm rotation is not observable from body landmarks |
| 5. Muscle use | **+1** if held >1 min or repeated >4x/min | user input |
| 6. Force | 0: <2 kg intermittent, +1: 2-10 kg intermittent, +2: 2-10 kg static/repeated, +3: >10 kg or shock | user input |

### RULA group B (neck, trunk, legs)

| Step | Chart bands | Engine |
|---|---|---|
| 9. Neck | 0-10 = 1, 10-20 = 2, >20 = 3, **in extension = 4**; +1 twisted, +1 side bent | `signed_angle(ear_mid - shoulder_mid, trunk_up, forward)` |
| 10. Trunk | 0 = 1, 0-20 = 2, 20-60 = 3, >60 = 4; +1 twisted, +1 side bent | `signed_angle(shoulder_mid - hip_mid, gravity_up, forward)` |
| 11. Legs | supported and balanced = 1, otherwise 2 | auto from knee asymmetry, overridable |

Table A + muscle + force = **Score A**; Table B + muscle + force = **Score B**;
Table C[A][B] = **grand score** -> action level 1-4.

### REBA group A (trunk, neck, legs)

| Step | Chart bands | Engine |
|---|---|---|
| 1. Neck | 0-20 = 1, >20 or extension = 2; +1 twisted, +1 side bent | same angle as RULA |
| 2. Trunk | upright = 1, 0-20 flex or 0-20 ext = 2, 20-60 flex or >20 ext = 3, >60 flex = 4; +1 twisted, +1 side bent | same angle as RULA |
| 3. Legs | bilateral/walking/sitting = 1, unilateral/unstable = 2; **+1** knee 30-60 deg, **+2** knee >60 deg (not when seated) | knee flexion measured, stance auto-detected and overridable |
| 8. Force | 0: <5 kg, +1: 5-10 kg, +2: >10 kg, +1 more for shock | user input |

### REBA group B (arms and wrist)

| Step | Chart bands | Engine |
|---|---|---|
| 4. Upper arm | same four bands as RULA; +1 raised, +1 abducted, -1 supported | same angle as RULA |
| 5. Lower arm | 60-100 = 1, otherwise 2 (no adjustment) | same angle as RULA |
| 6. Wrist | 0-15 = 1, >15 = 2; +1 bent from midline or twisted | same angle as RULA |
| 10. Coupling | good 0, fair +1, poor +2, unacceptable +3 | user input |
| 12. Activity | +1 static hold >1 min, +1 repeated >4x/min, +1 rapid large changes / unstable base | user input |

Table A + force = **Score A**; Table B + coupling = **Score B**;
Table C[A][B] + activity = **REBA score 1-15** -> negligible / low / medium /
high / very high.

### Note on the two neutral tolerances

The charts have a row for "0 deg". A pose estimate is never exactly 0, so the
engine uses a +/-5 deg neutral band (`rula.NEUTRAL_TOLERANCE`). Widening it makes
the tool more forgiving, narrowing it makes it stricter; it is one constant.

---

## 4. What the camera cannot tell you

These stay user inputs (`ergonomics/schema.py`), and the UI asks for them:

* load / force in kg, and whether it is static, repeated, or a shock load
* whether the posture is held >1 min or repeated >4x/min
* grip quality (REBA coupling)
* wrist twist (pronation/supination)
* whether the arm is supported or the worker is leaning
* whether the legs are supported / weight is bilateral, if the feet are hidden
* raised shoulders - the detector only *hints*: without a relaxed baseline for
  the same worker, shoulder elevation is not measurable from one frame, so the
  hint never changes the score on its own

Auto-detected but overridable: trunk/neck twist and side bending, arm abduction,
wrist deviation, sitting vs standing, uneven leg loading.

---

## 5. Capture matters more than the maths

RULA and REBA are defined on sagittal angles, so the correct capture is **square
to the worker's side**, whole body in frame, at about torso height.

`landmarks.classify_view()` reports `side`, `oblique` or `front` from how wide the
shoulder line spans relative to the torso, plus (from the 3D landmarks) the
shoulder line's rotation out of the camera plane. A front view returns a warning
saying the sagittal angles will be underestimated, because they will be: a trunk
bent 40 deg towards the camera projects to almost nothing in the image.

Other warnings: low landmark visibility, hidden hands (wrist angles become
guesses), hidden feet (legs become a guess).

---

## 6. Interpreting the two scores together

They are different tools and they are *meant* to disagree.

* **RULA** is an upper-limb tool. Table C weights group A (arm/wrist) heavily.
* **REBA** is a whole-body tool for unpredictable handling work. Group A
  (trunk/neck/legs) dominates, and it adds coupling and activity.

So an upright worker holding one arm overhead can land at RULA action level 4
and REBA 3. That is not an error - that is the two instruments saying "this is a
shoulder problem, not a whole-body problem". The test
`test_overhead_work_penalises_the_shoulder` locks that behaviour down.

Both are screening tools: they say *where to look and how urgently*, not whether
a given worker will be injured. A high score means observe the full task, count
the cycles, and fix the biggest angle first - which is exactly what the insight
list is ordered by.

---

## 7. References

* McAtamney, L. & Corlett, E. N. (1993). *RULA: a survey method for the
  investigation of work-related upper limb disorders.* Applied Ergonomics 24(2).
* Hignett, S. & McAtamney, L. (2000). *Rapid Entire Body Assessment (REBA).*
  Applied Ergonomics 31(2).
* ISO 11226 (static working postures) and EN 1005-4 for the angle bands behind
  the "acceptable" advice in the insight text.
