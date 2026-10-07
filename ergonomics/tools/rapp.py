"""RAPP - Risk Assessment of Pushing and Pulling (HSE, INDG478, 2016).

Type A: loads on wheeled equipment (trolleys, roll cages, pallet trucks).
Type B: loads moved without wheels (dragging, sliding, churning, rolling).

Each factor is rated green / amber / red (some purple); the colours decide the
urgency and the total score ranks tasks against each other. The load-weight
cut-offs by equipment type are transcribed from the HSE sheet and should be
confirmed against it before regulatory use (validation: transcribed).
"""

from .common import band, insight, num, pick, row, sort_insights

# equipment -> [(upper kg limit, colour, points), ...]
EQUIPMENT = {
    "small_trolley": ("Small trolley / cart / sack truck", [(50, "green", 0), (200, "amber", 4), (400, "red", 8), (1e9, "purple", 10)]),
    "large_wheeled": ("Large wheeled equipment (roll cage, wheeled bin, pallet truck)",
                      [(150, "green", 0), (600, "amber", 4), (1000, "red", 8), (1e9, "purple", 10)]),
    "no_wheels": ("Type B - dragging, sliding, churning or rolling",
                  [(25, "green", 0), (50, "amber", 4), (100, "red", 8), (1e9, "purple", 10)]),
}

POSTURE = {"good": (0, "green", "upright, hands between hip and shoulder height, no twisting"),
           "reasonable": (3, "amber", "some bending, twisting or reaching"),
           "poor": (6, "red", "severe bending, twisting or stretching")}
GRIP = {"good": (0, "green", "good handles at a comfortable height"),
        "reasonable": (1, "amber", "handles usable but not ideal"),
        "poor": (2, "red", "no handles or awkward grip")}
PATTERN = {"good": (0, "green", "occasional, plenty of recovery"),
           "reasonable": (1, "amber", "regular with some recovery"),
           "poor": (3, "red", "continuous, little recovery")}
DISTANCE = {"short": (0, "green", "under 10 m"), "medium": (1, "amber", "10-30 m"), "long": (3, "red", "over 30 m")}
EQUIP_COND = {"good": (0, "green", "well maintained, free-running wheels"),
              "reasonable": (1, "amber", "some wear or stiffness"),
              "poor": (2, "red", "damaged or poorly maintained")}
FLOOR = {"good": (0, "green", "dry, clean, level, in good condition"),
         "reasonable": (1, "amber", "slight slope, minor damage or contamination"),
         "poor": (2, "red", "steep, badly damaged or contaminated"),
         "unsuitable": (4, "purple", "unsuitable for the equipment")}
OBSTACLES = {"none": (0, "green", "none"), "some": (1, "amber", "some obstacles or a doorway"),
             "many": (2, "red", "steps, gaps, tight turns or several obstacles")}
OTHER = {"none": (0, "green", "none"), "one": (1, "amber", "one factor (lighting, heat, PPE, distraction)"),
         "two_plus": (2, "red", "two or more factors")}

COLOUR_LEVEL = {"green": 0, "amber": 2, "red": 3, "purple": 4}


def _load_factor(equipment, kg):
    name, bands = EQUIPMENT[equipment]
    for limit, colour, pts in bands:
        if kg <= limit:
            return pts, colour, "%s, %.0f kg" % (name, kg)
    return 10, "purple", name


