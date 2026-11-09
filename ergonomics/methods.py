"""What each method covers, and what its own result says to do.

Methods are never added up, averaged or put on one scale: RULA tops out at 7,
REBA at 15 and a lifting index has no ceiling, so raw numbers cannot be
compared. What can be compared is how urgent each method's OWN action level
is. Every scorer already places its native score on an urgency of 0-4 using
that method's published cut-offs (``band.level`` in the tool modules, RULA's
action level, REBA's risk level). Here that urgency is used for one thing
only - putting the most urgent method first. What is shown is always the
method's own score, its own action level and its own wording.

    describe("niosh", run_tool("niosh", inputs))
    -> {"name": "NIOSH lifting equation", "area": "Lower back (lifting)",
        "score_text": "LI 2.4", "label": "LI over 2", "action": "...", "urgency": 3}
"""

from .tools.owas import CATEGORY_TEXT

# name, body area covered, and the top of the score scale (None = open-ended)
METHODS = {
    "rula": ("RULA", "Upper limb (neck, shoulders, arms and wrists)", 7),
    "reba": ("REBA", "Whole body", 15),
    "owas": ("OWAS", "Whole body (back, arms and legs)", 4),
    "niosh": ("NIOSH lifting equation", "Lower back (lifting)", None),
    "niosh_cli": ("NIOSH composite lifting index", "Lower back (several lifts)", None),
    "kim": ("KIM-LHC", "Lower back and whole body (lifting, holding, carrying)", None),
    "rapp": ("RAPP", "Back, shoulders and arms (pushing and pulling)", None),
    "strain_index": ("Strain Index", "Hand and wrist", None),
    "art": ("HSE ART", "Arms, hands and wrists (repetitive work)", None),
    "rosa": ("ROSA", "Neck, back, arms and hands at a computer", 10),
    "biomech": ("L5/S1 load model", "Lower back (spinal compression)", None),
    "fit": ("Workstation fit", "Whole body (work height, reach, screen)", None),
}

# Each method's own reading of its result, indexed by the urgency (0-4) its
# tool module assigns from that method's thresholds - see the module named.
OWN_ACTION = {
    "niosh": [  # niosh.li_level: 0.7 / 1.0 / 2.0 / 3.0
        ("LI under 0.7", "Acceptable for nearly all workers."),
        ("LI 0.7 to 1.0", "Acceptable for most workers. Keep the lifting index at or under 1."),
        ("LI over 1", "Increased risk for some workers. Redesign the lift."),
        ("LI over 2", "High risk for many workers. Redesign the lift soon."),
        ("LI over 3", "High risk for most workers. Redesign the lift now."),
    ],
    "strain_index": [  # strain_index.si_level: 1.5 / 3 / 7 / 13
        ("SI 1.5 or less", "Safe."),
        ("SI 1.5 to 3", "Probably safe."),
        ("SI 3 to 7", "Uncertain. Reduce the force, the repetition or the wrist posture."),
        ("SI over 7", "Hazardous. Redesign the task."),
        ("SI over 13", "Hazardous. Redesign the task now."),
    ],
    "kim": [  # kim: risk ranges at 10 / 25 / 50 (KIM-LHC, BAuA)
        ("Risk range 1", "Low load. Physical overload is unlikely."),
        ("Risk range 1", "Low load. Physical overload is unlikely."),
        ("Risk range 2", "Increased load. Overload is possible for less resilient workers; redesign helps them."),
        ("Risk range 3", "Highly increased load. Overload is possible for normally resilient workers; redesign is recommended."),
        ("Risk range 4", "High load. Overload is likely; redesign is necessary."),
    ],
    "rosa": [  # rosa: final score, action threshold 5
        ("ROSA 2 or less", "No change needed."),
        ("ROSA 3 to 4", "Below the action threshold of 5. Improve if it is cheap."),
        ("ROSA 5", "At the action threshold. Change the workstation."),
        ("ROSA 6 to 7", "Above the action threshold. Change the workstation soon."),
        ("ROSA 8 or more", "Well above the action threshold. Change the workstation now."),
    ],
    "art": [  # art: exposure bands 12 / 22 (HSE), 30
        ("No exposure", "No repetitive arm work recorded."),
        ("Exposure under 12", "Low level of risk."),
        ("Exposure 12 to 21", "Medium level of risk. Examine the task closely."),
        ("Exposure 22 or more", "High level of risk. Prompt action needed."),
        ("Exposure 30 or more", "High level of risk. Act now."),
    ],
    "rapp": [  # rapp: worst factor colour (HSE)
        ("All factors green", "Low level of risk."),
        ("All factors green", "Low level of risk."),
        ("Worst factor amber", "Medium level of risk. Examine the task closely."),
        ("Worst factor red", "High level of risk. Prompt action needed."),
        ("Worst factor purple", "Very high level of risk. This may be a serious risk of injury."),
    ],
    "biomech": [  # biomech: 2500 N / action limit 3400 N / 4500 N / maximum permissible 6400 N
        ("Under 2500 N", "Well within the NIOSH action limit of 3400 N."),
        ("Under 3400 N", "Within the NIOSH action limit of 3400 N."),
        ("Over 3400 N", "Over the NIOSH action limit. Redesign the task."),
        ("Over 4500 N", "Approaching the maximum permissible limit of 6400 N. Redesign soon."),
        ("Over 6400 N", "Over the maximum permissible limit. Stop and redesign now."),
    ],
    "fit": [  # fit: mismatch 5 / 12 cm
        ("Fits the worker", "Work height, reach and screen suit this worker."),
        ("Within 5 cm", "Close to the targets for this worker."),
        ("5 to 12 cm off", "Adjust the workstation to this worker."),
        ("More than 12 cm off", "Change the workstation for this worker."),
        ("More than 12 cm off", "Change the workstation for this worker."),
    ],
}
OWN_ACTION["niosh_cli"] = [(label.replace("LI", "CLI"), text) for label, text in OWN_ACTION["niosh"]]

