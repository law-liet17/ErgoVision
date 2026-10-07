"""Shared vocabulary for every assessment tool.

Each tool keeps its own native score (a NIOSH lifting index, a REBA total, a
ROSA score...) *and* maps it onto one common action band, so unlike tools can
sit side by side in a risk register and be ranked together.

    level 0  negligible   no action needed
    level 1  low          monitor; improve if cheap
    level 2  medium       action needed, plan it
    level 3  high         action needed soon
    level 4  very high    stop / redesign now
"""

BANDS = [
    ("negligible", "No action needed."),
    ("low", "Acceptable; improve if the change is cheap. Re-check when the task changes."),
    ("medium", "Action needed. Plan a change and re-assess."),
    ("high", "Action needed soon. Prioritise this workstation."),
    ("very high", "Action needed now. Redesign or stop the task."),
]

COLOURS = ["#4ade80", "#9be15d", "#ffc53d", "#ff6b6b", "#c03cff"]


def band(level):
    level = int(max(0, min(4, level)))
    label, action = BANDS[level]
    return {"level": level, "label": label, "action": action, "colour": COLOURS[level]}


def insight(factor, severity, title, why, actions, control="engineering", value=None):
    """A recommendation tied to the input that produced it.

    `control` follows the hierarchy of controls so the UI can order fixes:
    eliminate > substitute > engineering > administrative > ppe.
    """
    return {
        "factor": factor,
        "severity": severity,          # "critical" | "high" | "medium" | "low" | "info"
        "title": title,
        "why": why,
        "actions": actions,
        "control": control,
        "value": value,
    }


CONTROL_ORDER = {"eliminate": 0, "substitute": 1, "engineering": 2, "administrative": 3, "ppe": 4}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def sort_insights(items):
    return sorted(items, key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9),
                                        CONTROL_ORDER.get(i["control"], 9)))


def num(value, default=0.0):
    if value is None or value == "":
        return float(default)
    return float(value)


def pick(value, choices, default):
    """Coerce a form value onto an allowed set."""
    return value if value in choices else default


def clamp(value, low, high):
    return max(low, min(high, value))


def row(label, value, points, note=""):
    """One line of a worksheet-style breakdown."""
    return {"label": label, "value": value, "points": points, "note": note}
