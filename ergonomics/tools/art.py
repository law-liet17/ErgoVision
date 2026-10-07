"""ART - Assessment of Repetitive Tasks of the upper limbs (HSE, INDG438, 2010).

Twelve risk factors in four stages (frequency and repetition, force, awkward
postures, additional factors) score green / amber / red points for one arm.
Task score x duration multiplier = exposure score:

    0-11  low       12-21  medium       22+  high

The point values below are transcribed from the HSE flow chart; confirm against
the printed sheet before regulatory use (validation: transcribed).
"""

from .common import band, insight, num, pick, row, sort_insights

ARM_MOVEMENTS = {"infrequent": (0, "infrequent - some intermittent movement"),
                 "frequent": (3, "frequent - regular movement with some pauses"),
                 "very_frequent": (6, "very frequent - almost continuous movement")}
REPETITION = {"le10": (0, "10 or fewer per minute"), "11to20": (3, "11-20 per minute"), "gt20": (6, "more than 20 per minute")}
FORCE_LEVEL = {"light": "light", "moderate": "moderate", "strong": "strong", "very_strong": "very strong"}
FORCE_TIME = {"some": "some of the time (< 1/3)", "regular": "regularly (1/3 to 2/3)", "most": "most of the time (> 2/3)"}
# force points: level -> (some, regular, most)
FORCE_POINTS = {"light": (0, 0, 0), "moderate": (1, 2, 4), "strong": (4, 6, 8), "very_strong": (12, 12, 12)}

HEAD = {"neutral": (0, "neutral or nearly neutral"), "awkward_some": (1, "bent or twisted some of the time"),
        "awkward_most": (2, "bent or twisted most of the time")}
BACK = {"neutral": (0, "upright"), "awkward_some": (1, "bent or twisted some of the time"),
        "awkward_most": (2, "bent or twisted most of the time")}
ARM = {"neutral": (0, "elbow close to the body"), "raised_some": (2, "raised or away from the body some of the time"),
       "raised_most": (4, "raised or away most of the time")}
WRIST = {"neutral": (0, "straight or nearly"), "bent_some": (1, "bent or deviated some of the time"),
         "bent_most": (2, "bent or deviated most of the time")}
GRIP = {"power": (0, "power grip"), "pinch_some": (1, "pinch or wide grip some of the time"),
        "pinch_most": (2, "pinch or wide grip most of the time")}
BREAKS = {"regular": (0, "break at least every hour"), "every_2h": (2, "break every 1-2 hours"),
          "longer": (4, "breaks more than 2 hours apart")}
PACE = {"self": (0, "self-paced"), "some_difficulty": (1, "sometimes difficult to keep up"),
        "often_difficulty": (2, "often difficult to keep up")}
OTHER = {"none": (0, "none"), "one": (1, "one factor (gloves, vibration, cold, precision...)"), "two_plus": (2, "two or more factors")}
DURATION = {"lt2h": (0.5, "under 2 h/day"), "2to4h": (0.75, "2-4 h/day"), "4to8h": (1.0, "4-8 h/day"), "gt8h": (1.5, "over 8 h/day")}


