"""Moore-Garg Strain Index (1995) for distal upper-extremity disorders.

    SI = IE x DE x EM x HWP x SW x DD

Six task variables, each rated into a multiplier from the published table.
SI <= 3 is generally safe, 3-7 uncertain, > 7 hazardous.
"""

from .common import band, insight, num, pick, row, sort_insights

INTENSITY = {  # % maximal strength, Borg
    "light": (1.0, "light (< 10% MVC, barely noticeable)"),
    "somewhat_hard": (3.0, "somewhat hard (10-29%, noticeable)"),
    "hard": (6.0, "hard (30-49%, obvious effort)"),
    "very_hard": (9.0, "very hard (50-79%, substantial)"),
    "near_maximal": (13.0, "near maximal (>= 80%)"),
}
POSTURE = {
    "very_good": (1.0, "perfectly neutral"),
    "good": (1.0, "near neutral"),
    "fair": (1.5, "non-neutral"),
    "bad": (2.0, "marked deviation"),
    "very_bad": (3.0, "near extreme"),
}
SPEED = {
    "very_slow": (1.0, "very slow (<= 80% of normal)"),
    "slow": (1.0, "slow (81-90%)"),
    "fair": (1.0, "fair (91-100%)"),
    "fast": (1.5, "fast (101-115%, rushed but keeps up)"),
    "very_fast": (2.0, "very fast (> 115%, cannot keep up)"),
}


def duration_multiplier(pct):
    if pct < 10:
        return 0.5
    if pct < 30:
        return 1.0
    if pct < 50:
        return 1.5
    if pct < 80:
        return 2.0
    return 3.0


def efforts_multiplier(per_min):
    if per_min < 4:
        return 0.5
    if per_min < 9:
        return 1.0
    if per_min < 15:
        return 1.5
    if per_min < 20:
        return 2.0
    return 3.0


def daily_multiplier(hours):
    if hours < 1:
        return 0.25
    if hours < 2:
        return 0.5
    if hours < 4:
        return 0.75
    if hours <= 8:          # a standard 8 h shift is the 1.0 band; only overtime beyond it is 1.5
        return 1.0
    return 1.5


def si_level(si):
    if si <= 1.5:
        return 0
    if si <= 3.0:
        return 1
    if si <= 7.0:
        return 2
    if si <= 13.0:
        return 3
    return 4


