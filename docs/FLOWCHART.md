# ErgoVision — assessment flow

The same seven stages for every exposure. Stage 1 decides which engines run;
stage 4 is what lets a NIOSH lifting index, a REBA score and a ROSA score sit
in the same register and be ranked together.

```
 ┌─ 0. SITE MODEL ─────────────────────────────────────────────────────────┐
 │  Plant → Department → Workstation → Task      (the risk register keys)  │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 1. TASK TRIAGE  (what kind of work is it?) ────────────────────────────┐
 │  lifting / lowering ─────► NIOSH RWL·LI·CLI   + KIM-LHC   + L5/S1 model │
 │  carrying / holding ─────► KIM-LHC                                       │
 │  pushing / pulling ──────► RAPP (HSE)                                    │
 │  repetitive upper limb ──► Strain Index + ART (HSE) + RULA              │
 │  awkward / static posture► RULA · REBA · OWAS  (from photo/video/live)  │
 │  office / screen work ───► ROSA                                          │
 │  any task ───────────────► Workstation-fit (anthropometrics)            │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 2. CAPTURE ────────────────────────────────────────────────────────────┐
 │  a) Vision: photo / clip / webcam → MediaPipe → joint angles, hand      │
 │     positions, view check, landmark confidence                          │
 │  b) Observed inputs the camera cannot see: load, frequency, duration,   │
 │     coupling, distances, breaks, floor, equipment                       │
 │  c) Anthropometrics: stature, mass, sex / population percentile         │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 3. ASSESSMENT ENGINES  (published tables & equations, each unit-tested)┐
 │  Posture ........ RULA · REBA · OWAS                                    │
 │  Manual handling  NIOSH lifting equation · KIM-LHC · RAPP push/pull     │
 │  Repetition ..... Moore-Garg Strain Index · HSE ART                     │
 │  Office ......... ROSA                                                  │
 │  Biomechanics ... static sagittal L5/S1 compression + shoulder moment   │
 │  Fit ............ work-height & reach envelope vs the worker            │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 4. NORMALISE ──────────────────────────────────────────────────────────┐
 │  every tool keeps its native score AND maps to one 0-4 action band      │
 │  (negligible · low · medium · high · very high)                         │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 5. INSIGHTS & CONTROLS ────────────────────────────────────────────────┐
 │  driving factor → fix, ordered by the hierarchy of controls             │
 │  (eliminate → substitute → engineering → administrative → PPE);         │
 │  what-if: edit an input, watch the score move                           │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                ▼
 ┌─ 6. RISK REGISTER & DASHBOARD ──────────────────────────────────────────┐
 │  workstation × tool heat-map · priority queue · action tracker          │
 │  (owner / due / status) · re-assessment trend · CSV / printable report  │
 └─────────────────────────────────────────────────────────────────────────┘
```

## Where each stage lives in the code

| Stage | Code |
|---|---|
| 0 Site model | `store.py` — `workstations` table; UI `#/workstations` |
| 1 Triage | `web/app.js` `TRIAGE` (method page); `ergonomics/tools/__init__.py` catalogue |
| 2 Capture | `ergonomics/pose_backend.py`, `landmarks.py`, `angles.py`; observed inputs via each tool's `SCHEMA` |
| 3 Engines | `ergonomics/rula.py`, `reba.py`, `tools/*.py` |
| 4 Normalise | `ergonomics/tools/common.py` `band()` — the 0-4 action band every result carries |
| 5 Insights | each engine's `insights` list; `insight(..., control=...)` carries the hierarchy-of-controls tag |
| 6 Register | `store.py` assessments + actions; `/api/dashboard`; UI `#/`, `#/register`, `#/actions` |

## The common action band

| Level | Label | Meaning |
|---|---|---|
| 0 | negligible | No action needed. |
| 1 | low | Acceptable; improve if the change is cheap. |
| 2 | medium | Action needed. Plan a change and re-assess. |
| 3 | high | Action needed soon. Prioritise this workstation. |
| 4 | very high | Action needed now. Redesign or stop the task. |

How each tool maps onto it is documented in [TOOLS.md](TOOLS.md).
