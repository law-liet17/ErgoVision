"""RULA - Rapid Upper Limb Assessment (McAtamney & Corlett, 1993).

Group A (arm and wrist): upper arm, lower arm, wrist, wrist twist -> Table A
Group B (neck, trunk, legs): neck, trunk, legs                    -> Table B
Score A = Table A + muscle use + force/load
Score B = Table B + muscle use + force/load
Grand score = Table C[Score A][Score B] -> action level 1..4

The tables below are the published worksheet values, transcribed as flat rows so
they can be eyeballed against a printed worksheet. Nothing is computed from a
formula - a chart lookup is a chart lookup.
"""

from .schema import Component, build_component, clamp

# --- Table A -------------------------------------------------------------
# Key: (upper arm score, lower arm score).
# Row order: wrist 1..4, each with wrist twist 1 then 2.
TABLE_A_ROWS = {
    (1, 1): [1, 2, 2, 2, 2, 3, 3, 3],
    (1, 2): [2, 2, 2, 2, 3, 3, 3, 3],
    (1, 3): [2, 3, 3, 3, 3, 3, 4, 4],
    (2, 1): [2, 3, 3, 3, 3, 4, 4, 4],
    (2, 2): [3, 3, 3, 3, 3, 4, 4, 4],
    (2, 3): [3, 4, 4, 4, 4, 4, 5, 5],
    (3, 1): [3, 3, 4, 4, 4, 4, 5, 5],
    (3, 2): [3, 4, 4, 4, 4, 4, 5, 5],
    (3, 3): [4, 4, 4, 4, 4, 5, 5, 5],
    (4, 1): [4, 4, 4, 4, 4, 5, 5, 5],
    (4, 2): [4, 4, 4, 4, 4, 5, 5, 5],
    (4, 3): [4, 4, 4, 5, 5, 5, 6, 6],
    (5, 1): [5, 5, 5, 5, 5, 6, 6, 7],
    (5, 2): [5, 6, 6, 6, 6, 7, 7, 7],
    (5, 3): [6, 6, 6, 7, 7, 7, 7, 8],
    (6, 1): [7, 7, 7, 7, 7, 8, 8, 9],
    (6, 2): [8, 8, 8, 8, 8, 9, 9, 9],
    (6, 3): [9, 9, 9, 9, 9, 9, 9, 9],
}

# --- Table B -------------------------------------------------------------
# Key: neck score 1..6. Row order: trunk 1..6, each with legs 1 then 2.
TABLE_B_ROWS = {
    1: [1, 3, 2, 3, 3, 4, 5, 5, 6, 6, 7, 7],
    2: [2, 3, 2, 3, 4, 5, 5, 5, 6, 7, 7, 7],
    3: [3, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7],
    4: [5, 5, 5, 6, 6, 7, 7, 7, 7, 7, 8, 8],
    5: [7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8],
    6: [8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9],
}

# --- Table C -------------------------------------------------------------
# Rows: Score A 1..8+, columns: Score B 1..7+.
TABLE_C = [
    [1, 2, 3, 3, 4, 5, 5],
    [2, 2, 3, 4, 4, 5, 5],
    [3, 3, 3, 4, 4, 5, 6],
    [3, 3, 3, 4, 5, 6, 6],
    [4, 4, 4, 5, 6, 7, 7],
    [4, 4, 5, 6, 6, 7, 7],
    [5, 5, 6, 6, 7, 7, 7],
    [5, 5, 6, 7, 7, 7, 7],
]

ACTION_LEVELS = {
    1: ("Acceptable", "Posture is acceptable if it is not maintained or repeated for long periods."),
    2: ("Investigate", "Further investigation needed; changes may be required."),
    3: ("Investigate soon", "Investigation and changes are required soon."),
    4: ("Change now", "Investigation and changes are required immediately."),
}

# A pose estimate is never exactly 0 deg, so "neutral" gets a small tolerance.
NEUTRAL_TOLERANCE = 5.0


def lookup_table_a(upper_arm, lower_arm, wrist, wrist_twist):
    ua = int(clamp(upper_arm, 1, 6))
    la = int(clamp(lower_arm, 1, 3))
    wr = int(clamp(wrist, 1, 4))
    tw = int(clamp(wrist_twist, 1, 2))
    return TABLE_A_ROWS[(ua, la)][(wr - 1) * 2 + (tw - 1)]