def run(inputs):
    intensity = pick(inputs.get("intensity"), INTENSITY, "somewhat_hard")
    duration_pct = max(0.0, min(100.0, num(inputs.get("duration_pct"), 30)))
    efforts = max(0.0, num(inputs.get("efforts_per_min"), 6))
    posture = pick(inputs.get("posture"), POSTURE, "fair")
    speed = pick(inputs.get("speed"), SPEED, "fair")
    hours = max(0.0, num(inputs.get("hours_per_day"), 6))

    ie, ie_txt = INTENSITY[intensity]
    de = duration_multiplier(duration_pct)
    em = efforts_multiplier(efforts)
    hwp, hwp_txt = POSTURE[posture]
    sw, sw_txt = SPEED[speed]
    dd = daily_multiplier(hours)
    si = ie * de * em * hwp * sw * dd
    lvl = si_level(si)

    breakdown = [
        row("Intensity of exertion (IE)", ie_txt, ie),
        row("Duration of exertion (DE)", "%.0f%% of cycle" % duration_pct, de),
        row("Efforts per minute (EM)", "%.1f /min" % efforts, em),
        row("Hand/wrist posture (HWP)", hwp_txt, hwp),
        row("Speed of work (SW)", sw_txt, sw),
        row("Duration per day (DD)", "%.1f h" % hours, dd),
        row("Strain Index", "product", round(si, 2)),
    ]

    notes = []
    if ie >= 6:
        notes.append(insight("intensity", "critical" if ie >= 9 else "high",
            "Exertions are forceful",
            "Intensity multiplier %.0f is the single largest term in the index; force is the "
            "strongest predictor of tendon disorders." % ie,
            ["Power tools, fixtures or jigs so the hand no longer supplies the force.",
             "Sharper tools, lower-friction feeds, better-fitting gloves to cut the grip force needed.",
             "Redesign the handle so a power grip replaces a pinch grip."], "engineering", ie))
    if de >= 2.0:
        notes.append(insight("duration", "high", "Exertion occupies most of the cycle",
            "%.0f%% of the cycle under load (DE %.1f). Tendons need slack time within every cycle to recover." % (duration_pct, de),
            ["Insert non-exertion elements into the cycle (auto-feed, self-holding fixtures).",
             "Alternate hands or alternate tasks so each hand rests within the cycle."], "engineering", de))
    if em >= 1.5:
        notes.append(insight("efforts", "high" if em >= 2 else "medium", "High effort frequency",
            "%.0f efforts/min (EM %.1f)." % (efforts, em),
            ["Combine repeated actions into one (multi-driver, batch fasteners).",
             "Job rotation to a task that uses different muscle groups; micro-breaks every 20-30 min."],
            "administrative", em))
    if hwp >= 1.5:
        notes.append(insight("posture", "medium" if hwp < 2 else "high", "Wrist is out of neutral",
            "Posture multiplier %.1f." % hwp,
            ["Bend the tool, not the wrist: pistol grip for work at elbow height, in-line for work at shoulder height.",
             "Tilt the workpiece or fixture so the hand approaches in line with the forearm."], "engineering", hwp))
    if sw >= 1.5:
        notes.append(insight("speed", "medium", "Pace is faster than the worker can sustain",
            "Speed multiplier %.1f." % sw,
            ["Decouple the worker from the line pace with a small buffer.",
             "Allow self-paced work where quality permits."], "administrative", sw))
    if dd >= 1.5:
        notes.append(insight("daily", "medium", "Exposure exceeds a normal shift",
            "%.1f h/day (DD %.1f)." % (hours, dd),
            ["Limit overtime on this task; rotate across the shift."], "administrative", dd))
    if not notes:
        notes.append(insight("task", "info", "Task is probably safe",
            "SI %.2f: all six multipliers are in their low bands." % si,
            ["Re-assess if cycle time, force or shift length change."], "administrative"))

    return {
        "tool": "strain_index",
        "score": round(si, 2),
        "score_label": "Strain Index",
        "band": band(lvl),
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "SI %.2f (%s)" % (si, ["safe", "safe", "uncertain", "hazardous", "hazardous"][lvl]),
    }


SCHEMA = {
    "id": "strain_index",
    "name": "Strain Index",
    "short": "SI",
    "category": "repetition",
    "standard": "Moore & Garg (1995)",
    "validation": "verified",
    "description": "Distal upper-limb risk from six task variables: force intensity, duration, frequency, wrist posture, pace and daily exposure.",
    "output": "Strain Index. <= 3 safe, 3-7 uncertain, > 7 hazardous.",
    "groups": [
        {"title": "Effort", "fields": [
            {"key": "intensity", "label": "Intensity of exertion", "type": "select", "default": "somewhat_hard",
             "options": [[k, v[1]] for k, v in INTENSITY.items()]},
            {"key": "duration_pct", "label": "Exertion as % of cycle", "type": "number", "unit": "%", "min": 0, "max": 100, "default": 30},
            {"key": "efforts_per_min", "label": "Efforts per minute", "type": "number", "min": 0, "max": 60, "step": 0.5, "default": 6},
        ]},
        {"title": "Posture and pace", "fields": [
            {"key": "posture", "label": "Hand / wrist posture", "type": "select", "default": "fair",
             "options": [[k, v[1]] for k, v in POSTURE.items()]},
            {"key": "speed", "label": "Speed of work", "type": "select", "default": "fair",
             "options": [[k, v[1]] for k, v in SPEED.items()]},
            {"key": "hours_per_day", "label": "Hours per day on this task", "type": "number", "unit": "h", "min": 0, "max": 12, "step": 0.5, "default": 6},
        ]},
    ],
}
