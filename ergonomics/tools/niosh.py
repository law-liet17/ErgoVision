"""Revised NIOSH Lifting Equation (Waters, Putz-Anderson, Garg & Fine, 1993).

    RWL = LC x HM x VM x DM x AM x FM x CM          (kg)
    LI  = load / RWL

LC (load constant) = 23 kg.  Multipliers:
    HM = 25 / H                 H = horizontal hand distance from mid-ankles, cm (25..63)
    VM = 1 - 0.003 |V - 75|     V = vertical hand height at lift start, cm (0..175)
    DM = 0.82 + 4.5 / D         D = vertical travel distance, cm (>= 25)
    AM = 1 - 0.0032 A           A = asymmetry angle, deg (0..135)
    FM = table(F, duration, V)  F = lifts per minute
    CM = table(coupling, V)

The lift is scored at the origin *and* the destination; the larger LI governs.
Multi-task jobs use the Composite Lifting Index (CLI).
"""

from .common import band, clamp, insight, num, pick, row, sort_insights

LOAD_CONSTANT = 23.0

FREQUENCIES = [0.2, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]

# FM rows: (duration, V < 75 cm) -> multiplier per frequency in FREQUENCIES
FM_TABLE = {
    ("1h", True):  [1.00, .97, .94, .91, .88, .84, .80, .75, .70, .60, .52, .45, .41, .37, .00, .00, .00],
    ("1h", False): [1.00, .97, .94, .91, .88, .84, .80, .75, .70, .60, .52, .45, .41, .37, .34, .31, .28],
    ("2h", True):  [.95, .92, .88, .84, .79, .72, .60, .50, .42, .35, .30, .26, .00, .00, .00, .00, .00],
    ("2h", False): [.95, .92, .88, .84, .79, .72, .60, .50, .42, .35, .30, .26, .23, .21, .00, .00, .00],
    ("8h", True):  [.85, .81, .75, .65, .55, .45, .35, .27, .22, .18, .00, .00, .00, .00, .00, .00, .00],
    ("8h", False): [.85, .81, .75, .65, .55, .45, .35, .27, .22, .18, .15, .13, .00, .00, .00, .00, .00],
}

CM_TABLE = {  # coupling -> (V < 75, V >= 75)
    "good": (1.00, 1.00),
    "fair": (0.95, 1.00),
    "poor": (0.90, 0.90),
}

DURATIONS = ("1h", "2h", "8h")
COUPLINGS = ("good", "fair", "poor")


def hm(h):
    if h <= 25:
        return 1.0
    if h > 63:
        return 0.0
    return 25.0 / h


def vm(v):
    if v < 0 or v > 175:
        return 0.0
    return 1.0 - 0.003 * abs(v - 75.0)


def dm(d):
    if d <= 25:
        return 1.0
    if d > 175:
        return 0.0
    return 0.82 + 4.5 / d


def am(a):
    if a > 135:
        return 0.0
    return 1.0 - 0.0032 * max(0.0, a)


def fm(f, duration, v):
    """Frequency multiplier. Frequencies between table rows round *up* (conservative)."""
    if f <= 0.2:
        f = 0.2
    if f > 15:
        return 0.0
    idx = next(i for i, x in enumerate(FREQUENCIES) if x >= f - 1e-9)
    return FM_TABLE[(duration, v < 75)][idx]


def cm(coupling, v):
    low, high = CM_TABLE[coupling]
    return low if v < 75 else high


def _point(load, h, v, d, a, f, duration, coupling):
    mult = {
        "HM": hm(h), "VM": vm(v), "DM": dm(d), "AM": am(a),
        "FM": fm(f, duration, v), "CM": cm(coupling, v),
    }
    rwl = LOAD_CONSTANT
    for m in mult.values():
        rwl *= m
    li = (load / rwl) if rwl > 0 else float("inf")
    return {"multipliers": {k: round(x, 3) for k, x in mult.items()},
            "rwl": round(rwl, 2), "li": (None if li == float("inf") else round(li, 2)),
            "inputs": {"H": h, "V": v, "D": d, "A": a, "F": f}}


