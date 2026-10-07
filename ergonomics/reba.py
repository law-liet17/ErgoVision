"""REBA - Rapid Entire Body Assessment (Hignett & McAtamney, 2000).

Group A (trunk, neck, legs) -> Table A, + force/load        = Score A
Group B (upper arm, lower arm, wrist) -> Table B, + coupling = Score B
Table C[Score A][Score B] + activity score                   = REBA score (1..15)

Same transcription approach as :mod:`.rula`: the tables are the printed
worksheet, written out so they can be checked by eye.
"""

from .schema import build_component, clamp

# --- Table A -------------------------------------------------------------
# Key: (neck score 1..3, trunk score 1..5). Values: legs 1..4.
TABLE_A_ROWS = {
    (1, 1): [1, 2, 3, 4],
    (1, 2): [2, 3, 4, 5],
    (1, 3): [2, 4, 5, 6],
    (1, 4): [3, 5, 6, 7],
    (1, 5): [4, 6, 7, 8],
    (2, 1): [1, 2, 3, 4],
    (2, 2): [3, 4, 5, 6],
    (2, 3): [4, 5, 6, 7],
    (2, 4): [5, 6, 7, 8],
    (2, 5): [6, 7, 8, 9],
    (3, 1): [3, 3, 5, 6],
    (3, 2): [4, 5, 6, 7],
    (3, 3): [5, 6, 7, 8],
    (3, 4): [6, 7, 8, 9],
    (3, 5): [7, 7, 8, 9],
}

# --- Table B -------------------------------------------------------------
# Key: upper arm score 1..6.
# Values: lower arm 1 with wrist 1..3, then lower arm 2 with wrist 1..3.
TABLE_B_ROWS = {
    1: [1, 2, 2, 1, 2, 3],
    2: [1, 2, 3, 2, 3, 4],
    3: [3, 4, 5, 4, 5, 5],
    4: [4, 5, 5, 5, 6, 7],
    5: [6, 7, 8, 7, 8, 8],
    6: [7, 8, 8, 8, 9, 9],
}

# --- Table C -------------------------------------------------------------
# Rows: Score A 1..12, columns: Score B 1..12.
TABLE_C = [
    [1, 1, 1, 2, 3, 3, 4, 5, 6, 7, 7, 7],
    [1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 7, 8],
    [2, 3, 3, 3, 4, 5, 6, 7, 7, 8, 8, 8],
    [3, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9],
    [4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9],
    [6, 6, 6, 7, 8, 8, 9, 9, 10, 10, 10, 10],
    [7, 7, 7, 8, 9, 9, 9, 10, 10, 11, 11, 11],
    [8, 8, 8, 9, 10, 10, 10, 10, 10, 11, 11, 11],
    [9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12],
    [10, 10, 10, 11, 11, 11, 11, 12, 12, 12, 12, 12],
    [11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12],
    [12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12],
]

COUPLING_SCORES = {
    "good": (0, "well fitting handle, mid-range power grip"),
    "fair": (1, "acceptable but not ideal hand hold"),
    "poor": (2, "hand hold not acceptable although possible"),
    "unacceptable": (3, "no handles, awkward, unsafe grip"),
}

RISK_BANDS = [
    (1, 1, "negligible", 0, "No action necessary."),
    (2, 3, "low", 1, "Action may be necessary."),
    (4, 7, "medium", 2, "Action necessary."),
    (8, 10, "high", 3, "Action necessary soon."),
    (11, 15, "very high", 4, "Action necessary NOW."),
]

NEUTRAL_TOLERANCE = 5.0


def lookup_table_a(neck, trunk, legs):
    nk = int(clamp(neck, 1, 3))
    tr = int(clamp(trunk, 1, 5))
    lg = int(clamp(legs, 1, 4))
    return TABLE_A_ROWS[(nk, tr)][lg - 1]


def lookup_table_b(upper_arm, lower_arm, wrist):
    ua = int(clamp(upper_arm, 1, 6))
    la = int(clamp(lower_arm, 1, 2))
    wr = int(clamp(wrist, 1, 3))
    return TABLE_B_ROWS[ua][(la - 1) * 3 + (wr - 1)]


