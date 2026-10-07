"""OWAS - Ovako Working Posture Analysing System (Karhu, Kansi & Kuorinka, 1977).

Four digits describe a posture: back (1-4), arms (1-3), legs (1-7), load (1-3).
The published table turns the 252 combinations into an action category:

    1  normal posture, no action
    2  slightly harmful, corrective action in the near future
    3  distinctly harmful, corrective action as soon as possible
    4  extremely harmful, corrective action immediately

OWAS is usually sampled over a work period; this scorer rates one posture,
and can derive the digits from the vision engine's joint angles.
"""

from .common import band, insight, num, row, sort_insights

BACK = {1: "straight", 2: "bent forward", 3: "twisted or side-bent", 4: "bent and twisted"}
ARMS = {1: "both below shoulder level", 2: "one at or above shoulder level", 3: "both at or above shoulder level"}
LEGS = {1: "sitting", 2: "standing, both legs straight", 3: "standing, weight on one straight leg",
        4: "standing or squatting, both knees bent", 5: "standing, one knee bent", 6: "kneeling on one or both knees",
        7: "walking or moving"}
LOAD = {1: "under 10 kg", 2: "10-20 kg", 3: "over 20 kg"}

# TABLE[(back, arms)] -> 7 leg entries, each a list for the 3 load classes
TABLE = {
    (1, 1): [[1, 1, 1], [1, 1, 1], [1, 1, 1], [2, 2, 2], [2, 2, 2], [1, 1, 1], [1, 1, 1]],
    (1, 2): [[1, 1, 1], [1, 1, 1], [1, 1, 1], [2, 2, 2], [2, 2, 2], [1, 1, 1], [1, 1, 1]],
    (1, 3): [[1, 1, 1], [1, 1, 1], [1, 1, 1], [2, 2, 3], [2, 2, 3], [1, 1, 1], [1, 1, 2]],
    (2, 1): [[2, 2, 3], [2, 2, 3], [2, 2, 3], [3, 3, 3], [3, 3, 3], [2, 2, 2], [2, 3, 3]],
    (2, 2): [[2, 2, 3], [2, 2, 3], [2, 3, 3], [3, 4, 4], [3, 4, 4], [3, 3, 4], [2, 3, 4]],
    (2, 3): [[3, 3, 4], [2, 2, 3], [3, 3, 3], [3, 4, 4], [4, 4, 4], [4, 4, 4], [2, 3, 4]],
    (3, 1): [[1, 1, 1], [1, 1, 1], [1, 1, 2], [3, 3, 3], [4, 4, 4], [1, 1, 1], [1, 1, 1]],
    (3, 2): [[2, 2, 3], [1, 1, 1], [1, 1, 2], [4, 4, 4], [4, 4, 4], [3, 3, 3], [1, 1, 1]],
    (3, 3): [[2, 2, 3], [1, 1, 1], [2, 3, 3], [4, 4, 4], [4, 4, 4], [4, 4, 4], [1, 1, 1]],
    (4, 1): [[2, 3, 3], [2, 2, 3], [2, 2, 3], [4, 4, 4], [4, 4, 4], [4, 4, 4], [2, 3, 4]],
    (4, 2): [[3, 3, 4], [2, 3, 4], [3, 3, 4], [4, 4, 4], [4, 4, 4], [4, 4, 4], [2, 3, 4]],
    (4, 3): [[4, 4, 4], [2, 3, 4], [3, 3, 4], [4, 4, 4], [4, 4, 4], [4, 4, 4], [2, 3, 4]],
}

CATEGORY_LEVEL = {1: 0, 2: 2, 3: 3, 4: 4}
CATEGORY_TEXT = {
    1: "Normal posture - no corrective action needed.",
    2: "Slightly harmful - corrective action in the near future.",
    3: "Distinctly harmful - corrective action as soon as possible.",
    4: "Extremely harmful - corrective action immediately.",
}


def lookup(back, arms, legs, load):
    return TABLE[(int(back), int(arms))][int(legs) - 1][int(load) - 1]


