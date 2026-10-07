"""Static sagittal-plane biomechanical model of the low back and shoulder.

A two-segment, single-equivalent-muscle model in the tradition of Chaffin's
static strength models: the moment at L5/S1 is balanced by the erector spinae
acting on a 5 cm lever, and the resulting muscle force is what compresses the
disc. It is an engineering estimate, not a 3D dynamic simulation, and it is
compared against the NIOSH (1981) compression criteria:

    action limit  3400 N       maximum permissible limit  6400 N

Segment lengths follow Drillis & Contini (1966) stature ratios; segment mass
fractions follow Dempster (via Winter, Biomechanics and Motor Control).
"""

import math

from .common import band, clamp, insight, num, pick, row, sort_insights

G = 9.81
ES_LEVER_M = 0.05                 # erector spinae moment arm about L5/S1
ACTION_LIMIT_N = 3400.0
MAX_PERMISSIBLE_N = 6400.0

# stature ratios (Drillis & Contini)
R_TRUNK = 0.288                   # L5/S1 (hip) to shoulder
R_UPPER_ARM = 0.186
R_FOREARM = 0.146
R_HAND = 0.108
# mass fractions (Dempster) and proximal COM ratios
M_UPPER_ARM, C_UPPER_ARM = 0.028, 0.436
M_FOREARM, C_FOREARM = 0.016, 0.430
M_HAND, C_HAND = 0.006, 0.506
M_HAT = 0.678                     # head, arms, trunk above the hips
M_UPPER_BODY = 0.54               # portion of HAT above L5/S1 (trunk share above the disc + head + arms)
C_UPPER_BODY = 0.45               # its centre of mass along the trunk axis from L5/S1


def run(inputs):
    mass = clamp(num(inputs.get("body_mass_kg"), 75), 30, 200)
    stature = clamp(num(inputs.get("stature_cm"), 172), 120, 220) / 100.0
    load = max(0.0, num(inputs.get("load_kg"), 10))
    trunk = clamp(num(inputs.get("trunk_flexion_deg"), 30), -30, 110)      # from vertical, + forward
    arm = clamp(num(inputs.get("upper_arm_flexion_deg"), 30), -60, 180)   # vs trunk, + forward
    elbow = clamp(num(inputs.get("elbow_flexion_deg"), 20), 0, 150)
    hands = pick(inputs.get("hands"), ("two", "one"), "two")
    hand_h_override = inputs.get("hand_horizontal_m")

    L_t, L_ua, L_fa, L_h = R_TRUNK * stature, R_UPPER_ARM * stature, R_FOREARM * stature, R_HAND * stature
    th = math.radians(trunk)
    a_abs = math.radians(trunk + arm)               # upper arm from vertical, absolute
    g_abs = math.radians(trunk + arm + elbow)       # forearm from vertical, absolute

    # horizontal offsets from the shoulder (arm hanging -> 0)
    x_ua = C_UPPER_ARM * L_ua * math.sin(a_abs)
    x_el = L_ua * math.sin(a_abs)
    x_fa = x_el + C_FOREARM * L_fa * math.sin(g_abs)
    x_hand_seg = x_el + L_fa * math.sin(g_abs) + C_HAND * L_h * math.sin(g_abs)
    x_hand = x_el + (L_fa + 0.5 * L_h) * math.sin(g_abs)

    # shoulder moment (one shoulder: its own arm plus its share of the load)
    share = 0.5 if hands == "two" else 1.0
    m_sh = G * (M_UPPER_ARM * mass * x_ua + M_FOREARM * mass * x_fa + M_HAND * mass * x_hand_seg + load * share * x_hand)

    # L5/S1: upper body lump at its COM plus arms and load out at the hands
    x_shoulder = L_t * math.sin(th)
    x_ub = C_UPPER_BODY * L_t * math.sin(th)
    if hand_h_override not in (None, ""):
        x_load = max(0.0, num(hand_h_override))
    else:
        x_load = x_shoulder + x_hand
    arms_mass = 2 * (M_UPPER_ARM + M_FOREARM + M_HAND) * mass
    x_arms = x_shoulder + (x_ua + x_fa + x_hand_seg) / 3.0
    m_l5 = G * ((M_UPPER_BODY * mass - arms_mass) * x_ub + arms_mass * x_arms + load * x_load)
    f_es = m_l5 / ES_LEVER_M
    weight_above = (M_UPPER_BODY * mass + load) * G
    compression = f_es + weight_above * math.cos(th)
    shear = weight_above * math.sin(abs(th))

    lvl = 0 if compression < 2500 else 1 if compression < ACTION_LIMIT_N else 2 if compression < 4500 \
        else 3 if compression < MAX_PERMISSIBLE_N else 4

    # rough shoulder capability reference: sustained flexion strength around 90 deg elevation
    sh_ref = 60.0 if pick(inputs.get("sex"), ("male", "female"), "male") == "male" else 40.0
    sh_pct = 100.0 * m_sh / sh_ref

    breakdown = [
        row("Trunk flexion", "%.0f deg from vertical" % trunk, round(x_ub, 3), "upper-body COM offset, m"),
        row("Hands from L5/S1", "%.2f m horizontal" % x_load, round(x_load, 3)),
        row("L5/S1 moment", "body + load", round(m_l5, 1), "N m"),
        row("Erector spinae force", "moment / 0.05 m", round(f_es, 0), "N"),
        row("Disc compression", "muscle + weight along spine", round(compression, 0), "N"),
        row("Disc shear", "weight across spine", round(shear, 0), "N"),
        row("Shoulder moment", "%s hand%s" % (hands, "s" if hands == "two" else ""), round(m_sh, 1), "N m"),
        row("NIOSH action limit", "3400 N", ACTION_LIMIT_N, "N"),
        row("NIOSH max permissible", "6400 N", MAX_PERMISSIBLE_N, "N"),
    ]

    notes = []
    if compression >= ACTION_LIMIT_N:
        notes.append(insight("compression", "critical" if compression >= MAX_PERMISSIBLE_N else "high",
            "L5/S1 compression exceeds the NIOSH action limit",
            "%.0f N estimated (AL 3400 N, MPL 6400 N). Compression is driven by the moment, and the moment by "
            "the horizontal distance of the load (%.2f m) and of the upper body (%.2f m)." % (compression, x_load, x_ub),
            ["Bring the load closer: every 10 cm nearer the body removes about %.0f N of compression at this load."
             % (load * G * 0.10 / ES_LEVER_M),
             "Reduce trunk flexion with a higher pick height; the upper body alone is %.0f N m at this angle."
             % (G * (M_UPPER_BODY * mass - arms_mass) * x_ub),
             "Lower the load or use a hoist / vacuum lifter."], "engineering", compression))
    elif compression >= 2500:
        notes.append(insight("compression", "medium", "Compression approaching the action limit",
            "%.0f N estimated." % compression,
            ["Keep the load close and the trunk upright; avoid adding frequency to this lift."], "engineering", compression))
    if shear > 1000:
        notes.append(insight("shear", "medium", "High shear on the lumbar spine",
            "%.0f N of shear from the trunk angle." % shear,
            ["Reduce trunk flexion; shear rises with the sine of the angle."], "engineering", shear))
    if sh_pct >= 50:
        notes.append(insight("shoulder", "high" if sh_pct >= 80 else "medium", "Shoulder moment is high",
            "%.1f N m per shoulder, about %.0f%% of a reference sustained capacity of %.0f N m." % (m_sh, sh_pct, sh_ref),
            ["Bring the hands in toward the shoulder; each 10 cm removes %.1f N m at this load." % (load * share * G * 0.10),
             "Support the arms or the load (armrest, tool balancer, fixture)."], "engineering", m_sh))
    if not notes:
        notes.append(insight("model", "info", "Loads are within the model's acceptable range",
            "Compression %.0f N, shoulder %.1f N m." % (compression, m_sh),
            ["Re-run with the peak load of the task, not the average."], "administrative"))

    return {
        "tool": "biomech",
        "score": round(compression),
        "score_label": "L5/S1 compression (N)",
        "band": band(lvl),
        "l5s1": {"moment_nm": round(m_l5, 1), "compression_n": round(compression), "shear_n": round(shear),
                 "erector_force_n": round(f_es), "hand_offset_m": round(x_load, 3)},
        "shoulder": {"moment_nm": round(m_sh, 1), "pct_reference": round(sh_pct), "reference_nm": sh_ref},
        "segments": {"trunk_m": round(L_t, 3), "upper_arm_m": round(L_ua, 3), "forearm_m": round(L_fa, 3)},
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "L5/S1 compression %.0f N, shoulder moment %.1f N m" % (compression, m_sh),
    }


