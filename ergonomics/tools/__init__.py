"""Tool registry: every assessment method the platform can run.

    from ergonomics.tools import TOOLS, run_tool, catalogue

    result = run_tool("niosh", {"load_kg": 15, ...})

Each module exposes `run(inputs) -> result` and a `SCHEMA` the UI uses to
build its form. Results always carry `score`, `band` (the common 0-4 action
band from :mod:`.common`), `breakdown` rows and `insights`.

Validation status, shown in the UI:
    verified    - tables/equations checked by unit tests against the published source
    transcribed - transcribed from the published sheet; confirm before regulatory use
    model       - an engineering model or design rule, not a scored worksheet
"""

from . import art, biomech, fit, kim, niosh, owas, rapp, rosa, strain_index

TOOLS = {
    m.SCHEMA["id"]: m for m in (niosh, strain_index, rosa, owas, art, rapp, kim, biomech, fit)
}

CATEGORIES = {
    "posture": "Posture",
    "manual_handling": "Manual handling",
    "repetition": "Repetitive work",
    "office": "Office / screen work",
    "biomechanics": "Biomechanics",
    "design": "Workstation design",
}

# The vision-based tools live in the posture lab, but they belong in the catalogue too.
VISION_TOOLS = [
    {"id": "rula", "name": "RULA", "short": "RULA", "category": "posture",
     "standard": "McAtamney & Corlett (1993)", "validation": "verified",
     "description": "Rapid Upper Limb Assessment from measured joint angles (photo, clip or webcam).",
     "output": "Grand score 1-7 and action level 1-4.", "route": "lab"},
    {"id": "reba", "name": "REBA", "short": "REBA", "category": "posture",
     "standard": "Hignett & McAtamney (2000)", "validation": "verified",
     "description": "Rapid Entire Body Assessment from measured joint angles, with load, coupling and activity.",
     "output": "REBA score 1-15 and risk level.", "route": "lab"},
]


def catalogue():
    items = []
    for tool_id, module in TOOLS.items():
        schema = dict(module.SCHEMA)
        schema["route"] = "tool"
        items.append(schema)
    items.extend(VISION_TOOLS)
    return {"tools": items, "categories": CATEGORIES}


def run_tool(tool_id, inputs):
    if tool_id not in TOOLS:
        raise KeyError("unknown tool %r" % tool_id)
    return TOOLS[tool_id].run(inputs or {})


__all__ = ["TOOLS", "CATEGORIES", "VISION_TOOLS", "catalogue", "run_tool"]