def li_level(li):
    if li is None:
        return 4
    if li < 0.7:
        return 0
    if li <= 1.0:
        return 1
    if li <= 2.0:
        return 2
    if li <= 3.0:
        return 3
    return 4


def run(inputs):
    """Single-task lift. Inputs are in cm / kg / lifts per minute."""
    load = num(inputs.get("load_kg"), 10)
    h_o = clamp(num(inputs.get("h_origin_cm"), 40), 0, 200)
    v_o = clamp(num(inputs.get("v_origin_cm"), 50), 0, 250)
    h_d = clamp(num(inputs.get("h_dest_cm"), h_o), 0, 200)
    v_d = clamp(num(inputs.get("v_dest_cm"), 100), 0, 250)
    a_o = clamp(num(inputs.get("a_origin_deg"), 0), 0, 180)
    a_d = clamp(num(inputs.get("a_dest_deg"), a_o), 0, 180)
    f = clamp(num(inputs.get("lifts_per_min"), 1), 0, 30)
    duration = pick(inputs.get("duration"), DURATIONS, "8h")
    coupling = pick(inputs.get("coupling"), COUPLINGS, "fair")
    d = abs(v_d - v_o)

    origin = _point(load, h_o, v_o, d, a_o, f, duration, coupling)
    dest = _point(load, h_d, v_d, d, a_d, f, duration, coupling)
    worst_name, worst = max((("origin", origin), ("destination", dest)),
                            key=lambda kv: (kv[1]["li"] if kv[1]["li"] is not None else 1e9))
    li = worst["li"]
    lvl = li_level(li)

    m = worst["multipliers"]
    breakdown = [
        row("Load constant", "23 kg", LOAD_CONSTANT, "NIOSH reference load"),
        row("Horizontal (HM)", "%.0f cm" % worst["inputs"]["H"], m["HM"], "25 / H"),
        row("Vertical (VM)", "%.0f cm" % worst["inputs"]["V"], m["VM"], "1 - 0.003 |V - 75|"),
        row("Distance (DM)", "%.0f cm" % d, m["DM"], "0.82 + 4.5 / D"),
        row("Asymmetry (AM)", "%.0f deg" % worst["inputs"]["A"], m["AM"], "1 - 0.0032 A"),
        row("Frequency (FM)", "%.1f /min, %s" % (f, {"1h": "<= 1 h", "2h": "<= 2 h", "8h": "<= 8 h"}[duration]), m["FM"], "table"),
        row("Coupling (CM)", coupling, m["CM"], "table"),
        row("RWL", "%.2f kg" % worst["rwl"], worst["rwl"], "product of the above"),
        row("Lifting index", "%.2f" % load if li is None else "%.1f kg / %.2f kg" % (load, worst["rwl"]),
            li if li is not None else "n/a", "load / RWL, at the %s" % worst_name),
    ]

    # --- recommendations, keyed to the weakest multiplier --------------------
    notes = []
    ranked = sorted(m.items(), key=lambda kv: kv[1])
    for key, value in ranked[:3]:
        if value >= 0.9 and li is not None and li <= 1.0:
            continue
        if key == "HM" and value < 0.9:
            notes.append(insight("horizontal", "high" if value < 0.6 else "medium",
                "Load is held too far from the body",
                "H = %.0f cm gives HM %.2f: the RWL falls in proportion to 25/H, so every extra "
                "10 cm of reach costs roughly a fifth of the allowable load." % (worst["inputs"]["H"], value),
                ["Remove the obstruction between the worker and the load (bin lip, pallet edge, guard).",
                 "Bring the load to the front edge of the surface; use tilted bins or lift-tilt tables.",
                 "Reduce container size so the hands can get close to the centre of mass."], "engineering", value))
        elif key == "VM" and value < 0.85:
            notes.append(insight("vertical", "medium",
                "Lift starts or ends far from knuckle height",
                "V = %.0f cm gives VM %.2f. Knuckle height (75 cm) is the ideal; floor and shoulder "
                "level lifts both lose about a quarter." % (worst["inputs"]["V"], value),
                ["Store heavy items between knuckle and elbow height (roughly 70-110 cm).",
                 "Use a scissor lift, pallet lifter or spring-loaded platform to keep the pick height constant.",
                 "Put the lightest items on the top and bottom shelves."], "engineering", value))
        elif key == "DM" and value < 0.9:
            notes.append(insight("distance", "low",
                "Long vertical travel",
                "D = %.0f cm gives DM %.2f." % (d, value),
                ["Reduce the height difference between pick and place (raise the source or lower the destination)."],
                "engineering", value))
        elif key == "AM" and value < 0.85:
            notes.append(insight("asymmetry", "high" if value < 0.7 else "medium",
                "Lift involves twisting",
                "A = %.0f deg gives AM %.2f. Twisting under load is the classic disc-injury mechanism." % (worst["inputs"]["A"], value),
                ["Re-orient the workstation so pick and place points are in front of the worker.",
                 "Add a turntable or move the feet with a step rather than rotating the trunk."], "engineering", value))
        elif key == "FM" and value < 0.8:
            notes.append(insight("frequency", "high" if value < 0.5 else "medium",
                "Lifting is too frequent for the shift length",
                "%.1f lifts/min over %s gives FM %.2f." % (f, {"1h": "up to 1 h", "2h": "up to 2 h", "8h": "up to 8 h"}[duration], value),
                ["Mechanise the repetitive element (conveyor, hoist, vacuum lifter).",
                 "Rotate workers between lifting and non-lifting tasks; add recovery breaks.",
                 "Batch items so fewer, better lifts replace many small ones only if RWL still allows the heavier load."],
                "administrative", value))
        elif key == "CM" and value < 1.0:
            notes.append(insight("coupling", "low",
                "Grip is not ideal",
                "Coupling rated '%s' (CM %.2f)." % (coupling, value),
                ["Add handles or cut-outs; use containers sized for a full power grip."], "engineering", value))
    if li is not None and li > 1.0:
        notes.insert(0, insight("load", "critical" if li > 3 else "high",
            "Load exceeds the recommended weight limit",
            "LI = %.2f: the load is %.0f%% of what this lift geometry allows (RWL %.1f kg)." % (li, li * 100, worst["rwl"]),
            ["Reduce the load to %.1f kg or less, or change the geometry until the RWL rises above the load." % worst["rwl"],
             "Split the load, use two-person handling with a clear protocol, or introduce a lifting aid."],
            "eliminate", li))
    if not notes:
        notes.append(insight("lift", "info", "Lift is within the recommended limit",
            "LI %.2f: acceptable for nearly all healthy workers." % (li or 0),
            ["Keep the geometry as it is; re-assess if load, frequency or layout change."], "administrative"))

    return {
        "tool": "niosh",
        "score": li,
        "score_label": "Lifting index",
        "band": band(lvl),
        "rwl": worst["rwl"],
        "governing": worst_name,
        "origin": origin,
        "destination": dest,
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "RWL %.1f kg at the %s; lifting index %s" % (worst["rwl"], worst_name, "n/a" if li is None else "%.2f" % li),
    }