def lookup_table_c(score_a, score_b):
    a = int(clamp(score_a, 1, 12))
    b = int(clamp(score_b, 1, 12))
    return TABLE_C[a - 1][b - 1]


# ---------------------------------------------------------------------------
# Group A
# ---------------------------------------------------------------------------

def neck_component(neck_flexion, ctx):
    if neck_flexion is None:
        neck_flexion = 0.0
    if neck_flexion < -NEUTRAL_TOLERANCE:
        base, band = 2, "in extension"
    elif neck_flexion <= 20:
        base, band = 1, "0-20 deg flexion"
    else:
        base, band = 2, "more than 20 deg flexion"

    adj = []
    if ctx["neck_twisted"]:
        adj.append({"label": "neck twisted", "delta": 1})
    if ctx["neck_side_bent"]:
        adj.append({"label": "neck side bent", "delta": 1})
    return build_component("neck", neck_flexion, base, band, adj, low=1, high=3)


def trunk_component(trunk_flexion, ctx):
    if trunk_flexion is None:
        trunk_flexion = 0.0
    magnitude = abs(trunk_flexion)
    if magnitude <= NEUTRAL_TOLERANCE:
        base, band = 1, "upright"
    elif trunk_flexion < 0:
        base = 2 if magnitude <= 20 else 3
        band = "%.0f deg extension" % magnitude
    elif trunk_flexion <= 20:
        base, band = 2, "0-20 deg flexion"
    elif trunk_flexion <= 60:
        base, band = 3, "20-60 deg flexion"
    else:
        base, band = 4, "more than 60 deg flexion"

    adj = []
    if ctx["trunk_twisted"]:
        adj.append({"label": "trunk twisted", "delta": 1})
    if ctx["trunk_side_bent"]:
        adj.append({"label": "trunk side bent", "delta": 1})
    return build_component("trunk", trunk_flexion, base, band, adj, low=1, high=5)


def legs_component(knee_flexion, ctx):
    """REBA legs: stance base, then a knee-flexion add-on (not when seated)."""
    bilateral = ctx["legs_bilateral"]
    base = 1 if bilateral else 2
    band = (
        "bilateral weight bearing, walking or sitting"
        if bilateral
        else "unilateral, unstable or raised leg"
    )

    adj = []
    knee = 0.0 if knee_flexion is None else knee_flexion
    if not ctx["sitting"]:
        if knee > 60:
            adj.append({"label": "knee flexed more than 60 deg", "delta": 2})
        elif knee >= 30:
            adj.append({"label": "knee flexed 30-60 deg", "delta": 1})
    return build_component("legs", knee, base, band, adj, low=1, high=4)


# ---------------------------------------------------------------------------
# Group B
# ---------------------------------------------------------------------------

def upper_arm_component(flexion, ctx):
    if flexion is None:
        flexion = 0.0
    if flexion < -20:
        base, band = 2, "extension beyond 20 deg"
    elif flexion <= 20:
        base, band = 1, "20 deg extension to 20 deg flexion"
    elif flexion <= 45:
        base, band = 2, "20-45 deg flexion"
    elif flexion <= 90:
        base, band = 3, "45-90 deg flexion"
    else:
        base, band = 4, "more than 90 deg flexion"

    adj = []
    if ctx["shoulder_raised"]:
        adj.append({"label": "shoulder raised", "delta": 1})
    if ctx["arm_abducted"]:
        adj.append({"label": "upper arm abducted", "delta": 1})
    if ctx["arm_supported"]:
        adj.append({"label": "arm supported / person leaning", "delta": -1})
    return build_component("upper_arm", flexion, base, band, adj, low=1, high=6)


def lower_arm_component(elbow_flexion, ctx=None):
    if elbow_flexion is None:
        elbow_flexion = 0.0
    if 60 <= elbow_flexion <= 100:
        base, band = 1, "60-100 deg flexion"
    elif elbow_flexion < 60:
        base, band = 2, "less than 60 deg flexion"
    else:
        base, band = 2, "more than 100 deg flexion"
    return build_component("lower_arm", elbow_flexion, base, band, [], low=1, high=2)


