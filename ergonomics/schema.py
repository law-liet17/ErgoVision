"""Task context that a photograph cannot show, plus the score breakdown types.

RULA and REBA are not purely geometric. Roughly a third of both worksheets asks
about things no pose model can see: how heavy the load is, whether the posture
is held or repeated, how good the hand grip is, whether the arm is resting on
something. Those arrive from the UI as :class:`Modifiers`.

Anything that *is* visible (twist, side bend, abduction, wrist deviation,
sitting, uneven legs) is auto-detected in :mod:`.angles`; the matching modifier
field defaults to ``None`` meaning "trust the detector", and any explicit
``True``/``False`` from the user overrides it.
"""

from dataclasses import dataclass, field, fields
from typing import Optional

COUPLING_CHOICES = ("good", "fair", "poor", "unacceptable")


@dataclass
class Modifiers:
    """User-supplied task context. ``None`` means "auto-detect if possible"."""

    # --- posture context --------------------------------------------------
    sitting: Optional[bool] = None
    legs_supported: Optional[bool] = None      # RULA legs: supported/balanced -> 1 else 2
    legs_bilateral: Optional[bool] = None      # REBA legs: both feet loaded -> 1 else 2
    arm_supported: Optional[bool] = None       # arm resting / person leaning -> upper arm -1
    shoulder_raised: Optional[bool] = None     # upper arm +1
    arm_abducted: Optional[bool] = None        # upper arm +1 (auto-detected)
    arm_across_midline: Optional[bool] = None  # RULA lower arm +1
    wrist_deviated: Optional[bool] = None      # wrist +1 (auto-detected)
    wrist_twist_end_range: Optional[bool] = None   # RULA wrist twist: 1 mid-range, 2 end-range
    trunk_twisted: Optional[bool] = None
    trunk_side_bent: Optional[bool] = None
    neck_twisted: Optional[bool] = None
    neck_side_bent: Optional[bool] = None

    # --- load / force -----------------------------------------------------
    load_kg: float = 0.0
    load_static_or_repeated: bool = False   # RULA: the 2-10 kg band splits on this
    shock_or_rapid_buildup: bool = False    # RULA +1 band, REBA +1

    # --- muscle use / activity -------------------------------------------
    static_posture: bool = False       # any part held > 1 minute
    repeated_actions: bool = False     # repeated more than 4x per minute
    rapid_large_changes: bool = False  # REBA only: rapid large range changes / unstable base

    # --- grip -------------------------------------------------------------
    coupling: str = "good"             # REBA only

    # --- which arm governs the assessment --------------------------------
    assessed_side: str = "auto"        # "left", "right" or "auto" (worst case)

    def __post_init__(self):
        if self.coupling not in COUPLING_CHOICES:
            raise ValueError(
                "coupling must be one of %s, got %r" % (", ".join(COUPLING_CHOICES), self.coupling)
            )
        if self.assessed_side not in ("auto", "left", "right"):
            raise ValueError("assessed_side must be 'auto', 'left' or 'right'")
        self.load_kg = float(self.load_kg or 0.0)

    @classmethod
    def from_dict(cls, data):
        """Build from a (possibly partial, possibly noisy) JSON payload."""
        data = data or {}
        known = {f.name for f in fields(cls)}
        clean = {}
        for key, value in data.items():
            if key not in known or value is None or value == "":
                continue
            if key in ("load_kg",):
                clean[key] = float(value)
            elif key in ("coupling", "assessed_side"):
                clean[key] = str(value)
            else:
                clean[key] = _as_bool(value)
        return cls(**clean)

    # --- resolution against auto-detected flags --------------------------
    def resolved(self, flags, side):
        """Merge user input with detector output for one arm.

        Returns a plain dict of the booleans/numbers the scorers consume.
        """
        flags = flags or {}

        def pick(user_value, auto_key, default=False):
            if user_value is not None:
                return bool(user_value)
            if auto_key is None:
                return default
            return bool(flags.get(auto_key, default))

        sitting = pick(self.sitting, "probably_sitting")
        return {
            "sitting": sitting,
            "legs_supported": pick(
                self.legs_supported, None, default=not flags.get("legs_uneven", False)
            ),
            "legs_bilateral": pick(
                self.legs_bilateral, None,
                default=sitting or not flags.get("legs_uneven", False),
            ),
            "arm_supported": pick(self.arm_supported, None),
            # Not auto-applied: the detector can only hint at raised shoulders,
            # so scoring waits for the user to confirm it.
            "shoulder_raised": pick(self.shoulder_raised, None),
            "arm_abducted": pick(self.arm_abducted, f"{side}_arm_abducted"),
            "arm_across_midline": pick(self.arm_across_midline, None),
            "wrist_deviated": pick(self.wrist_deviated, f"{side}_wrist_deviated"),
            "wrist_twist_end_range": pick(self.wrist_twist_end_range, None),
            "trunk_twisted": pick(self.trunk_twisted, "trunk_twisted"),
            "trunk_side_bent": pick(self.trunk_side_bent, "trunk_side_bent"),
            "neck_twisted": pick(self.neck_twisted, "neck_twisted"),
            "neck_side_bent": pick(self.neck_side_bent, "neck_side_bent"),
            "load_kg": self.load_kg,
            "load_static_or_repeated": bool(self.load_static_or_repeated),
            "shock_or_rapid_buildup": bool(self.shock_or_rapid_buildup),
            "static_posture": bool(self.static_posture),
            "repeated_actions": bool(self.repeated_actions),
            "rapid_large_changes": bool(self.rapid_large_changes),
            "coupling": self.coupling,
        }


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


@dataclass
class Component:
    """One row of a worksheet: the angle, the band it fell in, the add-ons."""

    name: str
    score: int
    base: int
    angle: Optional[float] = None
    band: str = ""
    adjustments: list = field(default_factory=list)  # [{"label":..., "delta": +1}]

    def to_dict(self):
        return {
            "name": self.name,
            "score": self.score,
            "base": self.base,
            "angle": self.angle,
            "band": self.band,
            "adjustments": self.adjustments,
        }


def clamp(value, low, high):
    return max(low, min(high, value))


def build_component(name, angle, base, band, adjustments, low=1, high=None):
    """Apply adjustments to a base band score and clamp into the table range."""
    total = base + sum(a["delta"] for a in adjustments)
    return Component(
        name=name,
        score=int(clamp(total, low, high if high is not None else total)),
        base=int(base),
        angle=None if angle is None else round(float(angle), 1),
        band=band,
        adjustments=adjustments,
    )
