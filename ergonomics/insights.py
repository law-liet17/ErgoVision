"""Turn scores back into workspace changes.

Every insight is tied to the thing that produced it - the measured angle and the
worksheet row it drove - so a report can always answer "why am I being told
this?". Severity is derived from the component score, not invented: a component
scoring at the top of its range is the one worth spending money on.
"""

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _sev(score, high_at, critical_at):
    if score >= critical_at:
        return "critical"
    if score >= high_at:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _insight(segment, severity, title, finding, why, actions, angle=None, score=None, ref=""):
    return {
        "segment": segment,
        "severity": severity,
        "title": title,
        "finding": finding,
        "why": why,
        "actions": actions,
        "angle": angle,
        "score": score,
        "reference": ref,
    }


def generate(angles, rula, reba, modifiers):
    """Build a prioritised list of ergonomic findings and fixes."""
    side = rula["governing_side"]
    arm = angles.side(side)
    ctx = rula["context"]
    rc = rula["components"]
    bc = reba["components"]
    sitting = ctx["sitting"]
    out = []

    # ---------------- trunk ------------------------------------------------
    trunk = angles.trunk_flexion or 0.0
    trunk_score = max(rc["trunk"]["score"], bc["trunk"]["score"])
    if trunk > 20 or trunk_score >= 3:
        out.append(_insight(
            "trunk", _sev(trunk_score, 3, 4),
            "Trunk is bent forward",
            "Trunk flexion measured at %.0f deg (RULA trunk %d, REBA trunk %d)."
            % (trunk, rc["trunk"]["score"], bc["trunk"]["score"]),
            "Forward flexion beyond 20 deg loads the lumbar discs and the back "
            "extensors continuously, and it is the single biggest driver of both scores here.",
            [
                "Raise the work surface or the workpiece so the hands sit near elbow height "
                "(a 20-30 cm lift usually removes most of the bend).",
                "Bring the work forward: reduce the horizontal reach so the worker does not "
                "lean in over an obstruction.",
                "Tilt bins, containers or pallets towards the worker so the contents come to "
                "the hands instead of the hands going down into the box.",
                "Use a lift table, scissor lift or spring-loaded pallet base so the top of the "
                "stack stays between knuckle and elbow height.",
            ],
            angle=round(trunk, 1), score=trunk_score, ref="RULA step 10 / REBA step 2",
        ))
    elif trunk < -5:
        out.append(_insight(
            "trunk", "medium",
            "Trunk is leaning backwards",
            "Trunk extension measured at %.0f deg." % abs(trunk),
            "Backward lean usually means the worker is counterbalancing a load held away from "
            "the body, or reaching up to a shelf that is too high.",
            [
                "Lower overhead work to below shoulder height.",
                "Keep loads close to the body; use a stand or trolley for the heavy part of the task.",
            ],
            angle=round(trunk, 1), score=trunk_score, ref="RULA step 10 / REBA step 2",
        ))

    if ctx["trunk_twisted"]:
        out.append(_insight(
            "trunk", "high",
            "Trunk is twisted",
            "Shoulder line rotated %.0f deg against the hips."
            % abs(angles.trunk_twist or 0.0),
            "Twisting under load multiplies spinal shear and adds +1 to both worksheets.",
            [
                "Re-layout the workstation so pick-up and put-down points are in front of the "
                "worker, not behind or beside.",
                "Add a turntable, gravity conveyor or swivel chair so the feet or the part move "
                "instead of the spine.",
                "Widen the foot space so the worker can step round rather than rotate the trunk.",
            ],
            angle=angles.trunk_twist, ref="RULA step 10 / REBA step 2 adjustment",
        ))
    if ctx["trunk_side_bent"]:
        out.append(_insight(
            "trunk", "medium",
            "Trunk is bent sideways",
            "Lateral trunk lean of %.0f deg." % abs(angles.trunk_side_bend or 0.0),
            "Side bending loads the spine asymmetrically and signals a one-sided layout.",
            [
                "Move the item being handled to a central position in front of the worker.",
                "Balance the load between both hands, or use a two-handled container.",
            ],
            angle=angles.trunk_side_bend, ref="REBA step 2 adjustment",
        ))

    # ---------------- neck -------------------------------------------------
    neck = angles.neck_flexion or 0.0
    neck_score = max(rc["neck"]["score"], bc["neck"]["score"])
    if neck > 20:
        out.append(_insight(
            "neck", _sev(neck_score, 3, 4),
            "Head is bent forward",
            "Neck flexion measured at %.0f deg from the trunk (RULA neck %d)."
            % (neck, rc["neck"]["score"]),
            "Every 10 deg of head tilt roughly doubles the static load on the neck extensors; "
            "over 20 deg held for minutes at a time is a classic neck-pain driver.",
            [
                "Raise the visual target: monitor top edge at eye height, or tilt the workpiece "
                "towards the worker with an angled stand or fixture.",
                "Bring detailed work closer (35-45 cm) so the head does not drop to see it.",
                "Add task lighting or magnification instead of moving the head closer.",
                "If a document or drawing is being read, use an inclined document holder next to "
                "the screen rather than flat on the desk.",
            ],
            angle=round(neck, 1), score=neck_score, ref="RULA step 9 / REBA step 1",
        ))
    elif neck < -5:
        out.append(_insight(
            "neck", "high",
            "Head is tipped back",
            "Neck extension measured at %.0f deg." % abs(neck),
            "Neck extension scores 4 on RULA immediately - it is the worst neck band on the "
            "worksheet - and is usually caused by work placed above eye level.",
            [
                "Lower the work or the display to below eye height.",
                "For overhead tasks use an inspection mirror, borescope or a tilting platform so "
                "the worker does not have to look up.",
            ],
            angle=round(neck, 1), score=neck_score, ref="RULA step 9",
        ))
    if ctx["neck_twisted"]:
        out.append(_insight(
            "neck", "medium",
            "Neck is twisted",
            "Head rotated %.0f deg against the shoulders." % abs(angles.neck_twist or 0.0),
            "Twisted-neck postures add +1 to the neck score and commonly come from a display or "
            "workpiece placed off to one side.",
            [
                "Centre the primary display or workpiece in front of the worker.",
                "Move secondary items (second monitor, parts bin, instructions) into the same "
                "line of sight, within 30 deg of centre.",
            ],
            angle=angles.neck_twist, ref="RULA step 9 / REBA step 1 adjustment",
        ))

    # ---------------- upper arm / shoulder --------------------------------
    ua = arm.upper_arm_flexion or 0.0
    ua_score = max(rc["upper_arm"]["score"], bc["upper_arm"]["score"])
    if ua > 45 or ua_score >= 3:
        out.append(_insight(
            "shoulder", _sev(ua_score, 3, 4),
            "Upper arm is raised",
            "%s upper arm at %.0f deg from the trunk (elevation %.0f deg), score %d."
            % (side.capitalize(), ua, arm.upper_arm_elevation or 0.0, ua_score),
            "Unsupported arm elevation above 45 deg is static shoulder work: the deltoid and "
            "rotator cuff cannot relax and blood flow drops within a minute.",
            [
                "Lower the work height, or move the work closer so the elbow stays near the body.",
                "Bring frequently used items inside the primary reach envelope (about 35-45 cm, "
                "elbow bent, upper arm hanging).",
                "Support the arm: armrest, forearm rest, balancer or spring arm for tools.",
                "For anything above shoulder height use a platform, step or height-adjustable "
                "stand instead of reaching up.",
            ],
            angle=round(ua, 1), score=ua_score, ref="RULA step 1 / REBA step 4",
        ))
    if ctx["arm_abducted"]:
        out.append(_insight(
            "shoulder", "medium",
            "Upper arm is held away from the body",
            "%s arm abducted %.0f deg." % (side.capitalize(), abs(arm.upper_arm_abduction or 0.0)),
            "Abduction adds +1 to the upper arm score and increases shoulder torque for the same "
            "hand load.",
            [
                "Narrow the working width so both hands work in front of the shoulders.",
                "Move obstructions (fixtures, guards, machine housings) that force the elbow out.",
            ],
            angle=arm.upper_arm_abduction, ref="RULA step 1 / REBA step 4 adjustment",
        ))
    if ctx["shoulder_raised"]:
        out.append(_insight(
            "shoulder", "medium",
            "Shoulders look hunched",
            "Shoulder-to-ear distance is small relative to the torso, suggesting raised shoulders.",
            "Raised shoulders add +1 and normally mean the work surface, armrests or keyboard are "
            "too high.",
            [
                "Drop the work surface or the armrests by 3-5 cm and re-check.",
                "Set seat height so the forearms are horizontal with the shoulders relaxed.",
            ],
            ref="RULA step 1 / REBA step 4 adjustment",
        ))
    if not ctx["arm_supported"] and ua_score >= 2 and ctx["static_posture"]:
        out.append(_insight(
            "shoulder", "medium",
            "Static arm posture with no support",
            "Arm score %d with the posture held for more than a minute and no arm support."
            % ua_score,
            "RULA subtracts a point when the arm is supported - providing a rest is often the "
            "cheapest single improvement available.",
            ["Fit a forearm rest, wrist rest, tool balancer or padded edge so the arm can rest "
             "between movements."],
            ref="RULA step 1 adjustment",
        ))

    # ---------------- elbow ------------------------------------------------
    elbow = arm.elbow_flexion or 0.0
    if not (60 <= elbow <= 100):
        out.append(_insight(
            "elbow", "low" if rc["lower_arm"]["score"] < 2 else "medium",
            "Elbow is outside its comfortable range",
            "%s elbow flexion %.0f deg (comfortable band is 60-100 deg)." % (side.capitalize(), elbow),
            "Working with a nearly straight or very tightly bent elbow means the work height or "
            "the reach distance is wrong for this worker.",
            [
                "Set the work height so the elbow sits at about 90 deg: hands 5-10 cm below "
                "elbow height for light work, lower for heavy or forceful work.",
                "Reduce the reach distance if the arm is straight (under 60 deg of flexion).",
                "Move the work away from the body if the elbow is over 100 deg.",
            ],
            angle=round(elbow, 1), score=rc["lower_arm"]["score"], ref="RULA step 2 / REBA step 5",
        ))

    # ---------------- wrist ------------------------------------------------
    wrist = arm.wrist_flexion or 0.0
    wrist_score = max(rc["wrist"]["score"], bc["wrist"]["score"])
    if abs(wrist) > 15 or wrist_score >= 3:
        out.append(_insight(
            "wrist", _sev(wrist_score, 3, 4),
            "Wrist is bent",
            "%s wrist %.0f deg %s neutral." % (
                side.capitalize(), abs(wrist), "in flexion from" if wrist > 0 else "in extension from"),
            "Bent wrists raise carpal tunnel pressure and cut grip strength; combined with force "
            "or repetition this is the classic tendon-disorder pattern.",
            [
                "Change the tool or handle angle so the wrist stays straight (bend the tool, not "
                "the wrist): pistol grip for work at elbow height, inline grip for work at "
                "shoulder height.",
                "Adjust the work height and orientation, or tilt the fixture, so the hand "
                "approaches the part in line with the forearm.",
                "For keyboard work: flat or negative tilt, keep the wrists floating, remove the "
                "palm rest edge.",
            ],
            angle=round(wrist, 1), score=wrist_score, ref="RULA step 3 / REBA step 6",
        ))
    if ctx["wrist_deviated"]:
        out.append(_insight(
            "wrist", "medium",
            "Wrist is deviated sideways",
            "Radial/ulnar deviation of %.0f deg." % abs(arm.wrist_deviation or 0.0),
            "Deviation adds +1 and usually comes from handle shape or the approach angle to the part.",
            [
                "Re-orient the fixture or jig so the hand approaches straight on.",
                "Choose a tool with a handle angled to match the work, or a bent-nose tool.",
            ],
            angle=arm.wrist_deviation, ref="RULA step 3 / REBA step 6 adjustment",
        ))

    # ---------------- legs -------------------------------------------------
    knees = [k for k in (angles.left_knee_flexion, angles.right_knee_flexion) if k is not None]
    worst_knee = max(knees) if knees else 0.0
    if not sitting and worst_knee >= 30:
        out.append(_insight(
            "legs", "high" if worst_knee > 60 else "medium",
            "Knees are bent while standing",
            "Knee flexion %.0f deg (REBA legs score %d)." % (worst_knee, bc["legs"]["score"]),
            "Squatting or half-crouching loads the knees and makes the trunk do the rest of the "
            "work; REBA adds up to +2 for it.",
            [
                "Raise the work off the floor onto a stand, trolley or lift table.",
                "Provide a sit-stand stool or kneeling pad if low work is unavoidable.",
                "Split tall stacks so the bottom layers never need a deep squat.",
            ],
            angle=round(worst_knee, 1), score=bc["legs"]["score"], ref="REBA step 3",
        ))
    if angles.flags.get("legs_uneven"):
        out.append(_insight(
            "legs", "medium",
            "Weight is on one leg",
            "Knee flexion differs by %.0f deg between legs." % angles.flags.get("knee_asymmetry_deg", 0),
            "One-legged or unstable stances score 2 on REBA legs and 2 on RULA legs, and they "
            "usually indicate a reach the worker cannot make with both feet planted.",
            [
                "Clear foot space so the worker can stand square to the task (remove pallet "
                "corners, cables, plinths).",
                "Move the target closer so leaning on one leg is not needed.",
                "Add an anti-fatigue mat and a footrest bar for long standing tasks.",
            ],
            ref="RULA step 11 / REBA step 3",
        ))
    if sitting:
        out.append(_insight(
            "legs", "info",
            "Seated task detected",
            "Hip and knee angles suggest a seated posture.",
            "Seated scoring assumes the trunk is supported and both feet are loaded; check the "
            "chair before trusting the low leg score.",
            [
                "Backrest in contact with the lumbar curve, seat pan supporting the thighs "
                "without pressure behind the knee.",
                "Feet flat on the floor or on a footrest; knees at roughly 90-110 deg.",
                "Alternate sitting and standing at least every 30-60 minutes.",
            ],
            ref="RULA step 11",
        ))

    # ---------------- load, grip, repetition ------------------------------
    if ctx["load_kg"] >= 5 or rula["group_a"]["force"] >= 2:
        out.append(_insight(
            "load", "high" if ctx["load_kg"] > 10 else "medium",
            "Hand load is significant",
            "Declared load %.1f kg (RULA force +%d, REBA force +%d)."
            % (ctx["load_kg"], rula["group_a"]["force"], reba["group_a"]["force"]),
            "Force multiplies the risk of every awkward angle above; the same posture with 1 kg "
            "and with 12 kg are different jobs.",
            [
                "Introduce a lifting aid: vacuum lifter, hoist, manipulator or balancer.",
                "Split the load into smaller units, or use two-person handling with a clear signal.",
                "Keep the load between knuckle and elbow height and inside 25 cm of the body.",
            ],
            score=rula["group_a"]["force"], ref="RULA step 6 / REBA step 8",
        ))
    if ctx["coupling"] in ("poor", "unacceptable"):
        out.append(_insight(
            "load", "medium",
            "Hand grip on the load is poor",
            "Coupling rated '%s' (REBA +%d)." % (ctx["coupling"], reba["group_b"]["coupling"]),
            "A bad grip forces higher grip force and pulls the wrist out of neutral.",
            [
                "Add cut-out handles, a handle bar or a grip strap to the container.",
                "Switch to totes with moulded handles at the right height for a power grip.",
                "Provide gloves that fit the task rather than gripping harder.",
            ],
            score=reba["group_b"]["coupling"], ref="REBA step 10",
        ))
    if ctx["static_posture"] or ctx["repeated_actions"]:
        out.append(_insight(
            "organisation", "medium",
            "Static holding or repetition present",
            "Muscle-use/activity points applied: %s."
            % (", ".join(rula["muscle_use_reasons"] + reba["activity_reasons"]) or "none"),
            "Both worksheets add points here because duration and frequency convert a tolerable "
            "posture into an injury risk.",
            [
                "Rotate the job between workers or between tasks so no one stays in one posture.",
                "Insert short pauses (30-60 s every 10-20 min) or micro-breaks with a stretch.",
                "Automate or mechanise the most repetitive element of the cycle.",
                "Re-sequence the task so the awkward element is spread over the shift.",
            ],
            ref="RULA steps 5/12 / REBA step 12",
        ))

    out.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], -(i["score"] or 0)))
    return out


def summarise(angles, rula, reba, insights):
    """Headline numbers plus the ranked list of body parts to fix first."""
    contributions = []
    for tool, result in (("RULA", rula), ("REBA", reba)):
        for name, comp in result["components"].items():
            contributions.append({
                "segment": name,
                "tool": tool,
                "score": comp["score"],
                "angle": comp["angle"],
                "band": comp["band"],
            })
    contributions.sort(key=lambda c: -c["score"])

    ranked, seen = [], set()
    for item in contributions:
        if item["segment"] in seen:
            continue
        seen.add(item["segment"])
        ranked.append(item["segment"])

    return {
        "rula_score": rula["grand_score"],
        "rula_action_level": rula["action_level"],
        "rula_action": rula["action"],
        "rula_risk": rula["risk"],
        "reba_score": reba["reba_score"],
        "reba_risk": reba["risk"],
        "reba_action": reba["action"],
        "governing_side": rula["governing_side"],
        "priority_segments": ranked[:4],
        "worst_components": contributions[:6],
        "critical_count": sum(1 for i in insights if i["severity"] == "critical"),
        "high_count": sum(1 for i in insights if i["severity"] == "high"),
    }
