"""ROSA - Rapid Office Strain Assessment (Sonne, Villalta & Andrews, 2012).

Section A  chair      : chair height + seat pan  vs  armrest + backrest  -> Table A (+ duration)
Section B  screen     : monitor  vs  telephone                           -> Table B
Section C  peripherals: mouse    vs  keyboard                            -> Table C
Monitor & peripherals = Table(B, C);  final ROSA = Table(chair, peripherals).
Scores run 1..10; a final score above 5 is high risk (Sonne 2012).
"""

from .common import band, clamp, insight, num, pick, row, sort_insights

# Table A: rows = armrest + backrest (2..9), cols = seat pan + chair height (2..8)
TABLE_A = {
    2: [2, 2, 3, 4, 5, 6, 7],
    3: [2, 2, 3, 4, 5, 6, 7],
    4: [3, 3, 3, 4, 5, 6, 7],
    5: [4, 4, 4, 4, 5, 6, 7],
    6: [5, 5, 5, 5, 6, 7, 8],
    7: [6, 6, 6, 7, 7, 8, 8],
    8: [7, 7, 7, 8, 8, 9, 9],
    9: [8, 8, 8, 9, 9, 9, 9],
}
# Table B: rows = telephone (0..6), cols = monitor (0..7)
TABLE_B = [
    [1, 1, 1, 2, 3, 4, 5, 6],
    [1, 1, 2, 2, 3, 4, 5, 6],
    [1, 2, 2, 3, 3, 4, 6, 7],
    [2, 2, 3, 3, 4, 5, 6, 8],
    [3, 3, 4, 4, 5, 6, 7, 8],
    [4, 4, 5, 5, 6, 7, 8, 9],
    [5, 5, 6, 7, 8, 8, 9, 9],
]
# Table C: rows = mouse (0..7), cols = keyboard (0..7)
TABLE_C = [
    [1, 1, 1, 2, 3, 4, 5, 6],
    [1, 1, 2, 3, 4, 5, 6, 7],
    [1, 2, 2, 3, 4, 5, 6, 7],
    [2, 3, 3, 3, 5, 6, 7, 8],
    [3, 4, 4, 5, 5, 6, 7, 8],
    [4, 5, 5, 6, 6, 7, 8, 9],
    [5, 6, 6, 7, 7, 8, 8, 9],
    [6, 7, 7, 8, 8, 9, 9, 9],
]

DURATION = {"lt1h": (-1, "under 1 h/day"), "1to4h": (0, "1-4 h/day"), "gt4h": (1, "over 4 h/day")}


def _dur(value):
    return DURATION[pick(value, DURATION, "1to4h")]


def _flags(inputs, key):
    """Booleans arrive as a list of ticked option ids or as key=true fields."""
    picked = inputs.get(key)
    if isinstance(picked, (list, tuple, set)):
        return set(picked)
    return {k for k, v in inputs.items() if k.startswith(key + ".") and v in (True, 1, "1", "true", "on")}