def composite(tasks, duration="8h"):
    """Composite Lifting Index for a multi-task job (NIOSH 1994 procedure).

    Each task is a dict like run()'s inputs (single geometry). STLI ranks the tasks;
    CLI adds the frequency-driven increments of the remaining tasks.
    """
    duration = pick(duration, DURATIONS, "8h")
    scored = []
    for t in tasks:
        load = num(t.get("load_kg"), 10)
        h = clamp(num(t.get("h_origin_cm"), 40), 0, 200)
        v = clamp(num(t.get("v_origin_cm"), 50), 0, 250)
        d = abs(clamp(num(t.get("v_dest_cm"), v), 0, 250) - v)
        a = clamp(num(t.get("a_origin_deg"), 0), 0, 180)
        f = clamp(num(t.get("lifts_per_min"), 1), 0.2, 30)
        coupling = pick(t.get("coupling"), COUPLINGS, "fair")
        fi_rwl = LOAD_CONSTANT * hm(h) * vm(v) * dm(d) * am(a) * cm(coupling, v)
        fili = load / fi_rwl if fi_rwl > 0 else float("inf")
        f_mult = fm(f, duration, v)
        stli = fili / f_mult if f_mult > 0 else float("inf")
        scored.append({"name": t.get("name") or "task %d" % (len(scored) + 1), "fili": fili, "stli": stli,
                       "f": f, "v": v, "load": load})
    scored.sort(key=lambda s: -s["stli"])
    if not scored:
        return {"tool": "niosh_cli", "score": None, "band": band(0), "tasks": []}

    cli = scored[0]["stli"]
    cumulative = scored[0]["f"]
    steps = [{"task": scored[0]["name"], "term": round(scored[0]["stli"], 3), "note": "STLI of the hardest task"}]
    for s in scored[1:]:
        prev = fm(cumulative, duration, s["v"])
        cumulative += s["f"]
        cur = fm(cumulative, duration, s["v"])
        if cur <= 0:
            term = float("inf")
        else:
            term = s["fili"] * (1.0 / cur - (1.0 / prev if prev > 0 else 0.0))
        cli += term
        steps.append({"task": s["name"], "term": None if term == float("inf") else round(term, 3),
                      "note": "FILI x (1/FM(%.1f) - 1/FM(%.1f))" % (cumulative, cumulative - s["f"])})
    score = None if cli == float("inf") else round(cli, 2)
    return {
        "tool": "niosh_cli",
        "score": score,
        "score_label": "Composite lifting index",
        "band": band(li_level(score)),
        "tasks": [{"name": s["name"], "fili": round(s["fili"], 3), "stli": round(s["stli"], 3)} for s in scored],
        "steps": steps,
        "summary": "CLI %s over %d tasks" % ("n/a" if score is None else score, len(scored)),
    }


