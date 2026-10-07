# ErgoVision

**See the risk before the injury.**

Workplace ergonomics platform for industrial engineers and operations managers:
photo / video posture analysis plus ten further assessment methods, one common
risk band, a workstation risk register, an action tracker and a dashboard.

```
web/                   the console (single-page app)
  index.html app.css app.js   dashboard Â· tools Â· register Â· actions Â· workstations Â· method
  twin.js                     the Three.js digital twin used by the posture lab
app.py                 Flask API + static hosting
store.py               SQLite risk register (workstations, assessments, actions)
main.py                live webcam viewer (same engine)
download_model.py      one-off: fetch the MediaPipe pose model
ergonomics/            the engines
  rula.py reba.py             posture worksheets (from measured joint angles)
  angles.py landmarks.py      landmarks -> worksheet angles   (see docs/SCORING.md)
  pose_backend.py             MediaPipe legacy or Tasks API, whichever is installed
  tools/                      niosh Â· strain_index Â· rosa Â· owas Â· art Â· rapp Â· kim Â· biomech Â· fit
tests/                 73 tests: tables, bands, angle extraction, end to end
docs/                  FLOWCHART.md Â· TOOLS.md Â· SCORING.md
```

## Run

```bash
pip install -r requirements.txt
python download_model.py           # once, if /health says the pose model is missing
python app.py                      # then open http://127.0.0.1:5000/
```

On first open the dashboard offers to load a demo plant (nine workstations,
fifteen assessments, all produced by really running the engines). Clear it
from the dashboard when you start entering your own.

```bash
python tests/test_scoring.py       # vision + RULA/REBA
python tests/test_tools.py         # the other nine tools
node --experimental-vm-modules check_js.mjs web/app.js web/twin.js   # front-end syntax
```

## What it does

**Posture lab** â€” upload a side-on photo or clip (or drop it on the 3D stage).
MediaPipe finds the body, the engine measures the worksheet angles, and the
digital twin takes the exact pose with every segment coloured by its RULA/REBA
band. RULA, REBA and OWAS are scored together, the worksheet arithmetic is
shown, and the posture can be sent on to the biomechanical model or NIOSH with
the angles and hand distance pre-filled.

**Assessment tools** â€” NIOSH lifting equation (with composite index), Moore-Garg
Strain Index, ROSA, OWAS, HSE ART, HSE RAPP, KIM-LHC, a static L5/S1 and
shoulder biomechanical model, and an anthropometric workstation-fit check. Each
form rescoring live; each result shows the score, its band, the row-by-row
breakdown and a fix list ordered by the hierarchy of controls.

**Risk register** â€” every saved assessment against its workstation, ranked by
band, filterable, exportable to CSV, with a printable report per assessment
and follow-up actions (owner, due date, status).

**Dashboard** â€” KPI tiles, a workstation Ã— tool heat-map, band distribution,
assessments by tool, activity trend and the priority queue.

**Method** â€” the seven-stage flowchart, a triage wizard that recommends tools
for a task type, and the validation status of every tool.

## Validation status (shown on every tool)

* **verified** â€” tables and equations checked by unit tests against the published source: RULA, REBA, NIOSH, Strain Index
* **transcribed** â€” transcribed from the published sheet, confirm before regulatory use: OWAS, ROSA, ART, RAPP, KIM
* **model** â€” engineering estimate or design rule: L5/S1 biomechanics, workstation fit

Details and the band mapping for every tool: [docs/TOOLS.md](docs/TOOLS.md).

## API (summary)

| Route | Purpose |
|---|---|
| `POST /analyze`, `/analyze-video`, `/score` | vision: angles â†’ RULA/REBA/OWAS |
| `GET /api/tools`, `POST /api/tools/<id>` | catalogue and tool runs |
| `/api/workstations`, `/api/assessments`, `/api/actions` | the register (CRUD) |
| `GET /api/dashboard` | aggregated view |
| `POST /api/demo/seed`, `/api/demo/clear` | demo data |

## Accuracy limits

* RULA/REBA angles are sagittal; a front-on photo underestimates them and the
  lab says so in its warnings.
* Single-camera depth is weak: twist, side bending and abduction are detected
  as flags you can override, not trusted measurements.
* The biomechanical model is a two-segment static estimate for ranking, not a
  3D dynamic simulation.
* Both posture worksheets and every tool here are screening methods: they say
  where to look and how urgently, not whether a particular worker will be injured.
