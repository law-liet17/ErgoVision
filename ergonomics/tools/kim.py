"""KIM-LHC - Key Indicator Method for lifting, holding and carrying (BAuA, 2001).

    risk score = time rating x (load rating + posture rating + working-condition rating)

    < 10   low          10-25  increased      25-50  highly increased      >= 50  high

The 2001 sheet is used because its four ratings are compact and widely quoted;
the 2019 revision adds more indicators. (validation: transcribed)
"""

from .common import band, insight, num, pick, row, sort_insights


def time_rating(activity, quantity):
    """Lifting: operations per day. Holding: minutes per day. Carrying: metres per day."""
    steps = {
        "lifting": [(10, 1), (40, 2), (200, 4), (500, 6), (1000, 8)],
        "holding": [(5, 1), (15, 2), (60, 4), (120, 6), (240, 8)],
        "carrying": [(300, 1), (1000, 2), (4000, 4), (8000, 6), (16000, 8)],
    }[activity]
    for limit, pts in steps:
        if quantity < limit:
            return pts
    return 10


def load_rating(kg, sex):
    steps = [(10, 1), (20, 2), (30, 4), (40, 7)] if sex == "male" else [(5, 1), (10, 2), (15, 4), (25, 7)]
    for limit, pts in steps:
        if kg < limit:
            return pts
    return 25


POSTURE = {
    "upright": (1, "upper body upright, load close to the body"),
    "slight_bend": (2, "slight forward bend or twist, load close to the body"),
    "low_bend": (4, "low bending or far forward bend, or slight bend with the load away from the body"),
    "far_forward": (8, "far forward bend with the load far from the body, or above shoulder height"),
}
CONDITIONS = {
    "good": (0, "good: enough space, level firm floor, good lighting and grip"),
    "restricted": (1, "restricted: little space, uneven or soft floor, poor grip"),
    "strongly_restricted": (2, "strongly restricted: very confined, unstable floor, poor lighting"),
}
ACTIVITY_LABEL = {"lifting": ("lifting", "operations per day"), "holding": ("holding", "minutes per day"),
                  "carrying": ("carrying", "metres carried per day")}


def run(inputs):
    activity = pick(inputs.get("activity"), ACTIVITY_LABEL, "lifting")
    quantity = max(0.0, num(inputs.get("quantity"), 100))
    kg = max(0.0, num(inputs.get("load_kg"), 15))
    sex = pick(inputs.get("sex"), ("male", "female"), "male")
    posture_key = pick(inputs.get("posture"), POSTURE, "slight_bend")
    cond_key = pick(inputs.get("conditions"), CONDITIONS, "good")

    t = time_rating(activity, quantity)
    l = load_rating(kg, sex)
    p, p_txt = POSTURE[posture_key]
    c, c_txt = CONDITIONS[cond_key]
    score = t * (l + p + c)
    lvl = 1 if score < 10 else 2 if score < 25 else 3 if score < 50 else 4

    breakdown = [
        row("Time rating", "%s: %.0f %s" % (activity, quantity, ACTIVITY_LABEL[activity][1]), t),
        row("Load rating", "%.0f kg (%s reference)" % (kg, sex), l),
        row("Posture rating", p_txt, p),
        row("Working conditions", c_txt, c),
        row("Risk score", "%d x (%d + %d + %d)" % (t, l, p, c), score),
    ]
    notes = []
    if l >= 7:
        notes.append(insight("load", "critical" if l == 25 else "high", "Load is heavy for this population",
            "Load rating %d for %.0f kg." % (l, kg),
            ["Reduce the unit load or use a lifting aid; the load rating dominates the score."], "eliminate", l))
    if p >= 4:
        notes.append(insight("posture", "high" if p == 8 else "medium", "Trunk posture during the handling",
            p_txt.capitalize() + ".",
            ["Raise the pick-up height, bring the load closer, remove the need to bend or reach overhead."],
            "engineering", p))
    if t >= 6:
        notes.append(insight("frequency", "medium", "High daily frequency or duration",
            "Time rating %d." % t,
            ["Reduce the number of handlings per shift (larger batches on wheels, conveyors).",
             "Share the task across workers or across the shift."], "administrative", t))
    if c >= 1:
        notes.append(insight("conditions", "low", "Working conditions add risk", c_txt.capitalize() + ".",
            ["Clear space around the task, repair the floor, improve lighting and grip surfaces."], "engineering", c))
    if not notes:
        notes.append(insight("task", "info", "Low load situation", "Risk score %d." % score,
            ["Re-check when load, frequency or layout change."], "administrative"))
    return {
        "tool": "kim",
        "score": score,
        "score_label": "KIM risk score",
        "band": band(lvl),
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "KIM-LHC %d (%s)" % (score, ["negligible", "low", "increased", "highly increased", "high"][lvl]),
    }


SCHEMA = {
    "id": "kim",
    "name": "KIM - lifting, holding, carrying",
    "short": "KIM",
    "category": "manual_handling",
    "standard": "BAuA Key Indicator Method LHC (2001)",
    "validation": "transcribed",
    "description": "German Key Indicator Method: daily time, load, posture and conditions combined into one risk score.",
    "output": "Risk score. < 10 low, 10-25 increased, 25-50 highly increased, 50+ high.",
    "groups": [
        {"title": "Activity", "fields": [
            {"key": "activity", "label": "Activity", "type": "select", "default": "lifting",
             "options": [["lifting", "Lifting / lowering"], ["holding", "Holding"], ["carrying", "Carrying"]]},
            {"key": "quantity", "label": "Quantity per day", "type": "number", "min": 0, "max": 20000, "default": 100,
             "help": "operations for lifting, minutes for holding, metres for carrying"},
            {"key": "load_kg", "label": "Load", "type": "number", "unit": "kg", "min": 0, "max": 100, "step": 0.5, "default": 15},
            {"key": "sex", "label": "Reference population", "type": "select", "default": "male",
             "options": [["male", "Male"], ["female", "Female"]]},
        ]},
        {"title": "Posture and conditions", "fields": [
            {"key": "posture", "label": "Typical posture", "type": "select", "default": "slight_bend",
             "options": [[k, v[1]] for k, v in POSTURE.items()]},
            {"key": "conditions", "label": "Working conditions", "type": "select", "default": "good",
             "options": [[k, v[1]] for k, v in CONDITIONS.items()]},
        ]},
    ],
}