def describe(tool_id, result):
    """One method's own score, own action level and body area, plus its urgency."""
    name, area, top = METHODS.get(tool_id, (tool_id, "", None))
    score = result.get("score")
    if tool_id == "rula":
        score = result["grand_score"]
        urgency = int(result["action_level"])
        label, action = "Action level %d" % urgency, result["action"]
    elif tool_id == "reba":
        score = result["reba_score"]
        urgency = int(result["risk_level"])
        label, action = "%s risk" % result["risk"].capitalize(), result["action"]
    elif tool_id == "owas":
        urgency = int(result["band"]["level"])
        label, action = "Action category %d" % score, CATEGORY_TEXT.get(score, result["band"]["action"])
    else:
        urgency = int(result["band"]["level"])
        if tool_id.startswith("niosh") and score is None:
            label, action = "Outside the equation", "The lift is outside the equation's limits. Redesign it now."
        elif tool_id in OWN_ACTION:
            label, action = OWN_ACTION[tool_id][max(0, min(4, urgency))]
        else:
            label, action = result["band"]["label"].capitalize(), result["band"]["action"]

    minimum = bool(result.get("is_minimum"))
    if score is None:
        score_text = "n/a"
    elif top:
        score_text = "%s%g/%d" % ("≥" if minimum else "", score, top)
    else:
        # "L5/S1 compression (N)" + 3759 -> "L5/S1 compression 3759 N"
        label_text, _, unit = (result.get("score_label") or "").partition(" (")
        score_text = "%s %g %s" % (label_text, score, unit.rstrip(")"))
    return {"id": tool_id, "name": name, "area": area, "score": score, "max": top,
            "score_text": score_text.strip(), "is_minimum": minimum,
            "label": label, "action": action, "urgency": urgency}


def rank(described):
    """Most urgent own action level first; ties keep the order given."""
    return sorted(described, key=lambda m: -m["urgency"])


# The dashboard keeps one label per workstation to order the work - never a score.
PRIORITY_NOTE = "Priority label for ordering fixes only. It is not a combined risk score."
PRIORITY_LABELS = ["No action", "Monitor", "Plan a fix", "Fix soon", "Fix first"]