SCHEMA = {
    "id": "niosh",
    "name": "NIOSH Lifting Equation",
    "short": "NIOSH",
    "category": "manual_handling",
    "standard": "Waters, Putz-Anderson, Garg & Fine (1993); Applications Manual (1994)",
    "validation": "verified",
    "description": "Recommended weight limit and lifting index for a two-handed lift, scored at origin and destination.",
    "output": "Lifting index (LI). 1.0 = the load equals the recommended limit.",
    "groups": [
        {"title": "Load and frequency", "fields": [
            {"key": "load_kg", "label": "Load", "type": "number", "unit": "kg", "min": 0, "max": 80, "step": 0.5, "default": 12},
            {"key": "lifts_per_min", "label": "Lifts per minute", "type": "number", "min": 0, "max": 20, "step": 0.1, "default": 2},
            {"key": "duration", "label": "Lifting duration", "type": "select", "default": "8h",
             "options": [["1h", "up to 1 hour"], ["2h", "up to 2 hours"], ["8h", "up to 8 hours"]]},
            {"key": "coupling", "label": "Hand coupling", "type": "select", "default": "fair",
             "options": [["good", "Good - handles, comfortable grip"], ["fair", "Fair"], ["poor", "Poor - no handles, awkward"]]},
        ]},
        {"title": "Origin (where the lift starts)", "fields": [
            {"key": "h_origin_cm", "label": "Horizontal distance H", "type": "number", "unit": "cm", "min": 20, "max": 80, "default": 45,
             "help": "Mid-ankles to the hands, measured horizontally"},
            {"key": "v_origin_cm", "label": "Hand height V", "type": "number", "unit": "cm", "min": 0, "max": 175, "default": 30},
            {"key": "a_origin_deg", "label": "Asymmetry angle A", "type": "number", "unit": "deg", "min": 0, "max": 135, "default": 0},
        ]},
        {"title": "Destination (where it is placed)", "fields": [
            {"key": "h_dest_cm", "label": "Horizontal distance H", "type": "number", "unit": "cm", "min": 20, "max": 80, "default": 40},
            {"key": "v_dest_cm", "label": "Hand height V", "type": "number", "unit": "cm", "min": 0, "max": 175, "default": 100},
            {"key": "a_dest_deg", "label": "Asymmetry angle A", "type": "number", "unit": "deg", "min": 0, "max": 135, "default": 0},
        ]},
    ],
}