def wrist_component(wrist_flexion, ctx):
    if wrist_flexion is None:
        wrist_flexion = 0.0
    magnitude = abs(wrist_flexion)
    if magnitude <= 15:
        base, band = 1, "0-15 deg flexion or extension"
    else:
        base, band = 2, "more than 15 deg flexion or extension"

    adj = []
    if ctx["wrist_deviated"] or ctx["wrist_twist_end_range"]:
        adj.append({"label": "wrist bent from midline or twisted", "delta": 1})
    return build_component("wrist", wrist_flexion, base, band, adj, low=1, high=3)


# ---------------------------------------------------------------------------
# Force, coupling, activity
# ---------------------------------------------------------------------------

def force_score(ctx):
    load = ctx["load_kg"]
    if load < 5:
        base, band = 0, "load under 5 kg"
    elif load <= 10:
        base, band = 1, "load 5-10 kg"
    else:
        base, band = 2, "load over 10 kg"
    if ctx["shock_or_rapid_buildup"]:
        return base + 1, band + " plus shock or rapid build-up of force"
    return base, band


def coupling_score(ctx):
    return COUPLING_SCORES[ctx["coupling"]]


def activity_score(ctx):
    score, reasons = 0, []
    if ctx["static_posture"]:
        score += 1
        reasons.append("one or more body parts held static for longer than 1 minute")
    if ctx["repeated_actions"]:
        score += 1
        reasons.append("small range actions repeated more than 4x per minute")
    if ctx["rapid_large_changes"]:
        score += 1
        reasons.append("rapid large range changes in posture or an unstable base")
    return score, reasons


def risk_band(reba_score):
    for low, high, label, level, action in RISK_BANDS:
        if low <= reba_score <= high:
            return label, level, action
    return "very high", 4, "Action necessary NOW."


# ---------------------------------------------------------------------------
# Full assessment
# ---------------------------------------------------------------------------

def score_side(angles, modifiers, side):
    ctx = modifiers.resolved(angles.flags, side)
    arm = angles.side(side)

    knees = [k for k in (angles.left_knee_flexion, angles.right_knee_flexion) if k is not None]
    worst_knee = max(knees) if knees else 0.0

    neck = neck_component(angles.neck_flexion, ctx)
    trunk = trunk_component(angles.trunk_flexion, ctx)
    legs = legs_component(worst_knee, ctx)

    upper_arm = upper_arm_component(arm.upper_arm_flexion, ctx)
    lower_arm = lower_arm_component(arm.elbow_flexion)
    wrist = wrist_component(arm.wrist_flexion, ctx)

    table_a = lookup_table_a(neck.score, trunk.score, legs.score)
    force, force_band = force_score(ctx)
    score_a = table_a + force

    table_b = lookup_table_b(upper_arm.score, lower_arm.score, wrist.score)
    coupling, coupling_band = coupling_score(ctx)
    score_b = table_b + coupling

    table_c = lookup_table_c(score_a, score_b)
    activity, activity_reasons = activity_score(ctx)
    total = int(clamp(table_c + activity, 1, 15))

    label, level, action = risk_band(total)

    return {
        "standard": "REBA",
        "side": side,
        "components": {
            c.name: c.to_dict()
            for c in (neck, trunk, legs, upper_arm, lower_arm, wrist)
        },
        "group_a": {
            "table_a": table_a,
            "force": force,
            "force_band": force_band,
            "score": score_a,
        },
        "group_b": {
            "table_b": table_b,
            "coupling": coupling,
            "coupling_band": coupling_band,
            "score": score_b,
        },
        "table_c": table_c,
        "activity": activity,
        "activity_reasons": activity_reasons,
        "reba_score": total,
        "risk": label,
        "risk_level": level,
        "action": action,
        "context": ctx,
    }


def score(angles, modifiers):
    """REBA for both arms; the governing side is the worse one unless pinned."""
    sides = {s: score_side(angles, modifiers, s) for s in ("left", "right")}
    if modifiers.assessed_side in ("left", "right"):
        governing = modifiers.assessed_side
    else:
        governing = max(sides, key=lambda s: (sides[s]["reba_score"], sides[s]["group_b"]["score"]))
    result = dict(sides[governing])
    result["sides"] = {s: sides[s]["reba_score"] for s in sides}
    result["detail_by_side"] = sides
    result["governing_side"] = governing
    return result
