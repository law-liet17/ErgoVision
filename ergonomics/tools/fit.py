"""Workstation fit: does the bench, screen and reach suit this worker?

Anthropometric landmarks are estimated from stature with the Drillis & Contini
(1966) ratios; the work-height rules are Grandjean's (precision work above
elbow, light work just below, heavy work well below). The tool compares the
actual workstation dimensions against the recommendation and bands the
mismatch. It is a design aid: measure the real worker when you can.
"""

from .common import band, clamp, insight, num, pick, row, sort_insights

# stature by population percentile (cm), adult, mixed-source approximate values
STATURE = {
    "male": {5: 163, 50: 175, 95: 188},
    "female": {5: 151, 50: 162, 95: 173},
}
RATIOS = {
    "eye": 0.936, "shoulder": 0.818, "elbow": 0.630, "hip": 0.530, "knuckle": 0.377,
    "sit_eye": 0.470, "sit_elbow": 0.145, "popliteal": 0.285, "upper_arm": 0.186, "forearm": 0.146, "hand": 0.108,
}
# work height relative to standing elbow height, cm: (low, high)
WORK_OFFSET = {
    "precision": (5, 10, "precision work: 5-10 cm above elbow height, with arm support"),
    "light": (-10, -5, "light assembly / bench work: 5-10 cm below elbow height"),
    "heavy": (-40, -20, "heavy work with downward force: 20-40 cm below elbow height"),
    "seated": (0, 5, "seated keyboard work: at or slightly above seated elbow height"),
}


def landmarks(stature_cm):
    return {k: round(stature_cm * r, 1) for k, r in RATIOS.items()}


def run(inputs):
    sex = pick(inputs.get("sex"), STATURE, "male")
    stature = num(inputs.get("stature_cm"), 0)
    pct = int(clamp(num(inputs.get("percentile"), 50), 5, 95))
    if stature <= 0:
        pct = min(STATURE[sex], key=lambda p: abs(p - pct))
        stature = STATURE[sex][pct]
    work = pick(inputs.get("work_type"), WORK_OFFSET, "light")
    surface = num(inputs.get("surface_height_cm"), 0)
    reach = num(inputs.get("reach_cm"), 0)
    screen_top = num(inputs.get("screen_top_cm"), 0)
    seat = num(inputs.get("seat_height_cm"), 0)

    lm = landmarks(stature)
    lo, hi, rule = WORK_OFFSET[work]
    if work == "seated":
        base = (seat if seat > 0 else lm["popliteal"]) + lm["sit_elbow"]
        base_label = "seated elbow height %.0f cm" % base
    else:
        base = lm["elbow"]
        base_label = "standing elbow height %.0f cm" % base
    rec_lo, rec_hi = base + lo, base + hi
    normal_reach = lm["forearm"] + lm["hand"]
    max_reach = lm["upper_arm"] + lm["forearm"] + lm["hand"]
    eye = lm["eye"] if work != "seated" else (seat if seat > 0 else lm["popliteal"]) + lm["sit_eye"]

    breakdown = [
        row("Stature", "%s, ~%dth percentile" % (sex, pct), stature, "cm"),
        row("Elbow height (standing)", "0.630 x stature", lm["elbow"], "cm"),
        row("Shoulder height", "0.818 x stature", lm["shoulder"], "cm"),
        row("Eye height (standing)", "0.936 x stature", lm["eye"], "cm"),
        row("Knuckle height", "0.377 x stature", lm["knuckle"], "cm"),
        row("Recommended work height", rule, "%.0f-%.0f" % (rec_lo, rec_hi), "cm, from " + base_label),
        row("Normal reach", "forearm + hand", round(normal_reach), "cm - frequent items inside this"),
        row("Maximum reach", "whole arm", round(max_reach), "cm - occasional items inside this"),
    ]

    notes, worst, mismatch = [], 0, 0.0
    if surface > 0:
        delta = 0 if rec_lo <= surface <= rec_hi else (surface - rec_hi if surface > rec_hi else surface - rec_lo)
        mismatch = max(mismatch, abs(delta))
        breakdown.append(row("Actual work height", "%.0f cm" % surface, round(delta, 1), "cm from the recommended band"))
        if abs(delta) > 2:
            lvl = 1 if abs(delta) <= 5 else 2 if abs(delta) <= 12 else 3
            worst = max(worst, lvl)
            notes.append(insight("height", "high" if lvl >= 3 else "medium" if lvl == 2 else "low",
                "Work surface is %.0f cm too %s" % (abs(delta), "high" if delta > 0 else "low"),
                "Recommended %.0f-%.0f cm for %s; the surface is at %.0f cm. Too high lifts the shoulders, "
                "too low bends the neck and trunk." % (rec_lo, rec_hi, work, surface),
                ["Adjust the surface to %.0f-%.0f cm, or fit a height-adjustable frame." % (rec_lo, rec_hi),
                 "If the surface is shared by workers of different stature, aim for the tallest and give shorter "
                 "workers a platform (standing) or footrest (seated)."], "engineering", delta))
    if reach > 0:
        breakdown.append(row("Actual frequent reach", "%.0f cm" % reach, round(reach - normal_reach, 1), "cm beyond normal reach"))
        mismatch = max(mismatch, reach - normal_reach)
        if reach > max_reach:
            worst = max(worst, 3)
            notes.append(insight("reach", "high", "Frequent items are beyond maximum reach",
                "%.0f cm vs %.0f cm maximum reach: the worker must lean or step every time." % (reach, max_reach),
                ["Move the items inside %.0f cm; use gravity feed or a turntable." % normal_reach], "engineering", reach))
        elif reach > normal_reach:
            worst = max(worst, 2)
            notes.append(insight("reach", "medium", "Frequent items are outside the normal reach envelope",
                "%.0f cm vs %.0f cm normal reach: the arm has to extend for each pick." % (reach, normal_reach),
                ["Bring frequently used parts inside %.0f cm; keep only occasional items out to %.0f cm."
                 % (normal_reach, max_reach)], "engineering", reach))
    if screen_top > 0:
        d = screen_top - eye
        breakdown.append(row("Screen top vs eye height", "%.0f cm" % screen_top, round(d, 1), "cm above (+) or below (-) eye height"))
        if d > 3 or d < -12:
            mismatch = max(mismatch, abs(d))
            worst = max(worst, 2 if abs(d) < 20 else 3)
            notes.append(insight("screen", "medium", "Screen height is off",
                "Top of the screen should be at or just below eye height (%.0f cm); it is %.0f cm %s."
                % (eye, abs(d), "above" if d > 0 else "below"),
                ["Raise or lower the monitor so the top edge sits at eye height and the centre 15-20 deg below it."],
                "engineering", d))
    if not notes:
        notes.append(insight("fit", "info", "Workstation matches this worker",
            "All measured dimensions sit inside the recommended bands.",
            ["Check the fit for the smallest and largest workers who share the station."], "administrative"))

    return {
        "tool": "fit",
        "score": round(max(0.0, mismatch)),
        "score_label": "Largest mismatch (cm)",
        "stature_cm": round(stature),
        "band": band(worst),
        "landmarks": lm,
        "recommended": {"work_height": [round(rec_lo), round(rec_hi)], "normal_reach": round(normal_reach),
                        "max_reach": round(max_reach), "eye_height": round(eye)},
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "Work height %.0f-%.0f cm, normal reach %.0f cm for a %.0f cm worker" % (rec_lo, rec_hi, normal_reach, stature),
    }