def run(inputs):
    def g(key, default=1, hi=3):
        return int(clamp(num(inputs.get(key), default), 1, hi))

    # ---------------- section A: chair ----------------------------------------
    chair_height = g("chair_height", 1, 3) + (1 if inputs.get("no_room_under_desk") else 0) \
        + (1 if inputs.get("height_not_adjustable") else 0)
    seat_pan = g("seat_pan", 1, 2) + (1 if inputs.get("pan_not_adjustable") else 0)
    armrest = g("armrest", 1, 2) + (1 if inputs.get("armrest_hard") else 0) \
        + (1 if inputs.get("armrest_too_wide") else 0) + (1 if inputs.get("armrest_not_adjustable") else 0)
    backrest = g("backrest", 1, 2) + (1 if inputs.get("surface_too_high") else 0) \
        + (1 if inputs.get("backrest_not_adjustable") else 0)
    a_col = int(clamp(chair_height + seat_pan, 2, 8))
    a_row = int(clamp(armrest + backrest, 2, 9))
    chair_dur, chair_dur_txt = _dur(inputs.get("chair_duration"))
    chair = int(clamp(TABLE_A[a_row][a_col - 2] + chair_dur, 1, 10))

    # ---------------- section B: monitor and phone ----------------------------
    monitor = g("monitor", 1, 3) + (1 if inputs.get("neck_twist") else 0) + (1 if inputs.get("glare") else 0) \
        + (1 if inputs.get("no_document_holder") else 0) + (1 if inputs.get("monitor_too_far") else 0)
    mon_dur, mon_dur_txt = _dur(inputs.get("monitor_duration"))
    monitor = int(clamp(monitor + mon_dur, 0, 7))
    phone = g("phone", 1, 2) + (2 if inputs.get("neck_shoulder_hold") else 0) + (1 if inputs.get("no_handsfree") else 0)
    phone_dur, phone_dur_txt = _dur(inputs.get("phone_duration"))
    phone = int(clamp(phone + phone_dur, 0, 6))
    section_b = TABLE_B[phone][monitor]

    # ---------------- section C: mouse and keyboard ---------------------------
    mouse = g("mouse", 1, 2) + (2 if inputs.get("mouse_different_surface") else 0) \
        + (1 if inputs.get("pinch_grip") else 0) + (1 if inputs.get("hard_palm_rest") else 0)
    mouse_dur, mouse_dur_txt = _dur(inputs.get("mouse_duration"))
    mouse = int(clamp(mouse + mouse_dur, 0, 7))
    keyboard = g("keyboard", 1, 2) + (1 if inputs.get("wrist_deviation") else 0) \
        + (1 if inputs.get("keyboard_too_high") else 0) + (1 if inputs.get("reaching_overhead") else 0) \
        + (1 if inputs.get("platform_not_adjustable") else 0)
    key_dur, key_dur_txt = _dur(inputs.get("keyboard_duration"))
    keyboard = int(clamp(keyboard + key_dur, 0, 7))
    section_c = TABLE_C[mouse][keyboard]

    peripherals = max(section_b, section_c)     # the published grand tables are max() lookups
    final = max(chair, peripherals)
    lvl = 0 if final <= 2 else 1 if final <= 4 else 2 if final == 5 else 3 if final <= 7 else 4

    breakdown = [
        row("Chair height", "", chair_height), row("Seat pan depth", "", seat_pan),
        row("Armrests", "", armrest), row("Backrest", "", backrest),
        row("Chair (Table A + duration)", chair_dur_txt, chair),
        row("Monitor", mon_dur_txt, monitor), row("Telephone", phone_dur_txt, phone),
        row("Section B (monitor x phone)", "", section_b),
        row("Mouse", mouse_dur_txt, mouse), row("Keyboard", key_dur_txt, keyboard),
        row("Section C (mouse x keyboard)", "", section_c),
        row("Monitor and peripherals", "max of B, C", peripherals),
        row("ROSA final score", "max of chair, peripherals", final),
    ]

    notes = []
    if chair >= 4:
        worst = max((chair_height, "chair height"), (seat_pan, "seat pan"), (armrest, "armrests"), (backrest, "backrest"))
        notes.append(insight("chair", "high" if chair >= 6 else "medium", "Chair set-up drives the score",
            "Chair score %d; the worst element is the %s (%d)." % (chair, worst[1], worst[0]),
            ["Set seat height so the knees are at 90 deg with feet flat (or add a footrest).",
             "Seat pan: 2-3 finger widths between the seat edge and the back of the knee.",
             "Armrests at relaxed-elbow height, soft, close enough that the shoulders stay down.",
             "Backrest reclined 95-110 deg with lumbar support in the small of the back.",
             "If the chair cannot be adjusted to fit, replace it - it is the cheapest fix on this list."],
            "engineering", chair))
    if monitor >= 3:
        notes.append(insight("monitor", "high" if monitor >= 5 else "medium", "Monitor position",
            "Monitor score %d." % monitor,
            ["Top of the screen at eye height, about an arm's length away.",
             "Centre the primary screen; add a document holder beside it.",
             "Kill glare with blinds, screen angle or a matte filter."], "engineering", monitor))
    if phone >= 3:
        notes.append(insight("phone", "medium", "Telephone use",
            "Telephone score %d." % phone,
            ["Provide a headset for anyone on the phone more than about 2 hours a day.",
             "Keep the phone within 30 cm so it can be reached without leaning."], "engineering", phone))
    if mouse >= 3:
        notes.append(insight("mouse", "medium", "Mouse position or grip",
            "Mouse score %d." % mouse,
            ["Mouse on the same surface and level as the keyboard, directly beside it.",
             "Size the mouse to the hand; a compact keyboard shortens the reach."], "engineering", mouse))
    if keyboard >= 3:
        notes.append(insight("keyboard", "medium", "Keyboard posture",
            "Keyboard score %d." % keyboard,
            ["Keyboard flat or negatively tilted, at elbow height, wrists straight.",
             "Move frequently used items off the shelf above the desk."], "engineering", keyboard))
    if final > 5:
        notes.insert(0, insight("overall", "high", "Workstation needs changing now",
            "ROSA %d is above the 5-point threshold that Sonne et al. associate with discomfort." % final,
            ["Fix the highest-scoring section first; re-assess with the worker seated after the change."],
            "administrative", final))
    if not notes:
        notes.append(insight("overall", "info", "Workstation is set up well",
            "ROSA %d." % final, ["Re-check after any equipment change or if discomfort is reported."], "administrative"))

    return {
        "tool": "rosa",
        "score": final,
        "score_label": "ROSA score",
        "band": band(lvl),
        "sections": {"chair": chair, "monitor": monitor, "phone": phone, "mouse": mouse, "keyboard": keyboard,
                     "section_b": section_b, "section_c": section_c, "peripherals": peripherals},
        "breakdown": breakdown,
        "insights": sort_insights(notes),
        "summary": "ROSA %d (chair %d, monitor/peripherals %d)" % (final, chair, peripherals),
    }