def from_angles(angles, flags=None, load_kg=0.0):
    """Derive the OWAS digits from the vision engine's angle payload."""
    flags = flags or {}
    trunk = num(angles.get("trunk_flexion"))
    twisted = bool(flags.get("trunk_twisted")) or abs(num(angles.get("trunk_twist"))) > 20 \
        or abs(num(angles.get("trunk_side_bend"))) > 15
    bent = trunk > 20
    back = 4 if (bent and twisted) else 3 if twisted else 2 if bent else 1

    def raised(side):
        arm = angles.get(side) or {}
        return max(num(arm.get("upper_arm_flexion")), num(arm.get("upper_arm_elevation"))) >= 90
    n_up = int(raised("left")) + int(raised("right"))
    arms = 1 if n_up == 0 else 2 if n_up == 1 else 3

    lk, rk = num(angles.get("left_knee_flexion")), num(angles.get("right_knee_flexion"))
    if flags.get("probably_sitting"):
        legs = 1
    elif lk > 30 and rk > 30:
        legs = 4
    elif lk > 30 or rk > 30:
        legs = 5
    elif flags.get("legs_uneven"):
        legs = 3
    else:
        legs = 2
    load = 1 if load_kg < 10 else 2 if load_kg <= 20 else 3
    return {"back": back, "arms": arms, "legs": legs, "load": load}


def run(inputs):
    back = int(max(1, min(4, num(inputs.get("back"), 1))))
    arms = int(max(1, min(3, num(inputs.get("arms"), 1))))
    legs = int(max(1, min(7, num(inputs.get("legs"), 2))))
    load = int(max(1, min(3, num(inputs.get("load"), 1))))
    category = lookup(back, arms, legs, load)
    lvl = CATEGORY_LEVEL[category]

    breakdown = [
        row("Back", BACK[back], back), row("Arms", ARMS[arms], arms),
        row("Legs", LEGS[legs], legs), row("Load", LOAD[load], load),
        row("Action category", CATEGORY_TEXT[category], category),
    ]
    notes = []
    if back >= 2:
        notes.append(insight("back", "high" if back == 4 else "medium", "Back is %s" % BACK[back],
            "Back code %d is the strongest driver of OWAS category %d." % (back, category),
            ["Raise the work to between knuckle and elbow height so the trunk stays upright.",
             "Move the pick/place points in front of the worker to remove the twist."], "engineering", back))
    if arms >= 2:
        notes.append(insight("arms", "medium", ARMS[arms].capitalize(),
            "Work at or above shoulder height fatigues the shoulder within minutes.",
            ["Lower the work or raise the worker (platform, height-adjustable stand)."], "engineering", arms))
    if legs in (4, 5, 6):
        notes.append(insight("legs", "medium", "Legs: %s" % LEGS[legs],
            "Squatting and kneeling load the knees and are unstable under load.",
            ["Bring low work up onto a stand; provide a sit-stand stool or kneeling pad if it cannot be raised."],
            "engineering", legs))
    if load >= 2:
        notes.append(insight("load", "high" if load == 3 else "medium", "Load %s" % LOAD[load],
            "Load class %d multiplies the harm of every posture code." % load,
            ["Use a lifting aid or split the load."], "engineering", load))
    if not notes:
        notes.append(insight("posture", "info", "Posture is acceptable", CATEGORY_TEXT[1],
            ["Keep sampling other postures in the cycle - OWAS is meant to be applied over time."], "administrative"))

    return {
        "tool": "owas",
        "score": category,
        "score_label": "Action category",
        "band": band(lvl),
        "code": "%d%d%d%d" % (back, arms, legs, load),
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "OWAS %d%d%d%d - action category %d" % (back, arms, legs, load, category),
    }


SCHEMA = {
    "id": "owas",
    "name": "OWAS working posture",
    "short": "OWAS",
    "category": "posture",
    "standard": "Karhu, Kansi & Kuorinka (1977)",
    "validation": "transcribed",
    "description": "Whole-body posture code (back, arms, legs, load) mapped to one of four action categories. Auto-filled from a photo in the posture lab.",
    "output": "Action category 1-4.",
    "groups": [
        {"title": "Posture code", "fields": [
            {"key": "back", "label": "Back", "type": "select", "default": 1, "options": [[k, v] for k, v in BACK.items()]},
            {"key": "arms", "label": "Arms", "type": "select", "default": 1, "options": [[k, v] for k, v in ARMS.items()]},
            {"key": "legs", "label": "Legs", "type": "select", "default": 2, "options": [[k, v] for k, v in LEGS.items()]},
            {"key": "load", "label": "Load or force", "type": "select", "default": 1, "options": [[k, v] for k, v in LOAD.items()]},
        ]},
    ],
}
