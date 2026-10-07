# Assessment tools

Eleven methods. Each keeps its native score and maps onto the common 0-4
action band (see [FLOWCHART.md](FLOWCHART.md)). The **status** column is
shown in the UI and matters:

* **verified** — tables and equations checked by unit tests against the published source
* **transcribed** — transcribed from the published sheet; confirm against the printed
  worksheet before regulatory use
* **model** — an engineering estimate or design rule, not a scored worksheet

| Tool | Source | Status | Native score → band |
|---|---|---|---|
| RULA | McAtamney & Corlett 1993 | verified | action level 1 → 0/1, 2 → 2, 3 → 3, 4 → 4 |
| REBA | Hignett & McAtamney 2000 | verified | risk level 0-4 directly |
| OWAS | Karhu et al. 1977 | transcribed | category 1 → 0, 2 → 2, 3 → 3, 4 → 4 |
| NIOSH lifting equation | Waters et al. 1993/94 | verified | LI < 0.7 → 0, ≤ 1 → 1, ≤ 2 → 2, ≤ 3 → 3, > 3 → 4 |
| Strain Index | Moore & Garg 1995 | verified | SI ≤ 1.5 → 0, ≤ 3 → 1, ≤ 7 → 2, ≤ 13 → 3, > 13 → 4 |
| ROSA | Sonne et al. 2012 | transcribed | 1-2 → 0, 3-4 → 1, 5 → 2, 6-7 → 3, 8-10 → 4 |
| ART | HSE INDG438 | transcribed | exposure < 12 → 1, < 22 → 2, < 30 → 3, ≥ 30 → 4 (0 → 0) |
| RAPP | HSE INDG478 | transcribed | worst factor colour: green 0/1, amber 2, red 3, purple 4 |
| KIM-LHC | BAuA 2001 | transcribed | < 10 → 1, < 25 → 2, < 50 → 3, ≥ 50 → 4 |
| L5/S1 biomechanics | static sagittal model; NIOSH 1981 limits | model | < 2500 N → 0, < 3400 → 1, < 4500 → 2, < 6400 → 3, ≥ 6400 → 4 |
| Workstation fit | Drillis & Contini; Grandjean | model | largest mismatch: ≤ 2 cm → 0, ≤ 5 → 1, ≤ 12 → 2, beyond → 3 |

## Notes per tool

**NIOSH** — `RWL = 23 · HM · VM · DM · AM · FM · CM`, scored at origin and
destination, larger LI governs. Frequencies between table rows round *up*
(conservative). The composite lifting index follows the 1994 manual: tasks
sorted by STLI, then `CLI = STLI₁ + Σ FILIⱼ (1/FM(F₁..Fⱼ) − 1/FM(F₁..Fⱼ₋₁))`.

**Strain Index** — a standard 8 h shift is the 1.0 duration band; only overtime
beyond 8 h scores 1.5.

**ROSA** — the two grand tables in the published sheet are `max()` lookups and
are implemented as such; Tables A, B and C are transcribed row by row.

**ART** — the HSE sheet has three bands (low / medium / high 22+). The
"very high" split at 30 is ours, so that extreme exposures rank above ordinary
high ones in the register.

**RAPP** — the HSE guidance uses colours to set urgency and the total only to
rank; the band therefore follows the worst colour. The load cut-offs per
equipment type are the item most worth checking against the printed sheet.

**KIM** — the 2001 LHC sheet (time × (load + posture + conditions)). The 2019
revision adds indicators and is not implemented.

**L5/S1 model** — two-segment static model: upper-body lump (0.54 body mass,
COM at 0.45 of the trunk length) plus arm segments and hand load, erector
spinae on a 5 cm lever, compression = muscle force + weight component along
the spine. It is an estimate for ranking, not a substitute for 3DSSPP-class
software. The shoulder "reference capacity" (60 / 40 N·m) is indicative only.

**Workstation fit** — landmark ratios from Drillis & Contini (elbow 0.630,
shoulder 0.818, eye 0.936 × stature); work-height rules: precision +5..+10 cm
above elbow, light −5..−10 cm, heavy −20..−40 cm. Normal reach = forearm +
hand; maximum reach = whole arm.

**Posture tools** — see [SCORING.md](SCORING.md) for how joint angles are
measured and mapped onto the RULA/REBA rows. OWAS digits are derived from the
same angles (`owas.from_angles`).

## API

```
GET  /api/tools                 catalogue with input schemas
POST /api/tools/<id>            {inputs: {...}}  ->  result
POST /api/tools/niosh/composite {tasks: [...], duration: "8h"}
```

Every result: `score`, `score_label`, `band {level,label,action,colour}`,
`breakdown [{label,value,points,note}]`, `insights [{factor,severity,title,
why,actions,control}]`, `summary`.