def lookup_table_b(neck, trunk, legs):
    nk = int(clamp(neck, 1, 6))
    tr = int(clamp(trunk, 1, 6))
    lg = int(clamp(legs, 1, 2))
    return TABLE_B_ROWS[nk][(tr - 1) * 2 + (lg - 1)]


def lookup_table_c(score_a, score_b):
    a = int(clamp(score_a, 1, 8))
    b = int(clamp(score_b, 1, 7))
    return TABLE_C[a - 1][b - 1]


# ---------------------------------------------------------------------------
# Group A components
# ---------------------------------------------------------------------------

def upper_arm_component(flexion, ctx):
    """RULA step 1. `flexion` is signed: + forward flexion, - extension."""
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


def lower_arm_component(elbow_flexion, ctx):
    """RULA step 2. Elbow flexion with 0 deg = straight arm."""
    if elbow_flexion is None:
        elbow_flexion = 0.0
    if 60 <= elbow_flexion <= 100:
        base, band = 1, "60-100 deg flexion"
    elif elbow_flexion < 60:
        base, band = 2, "less than 60 deg flexion"
    else:
        base, band = 2, "more than 100 deg flexion"

    adj = []
    if ctx["arm_across_midline"]:
        adj.append({"label": "arm works across midline or out to the side", "delta": 1})
    return build_component("lower_arm", elbow_flexion, base, band, adj, low=1, high=3)


def wrist_component(wrist_flexion, ctx):
    """RULA step 3. Flexion and extension score the same, so magnitude is used."""
    if wrist_flexion is None:
        wrist_flexion = 0.0
    magnitude = abs(wrist_flexion)
    if magnitude <= NEUTRAL_TOLERANCE:
        base, band = 1, "neutral (within %g deg)" % NEUTRAL_TOLERANCE
    elif magnitude <= 15:
        base, band = 2, "1-15 deg flexion or extension"
    else:
        base, band = 3, "more than 15 deg flexion or extension"

    adj = []
    if ctx["wrist_deviated"]:
        adj.append({"label": "wrist deviated from midline", "delta": 1})
    return build_component("wrist", wrist_flexion, base, band, adj, low=1, high=4)


def wrist_twist_component(ctx):
    """RULA step 4. Not visible in a photo - comes from the task description."""
    end_range = ctx["wrist_twist_end_range"]
    band = "at or near end of twisting range" if end_range else "mainly in mid-range"
    return build_component("wrist_twist", None, 2 if end_range else 1, band, [], low=1, high=2)


# ---------------------------------------------------------------------------
# Group B components
# ---------------------------------------------------------------------------

def neck_component(neck_flexion, ctx):
    """RULA step 9. `neck_flexion` is measured from the trunk axis, + = forward."""
    if neck_flexion is None:
        neck_flexion = 0.0
    if neck_flexion < -NEUTRAL_TOLERANCE:
        base, band = 4, "in extension"
    elif neck_flexion <= 10:
        base, band = 1, "0-10 deg flexion"
    elif neck_flexion <= 20:
        base, band = 2, "10-20 deg flexion"
    else:
        base, band = 3, "more than 20 deg flexion"

    adj = []
    if ctx["neck_twisted"]:
        adj.append({"label": "neck twisted", "delta": 1})
    if ctx["neck_side_bent"]:
        adj.append({"label": "neck side bent", "delta": 1})
    return build_component("neck", neck_flexion, base, band, adj, low=1, high=6)


def trunk_component(trunk_flexion, ctx):
    """RULA step 10. `trunk_flexion` is measured from vertical, + = forward."""
    if trunk_flexion is None:
        trunk_flexion = 0.0
    magnitude = abs(trunk_flexion)
    if magnitude <= NEUTRAL_TOLERANCE:
        base = 1
        band = "seated, trunk well supported" if ctx["sitting"] else "upright"
    elif trunk_flexion < 0:
        # RULA only illustrates flexion; extension is scored on magnitude and flagged.
        base = 2 if magnitude <= 20 else 3
        band = "%.0f deg extension (scored on magnitude)" % magnitude
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
    return build_component("trunk", trunk_flexion, base, band, adj, low=1, high=6)