SCHEMA = {
    "id": "fit",
    "name": "Workstation fit",
    "short": "Fit",
    "category": "design",
    "standard": "Drillis & Contini ratios; Grandjean work-height rules",
    "validation": "model",
    "description": "Recommended work height, reach envelope and screen height for a worker, compared with the actual station.",
    "output": "Recommended bands and the mismatch of the actual dimensions.",
    "groups": [
        {"title": "Worker", "fields": [
            {"key": "sex", "label": "Population", "type": "select", "default": "male", "options": [["male", "Male"], ["female", "Female"]]},
            {"key": "percentile", "label": "Design percentile", "type": "select", "default": 50,
             "options": [[5, "5th (small)"], [50, "50th (median)"], [95, "95th (tall)"]]},
            {"key": "stature_cm", "label": "Measured stature (overrides percentile)", "type": "number", "unit": "cm", "min": 0, "max": 220},
        ]},
        {"title": "Workstation", "fields": [
            {"key": "work_type", "label": "Type of work", "type": "select", "default": "light",
             "options": [["precision", "Precision (fine assembly, inspection)"], ["light", "Light bench work"],
                         ["heavy", "Heavy / downward force"], ["seated", "Seated keyboard work"]]},
            {"key": "surface_height_cm", "label": "Actual work surface height", "type": "number", "unit": "cm", "min": 0, "max": 160},
            {"key": "seat_height_cm", "label": "Seat height (seated work)", "type": "number", "unit": "cm", "min": 0, "max": 80},
            {"key": "reach_cm", "label": "Distance to frequently used items", "type": "number", "unit": "cm", "min": 0, "max": 120},
            {"key": "screen_top_cm", "label": "Height of the top of the screen", "type": "number", "unit": "cm", "min": 0, "max": 200},
        ]},
    ],
}