def run(inputs):
    def get(key, table, default):
        return table[pick(inputs.get(key), table, default)]

    arm_mv = get("arm_movements", ARM_MOVEMENTS, "frequent")
    rep = get("repetition", REPETITION, "11to20")
    f_level = pick(inputs.get("force_level"), FORCE_POINTS, "moderate")
    f_time = pick(inputs.get("force_time"), FORCE_TIME, "some")
    force_pts = FORCE_POINTS[f_level][["some", "regular", "most"].index(f_time)]
    head = get("head", HEAD, "neutral")
    back = get("back", BACK, "neutral")
    arm = get("arm", ARM, "neutral")
    wrist = get("wrist", WRIST, "bent_some")
    grip = get("grip", GRIP, "power")
    breaks = get("breaks", BREAKS, "regular")
    pace = get("pace", PACE, "self")
    other = get("other", OTHER, "none")
    dur_mult, dur_txt = get("duration", DURATION, "4to8h")

    parts = [
        ("A1 Arm movements", arm_mv), ("A2 Repetition", rep),
        ("B  Force", (force_pts, "%s force %s" % (FORCE_LEVEL[f_level], FORCE_TIME[f_time]))),
        ("C1 Head/neck posture", head), ("C2 Back posture", back), ("C3 Arm posture", arm),
        ("C4 Wrist posture", wrist), ("C5 Hand/finger grip", grip),
        ("D1 Breaks", breaks), ("D2 Work pace", pace), ("D3 Other factors", other),
    ]
    task_score = sum(p[1][0] for p in parts)
    exposure = task_score * dur_mult
    lvl = 1 if exposure < 12 else 2 if exposure < 22 else 3 if exposure < 30 else 4
    if exposure == 0:
        lvl = 0

    breakdown = [row(label, val[1], val[0]) for label, val in parts]
    breakdown.append(row("Task score", "sum", task_score))
    breakdown.append(row("Duration multiplier", dur_txt, dur_mult))
    breakdown.append(row("Exposure score", "task x duration", round(exposure, 1)))

    notes = []
    ranked = sorted(parts, key=lambda p: -p[1][0])
    for label, (pts, text) in ranked[:3]:
        if pts <= 0:
            continue
        key = label.split()[0]
        if key.startswith("A"):
            notes.append(insight("repetition", "high" if pts >= 6 else "medium", "%s: %s" % (label[3:], text),
                "%d points. Frequency is the exposure that turns tolerable postures into tendon injury." % pts,
                ["Mechanise or semi-automate the most repetitive element.",
                 "Enlarge the job so different muscle groups share the cycle; rotate every 1-2 h."],
                "engineering", pts))
        elif key == "B":
            notes.append(insight("force", "critical" if pts >= 8 else "high", "Force: %s" % text,
                "%d points." % pts,
                ["Take the force out of the hand: powered tools, torque arms, fixtures, low-friction feeds.",
                 "Sharpen cutting edges and maintain tools so less grip force is needed."], "engineering", pts))
        elif key.startswith("C"):
            notes.append(insight("posture", "medium", "%s: %s" % (label[3:], text), "%d points." % pts,
                ["Adjust work height and orientation so the neck, back, arm and wrist stay near neutral.",
                 "Bend the tool rather than the wrist; bring the work in to the elbow."], "engineering", pts))
        elif key == "D1":
            notes.append(insight("breaks", "medium", "Breaks are too far apart", text,
                ["Schedule a short break or task change at least every hour."], "administrative", pts))
        elif key == "D2":
            notes.append(insight("pace", "medium", "Work pace", text,
                ["Add a buffer so the worker is decoupled from the line; allow self-pacing."], "administrative", pts))
        else:
            notes.append(insight("other", "low", "Additional factors", text,
                ["Address gloves fit, vibration, cold and precision demands one by one."], "ppe", pts))
    if not notes:
        notes.append(insight("task", "info", "Low exposure", "Exposure score %.0f." % exposure,
            ["Re-assess if cycle time or shift length change."], "administrative"))

    return {
        "tool": "art",
        "score": round(exposure, 1),
        "score_label": "Exposure score",
        "band": band(lvl),
        "task_score": task_score,
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "ART exposure %.0f (%s arm)" % (exposure, inputs.get("side") or "assessed"),
    }


def _opts(table):
    return [[k, v[1]] for k, v in table.items()]


SCHEMA = {
    "id": "art",
    "name": "ART - repetitive upper-limb tasks",
    "short": "ART",
    "category": "repetition",
    "standard": "HSE INDG438 (2010)",
    "validation": "transcribed",
    "description": "HSE Assessment of Repetitive Tasks: frequency, force, posture and additional factors for one arm, weighted by daily duration.",
    "output": "Exposure score. 0-11 low, 12-21 medium, 22+ high.",
    "groups": [
        {"title": "Arm and frequency", "fields": [
            {"key": "side", "label": "Arm assessed", "type": "select", "default": "right", "options": [["right", "Right"], ["left", "Left"]]},
            {"key": "arm_movements", "label": "A1 Arm movements", "type": "select", "default": "frequent", "options": _opts(ARM_MOVEMENTS)},
            {"key": "repetition", "label": "A2 Repetition", "type": "select", "default": "11to20", "options": _opts(REPETITION)},
        ]},
        {"title": "Force", "fields": [
            {"key": "force_level", "label": "B Force level", "type": "select", "default": "moderate",
             "options": [["light", "Light (< 1 kg)"], ["moderate", "Moderate (1-4 kg)"], ["strong", "Strong (4-6 kg)"], ["very_strong", "Very strong (> 6 kg)"]]},
            {"key": "force_time", "label": "How often", "type": "select", "default": "some", "options": [[k, v] for k, v in FORCE_TIME.items()]},
        ]},
        {"title": "Awkward postures", "fields": [
            {"key": "head", "label": "C1 Head / neck", "type": "select", "default": "neutral", "options": _opts(HEAD)},
            {"key": "back", "label": "C2 Back", "type": "select", "default": "neutral", "options": _opts(BACK)},
            {"key": "arm", "label": "C3 Arm", "type": "select", "default": "neutral", "options": _opts(ARM)},
            {"key": "wrist", "label": "C4 Wrist", "type": "select", "default": "bent_some", "options": _opts(WRIST)},
            {"key": "grip", "label": "C5 Hand / finger grip", "type": "select", "default": "power", "options": _opts(GRIP)},
        ]},
        {"title": "Additional factors", "fields": [
            {"key": "breaks", "label": "D1 Breaks", "type": "select", "default": "regular", "options": _opts(BREAKS)},
            {"key": "pace", "label": "D2 Work pace", "type": "select", "default": "self", "options": _opts(PACE)},
            {"key": "other", "label": "D3 Other factors", "type": "select", "default": "none", "options": _opts(OTHER)},
            {"key": "duration", "label": "Daily duration", "type": "select", "default": "4to8h", "options": _opts(DURATION)},
        ]},
    ],
}