_DUR = [["lt1h", "under 1 h/day"], ["1to4h", "1-4 h/day"], ["gt4h", "over 4 h/day"]]

SCHEMA = {
    "id": "rosa",
    "name": "ROSA - office workstation",
    "short": "ROSA",
    "category": "office",
    "standard": "Sonne, Villalta & Andrews (2012)",
    "validation": "transcribed",
    "description": "Rapid Office Strain Assessment: chair, monitor, telephone, mouse and keyboard scored with duration modifiers.",
    "output": "ROSA 1-10. Above 5 = high risk, change the workstation.",
    "groups": [
        {"title": "Chair", "fields": [
            {"key": "chair_height", "label": "Chair height", "type": "select", "default": 1,
             "options": [[1, "Knees at 90 deg, feet flat"], [2, "Too low or too high"], [3, "Feet do not reach the floor"]]},
            {"key": "no_room_under_desk", "label": "No room for legs under the desk", "type": "bool"},
            {"key": "height_not_adjustable", "label": "Height not adjustable", "type": "bool"},
            {"key": "seat_pan", "label": "Seat pan depth", "type": "select", "default": 1,
             "options": [[1, "About 8 cm behind the knee"], [2, "Too long or too short"]]},
            {"key": "pan_not_adjustable", "label": "Pan not adjustable", "type": "bool"},
            {"key": "armrest", "label": "Armrests", "type": "select", "default": 1,
             "options": [[1, "Elbows supported, shoulders relaxed"], [2, "Too high / low, shoulders shrugged or unsupported"]]},
            {"key": "armrest_hard", "label": "Hard or damaged armrest surface", "type": "bool"},
            {"key": "armrest_too_wide", "label": "Armrests too wide", "type": "bool"},
            {"key": "armrest_not_adjustable", "label": "Armrests not adjustable", "type": "bool"},
            {"key": "backrest", "label": "Backrest", "type": "select", "default": 1,
             "options": [[1, "Lumbar support, reclined 95-110 deg"], [2, "No lumbar support, wrong angle, or leaning forward"]]},
            {"key": "surface_too_high", "label": "Work surface too high (shoulders shrugged)", "type": "bool"},
            {"key": "backrest_not_adjustable", "label": "Backrest not adjustable", "type": "bool"},
            {"key": "chair_duration", "label": "Time in the chair", "type": "select", "default": "gt4h", "options": _DUR},
        ]},
        {"title": "Monitor and telephone", "fields": [
            {"key": "monitor", "label": "Monitor", "type": "select", "default": 1,
             "options": [[1, "Eye level, arm's length"], [2, "Too low (looking down > 30 deg)"], [3, "Too high (neck extended)"]]},
            {"key": "neck_twist", "label": "Neck twisted > 30 deg to see it", "type": "bool"},
            {"key": "glare", "label": "Glare on the screen", "type": "bool"},
            {"key": "no_document_holder", "label": "Documents used with no holder", "type": "bool"},
            {"key": "monitor_too_far", "label": "Monitor too far away", "type": "bool"},
            {"key": "monitor_duration", "label": "Time on the monitor", "type": "select", "default": "gt4h", "options": _DUR},
            {"key": "phone", "label": "Telephone", "type": "select", "default": 1,
             "options": [[1, "Headset or one hand, neutral neck"], [2, "Reach over 30 cm to the phone"]]},
            {"key": "neck_shoulder_hold", "label": "Phone held between neck and shoulder", "type": "bool"},
            {"key": "no_handsfree", "label": "No hands-free option", "type": "bool"},
            {"key": "phone_duration", "label": "Time on the phone", "type": "select", "default": "1to4h", "options": _DUR},
        ]},
        {"title": "Mouse and keyboard", "fields": [
            {"key": "mouse", "label": "Mouse", "type": "select", "default": 1,
             "options": [[1, "In line with the shoulder"], [2, "Reaching to the mouse"]]},
            {"key": "mouse_different_surface", "label": "Mouse and keyboard on different surfaces", "type": "bool"},
            {"key": "pinch_grip", "label": "Pinch grip on a small mouse", "type": "bool"},
            {"key": "hard_palm_rest", "label": "Hard palm rest in front of the mouse", "type": "bool"},
            {"key": "mouse_duration", "label": "Time on the mouse", "type": "select", "default": "gt4h", "options": _DUR},
            {"key": "keyboard", "label": "Keyboard", "type": "select", "default": 1,
             "options": [[1, "Wrists straight, shoulders relaxed"], [2, "Wrists extended over 15 deg"]]},
            {"key": "wrist_deviation", "label": "Wrists deviated sideways", "type": "bool"},
            {"key": "keyboard_too_high", "label": "Keyboard too high (shoulders shrugged)", "type": "bool"},
            {"key": "reaching_overhead", "label": "Reaching to items overhead", "type": "bool"},
            {"key": "platform_not_adjustable", "label": "Keyboard platform not adjustable", "type": "bool"},
            {"key": "keyboard_duration", "label": "Time on the keyboard", "type": "select", "default": "gt4h", "options": _DUR},
        ]},
    ],
}