SCHEMA = {
    "id": "biomech",
    "name": "Biomechanical load model",
    "short": "L5/S1",
    "category": "biomechanics",
    "standard": "Static sagittal model (Chaffin); NIOSH 1981 compression limits",
    "validation": "model",
    "description": "Estimates L5/S1 disc compression and shoulder moment from posture, load and anthropometry. Auto-filled from the posture lab.",
    "output": "Compression in newtons against the 3400 N action limit and 6400 N maximum.",
    "groups": [
        {"title": "Worker", "fields": [
            {"key": "body_mass_kg", "label": "Body mass", "type": "number", "unit": "kg", "min": 40, "max": 150, "default": 75},
            {"key": "stature_cm", "label": "Stature", "type": "number", "unit": "cm", "min": 140, "max": 210, "default": 172},
            {"key": "sex", "label": "Sex (shoulder reference)", "type": "select", "default": "male", "options": [["male", "Male"], ["female", "Female"]]},
        ]},
        {"title": "Posture and load", "fields": [
            {"key": "load_kg", "label": "Load in hands", "type": "number", "unit": "kg", "min": 0, "max": 80, "step": 0.5, "default": 10},
            {"key": "hands", "label": "Hands on the load", "type": "select", "default": "two", "options": [["two", "Two hands"], ["one", "One hand"]]},
            {"key": "trunk_flexion_deg", "label": "Trunk flexion", "type": "number", "unit": "deg", "min": -30, "max": 110, "default": 30},
            {"key": "upper_arm_flexion_deg", "label": "Upper arm flexion (vs trunk)", "type": "number", "unit": "deg", "min": -60, "max": 180, "default": 30},
            {"key": "elbow_flexion_deg", "label": "Elbow flexion", "type": "number", "unit": "deg", "min": 0, "max": 150, "default": 20},
            {"key": "hand_horizontal_m", "label": "Hands from L5/S1 (override)", "type": "number", "unit": "m", "min": 0, "max": 1.2, "step": 0.01,
             "help": "Leave blank to compute from the angles"},
        ]},
    ],
}