def legs_component(ctx):
    """RULA step 11. 1 if legs and feet are supported and balanced, else 2."""
    supported = ctx["legs_supported"]
    band = "legs and feet supported and balanced" if supported else "legs or feet unsupported / unbalanced"
    return build_component("legs", None, 1 if supported else 2, band, [], low=1, high=2)


# ---------------------------------------------------------------------------
# Muscle use and force
# ---------------------------------------------------------------------------

def muscle_use_score(ctx):
    reasons = []
    if ctx["static_posture"]:
        reasons.append("posture held longer than 1 minute")
    if ctx["repeated_actions"]:
        reasons.append("action repeated more than 4x per minute")
    return (1 if reasons else 0), reasons


def force_score(ctx):
    """RULA force/load: 0, +1, +2 or +3."""
    load = ctx["load_kg"]
    sustained = ctx["load_static_or_repeated"]
    if ctx["shock_or_rapid_buildup"] or load > 10:
        return 3, "load over 10 kg, or shock / rapid build-up of force"
    if load >= 2 and sustained:
        return 2, "2-10 kg static or repeated"
    if load >= 2:
        return 1, "2-10 kg intermittent"
    return 0, "under 2 kg intermittent"


# ---------------------------------------------------------------------------
# Full assessment
# ---------------------------------------------------------------------------

def action_level(grand_score):
    if grand_score <= 2:
        return 1
    if grand_score <= 4:
        return 2
    if grand_score <= 6:
        return 3
    return 4


RISK_BY_LEVEL = {1: "negligible", 2: "low", 3: "medium", 4: "high"}


def score_side(angles, modifiers, side):
    """Full RULA for one arm (group B is shared, group A is per side)."""
    ctx = modifiers.resolved(angles.flags, side)
    arm = angles.side(side)

    upper_arm = upper_arm_component(arm.upper_arm_flexion, ctx)
    lower_arm = lower_arm_component(arm.elbow_flexion, ctx)
    wrist = wrist_component(arm.wrist_flexion, ctx)
    twist = wrist_twist_component(ctx)

    neck = neck_component(angles.neck_flexion, ctx)
    trunk = trunk_component(angles.trunk_flexion, ctx)
    legs = legs_component(ctx)

    muscle, muscle_reasons = muscle_use_score(ctx)
    force, force_band = force_score(ctx)

    table_a = lookup_table_a(upper_arm.score, lower_arm.score, wrist.score, twist.score)
    score_a = table_a + muscle + force

    table_b = lookup_table_b(neck.score, trunk.score, legs.score)
    score_b = table_b + muscle + force

    grand = lookup_table_c(score_a, score_b)
    level = action_level(grand)
    name, advice = ACTION_LEVELS[level]

    return {
        "standard": "RULA",
        "side": side,
        "components": {
            c.name: c.to_dict()
            for c in (upper_arm, lower_arm, wrist, twist, neck, trunk, legs)
        },
        "group_a": {
            "table_a": table_a,
            "muscle_use": muscle,
            "force": force,
            "force_band": force_band,
            "score": score_a,
        },
        "group_b": {
            "table_b": table_b,
            "muscle_use": muscle,
            "force": force,
            "force_band": force_band,
            "score": score_b,
        },
        "muscle_use_reasons": muscle_reasons,
        "grand_score": grand,
        "action_level": level,
        "action_name": name,
        "action": advice,
        "risk": RISK_BY_LEVEL[level],
        "context": ctx,
    }


def score(angles, modifiers):
    """RULA for both arms; the governing side is the worse one unless pinned."""
    sides = {s: score_side(angles, modifiers, s) for s in ("left", "right")}
    if modifiers.assessed_side in ("left", "right"):
        governing = modifiers.assessed_side
    else:
        governing = max(sides, key=lambda s: (sides[s]["grand_score"], sides[s]["group_a"]["score"]))
    result = dict(sides[governing])
    result["sides"] = {s: sides[s]["grand_score"] for s in sides}
    result["detail_by_side"] = sides
    result["governing_side"] = governing
    return result