def run(inputs):
    equipment = pick(inputs.get("equipment"), EQUIPMENT, "small_trolley")
    kg = max(0.0, num(inputs.get("load_kg"), 100))
    factors = [("A Load and equipment", _load_factor(equipment, kg))]
    for label, key, table, default in (
        ("B Posture", "posture", POSTURE, "good"), ("C Hand grip", "grip", GRIP, "good"),
        ("D Work pattern", "pattern", PATTERN, "reasonable"), ("E Travel distance", "distance", DISTANCE, "short"),
        ("F Equipment condition", "condition", EQUIP_COND, "good"), ("G Floor surface", "floor", FLOOR, "good"),
        ("H Obstacles on route", "obstacles", OBSTACLES, "none"), ("I Other factors", "other", OTHER, "none"),
    ):
        if key == "condition" and equipment == "no_wheels":
            continue
        pts, colour, text = table[pick(inputs.get(key), table, default)]
        factors.append((label, (pts, colour, text)))

    total = sum(f[1][0] for f in factors)
    worst_colour = max((f[1][1] for f in factors), key=lambda c: COLOUR_LEVEL[c])
    lvl = COLOUR_LEVEL[worst_colour]
    if lvl == 0 and total > 0:
        lvl = 1

    breakdown = [row(label, text, pts, colour) for label, (pts, colour, text) in factors]
    breakdown.append(row("Total score", "ranking only - colours set the urgency", total))

    notes = []
    for label, (pts, colour, text) in sorted(factors, key=lambda f: -f[1][0]):
        if colour == "green":
            continue
        sev = "critical" if colour == "purple" else "high" if colour == "red" else "medium"
        key = label[0]
        actions = {
            "A": ["Reduce the load per trip or use powered equipment (electric tug, powered pallet truck).",
                  "Larger-diameter wheels and correct castor configuration cut the starting force substantially."],
            "B": ["Handles at 90-120 cm so the push is made with the hands between hip and shoulder.",
                  "Push rather than pull; keep the load in front and the trunk upright."],
            "C": ["Fit vertical or horizontal handles at the right height; wrap for grip."],
            "D": ["Build recovery into the shift; rotate between pushing and other work."],
            "E": ["Shorten the route or relocate storage; move long hauls to powered equipment."],
            "F": ["Maintenance schedule for wheels, bearings and brakes; replace damaged castors."],
            "G": ["Repair the floor, remove contamination, fix drainage; avoid slopes on the route."],
            "H": ["Ramp the steps, widen doorways, remove or relocate the obstacles."],
            "I": ["Improve lighting, ventilation, and PPE fit; remove distractions."],
        }[key]
        notes.append(insight(label[2:].lower(), sev, "%s: %s" % (label[2:], text),
            "%s factor (%d points)." % (colour.capitalize(), pts), actions, "engineering", pts))
    if not notes:
        notes.append(insight("task", "info", "All factors green", "Total %d." % total,
            ["Re-assess if the load, route or equipment changes."], "administrative"))

    return {
        "tool": "rapp",
        "score": total,
        "score_label": "RAPP total",
        "band": band(lvl),
        "worst_colour": worst_colour,
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "RAPP %d, worst factor %s" % (total, worst_colour),
    }


def _opts(table):
    return [[k, v[2]] for k, v in table.items()]


SCHEMA = {
    "id": "rapp",
    "name": "RAPP - pushing and pulling",
    "short": "RAPP",
    "category": "manual_handling",
    "standard": "HSE INDG478 (2016)",
    "validation": "transcribed",
    "description": "HSE Risk Assessment of Pushing and Pulling for wheeled equipment (type A) and loads without wheels (type B).",
    "output": "Colour-banded factors plus a total for ranking. Any red or purple factor = act.",
    "groups": [
        {"title": "Load", "fields": [
            {"key": "equipment", "label": "Equipment", "type": "select", "default": "small_trolley",
             "options": [[k, v[0]] for k, v in EQUIPMENT.items()]},
            {"key": "load_kg", "label": "Total moved weight", "type": "number", "unit": "kg", "min": 0, "max": 2000, "default": 120},
        ]},
        {"title": "Task factors", "fields": [
            {"key": "posture", "label": "B Posture", "type": "select", "default": "good", "options": _opts(POSTURE)},
            {"key": "grip", "label": "C Hand grip", "type": "select", "default": "good", "options": _opts(GRIP)},
            {"key": "pattern", "label": "D Work pattern", "type": "select", "default": "reasonable", "options": _opts(PATTERN)},
            {"key": "distance", "label": "E Travel distance", "type": "select", "default": "short", "options": _opts(DISTANCE)},
            {"key": "condition", "label": "F Equipment condition", "type": "select", "default": "good", "options": _opts(EQUIP_COND)},
            {"key": "floor", "label": "G Floor surface", "type": "select", "default": "good", "options": _opts(FLOOR)},
            {"key": "obstacles", "label": "H Obstacles on route", "type": "select", "default": "none", "options": _opts(OBSTACLES)},
            {"key": "other", "label": "I Other factors", "type": "select", "default": "none", "options": _opts(OTHER)},
        ]},
    ],
}
