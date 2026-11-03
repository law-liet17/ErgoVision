"""Render a synthetic side-view factory clip: worker walks in, stoop-lifts a box
(straight legs, trunk flexed ~95 deg, neck bent), carries it to the far end.
Usage: python make_lift_video.py OUT.mp4 [--frames DIR]"""
import math, sys, os
import numpy as np
import cv2

W, H, SS, FPS = 1280, 720, 2, 25
FLOOR = 620
L_TH, L_SH, L_TR, L_UA, L_FA = 100, 100, 125, 80, 70
BOX_W, BOX_H, PALLET_H = 70, 55, 18
BOX_X0 = 640                     # box centre on the pick-up pallet

def S(p):  # to supersampled integer pixel
    return (int(round(p[0] * SS)), int(round(p[1] * SS)))

def down(a):  # unit vector, angle from straight-down, +forward (+x)
    r = math.radians(a); return np.array([math.sin(r), math.cos(r)])

def up(a):    # unit vector, angle from straight-up, +forward
    r = math.radians(a); return np.array([math.sin(r), -math.cos(r)])

def capsule(img, a, b, w, col, outline=(25, 25, 30)):
    a, b = np.asarray(a, float), np.asarray(b, float)
    for c, ww in ((outline, w + 4), (col, w)):
        cv2.line(img, S(a), S(b), c, int(ww * SS), cv2.LINE_AA)
        cv2.circle(img, S(a), int(ww * SS / 2), c, -1, cv2.LINE_AA)
        cv2.circle(img, S(b), int(ww * SS / 2), c, -1, cv2.LINE_AA)

def poly(img, pts, col, outline=(25, 25, 30)):
    p = np.array([S(q) for q in pts], np.int32)
    cv2.fillPoly(img, [p], col, cv2.LINE_AA)
    cv2.polylines(img, [p], True, outline, 2 * SS, cv2.LINE_AA)

def ik(s, t, a, b, sign):
    d = t - s; dist = np.linalg.norm(d)
    dist_c = min(max(dist, abs(a - b) + 1), a + b - 1)
    base = math.atan2(d[1], d[0])
    alpha = math.acos((a * a + dist_c * dist_c - b * b) / (2 * a * dist_c))
    e = s + a * np.array([math.cos(base + sign * alpha), math.sin(base + sign * alpha)])
    w = e + b * (t - e) / max(np.linalg.norm(t - e), 1e-6)
    return e, w

# ---------------------------------------------------------------- background
def background():
    img = np.zeros((H * SS, W * SS, 3), np.uint8)
    for y in range(FLOOR * SS):   # wall gradient
        v = 150 + 40 * y / (FLOOR * SS)
        img[y, :] = (v * 0.95, v * 0.93, v * 0.88)
    for y in range(FLOOR * SS, H * SS):  # concrete floor
        v = 120 - 30 * (y - FLOOR * SS) / ((H - FLOOR) * SS)
        img[y, :] = (v, v * 1.02, v * 1.04)
    def rect(x0, y0, x1, y1, col): cv2.rectangle(img, S((x0, y0)), S((x1, y1)), col, -1, cv2.LINE_AA)
    # wall panels, ceiling beam and lights
    for x in range(0, W, 160): cv2.line(img, S((x, 0)), S((x, FLOOR)), (150, 148, 140), SS)
    rect(0, 0, W, 38, (70, 72, 78))
    for x in range(120, W, 260):
        rect(x, 38, x + 120, 50, (90, 90, 95)); rect(x + 6, 50, x + 114, 56, (225, 245, 250))
    rect(0, FLOOR - 140, W, FLOOR - 128, (70, 140, 60))       # green wall stripe
    # pallet racking, back left and back right
    for rx in (30, 990):
        for ux in (rx, rx + 250): rect(ux, 120, ux + 12, FLOOR, (30, 110, 220))
        for by in (230, 380, 520):
            rect(rx, by, rx + 262, by + 12, (150, 80, 30))
            for k in range(3):
                bx = rx + 22 + k * 80
                rect(bx, by - 52, bx + 62, by, (80, 135, 185)); rect(bx, by - 30, bx + 62, by - 26, (60, 105, 150))
    # conveyor in the middle background
    rect(330, 470, 900, 488, (75, 75, 80))
    for lx in range(350, 900, 120): rect(lx, 488, lx + 10, FLOOR - 5, (60, 60, 65))
    for k in range(5): rect(370 + k * 105, 430, 440 + k * 105, 470, (70, 120, 170))
    # walkway hazard lines on floor
    rect(0, FLOOR + 2, W, FLOOR + 8, (40, 200, 240))
    rect(0, H - 22, W, H - 16, (40, 200, 240))
    for x in range(0, W, 60):
        cv2.line(img, S((x, FLOOR + 30)), S((x - 40, H)), (100, 104, 108), SS, cv2.LINE_AA)
    # pick-up pallet (centre) and drop pallet (right)
    for px in (BOX_X0 - 60, 1190):
        rect(px, FLOOR - PALLET_H, px + 120, FLOOR - PALLET_H + 5, (60, 120, 165))
        for k in range(3): rect(px + k * 52, FLOOR - PALLET_H, px + k * 52 + 16, FLOOR, (50, 100, 140))
    return img

def draw_box(img, c):
    x, y = c
    poly(img, [(x - BOX_W / 2, y - BOX_H / 2), (x + BOX_W / 2, y - BOX_H / 2),
               (x + BOX_W / 2, y + BOX_H / 2), (x - BOX_W / 2, y + BOX_H / 2)], (70, 130, 190))
    cv2.line(img, S((x - BOX_W / 2, y - BOX_H / 2 + 8)), S((x + BOX_W / 2, y - BOX_H / 2 + 8)), (150, 190, 215), 3 * SS)

# ---------------------------------------------------------------- the worker
BLUE, BLUE_D = (150, 85, 35), (105, 58, 25)
SKIN, SKIN_D = (120, 160, 210), (95, 130, 180)
BOOT, VEST, HAT = (35, 35, 40), (20, 120, 245), (30, 200, 250)

def draw_worker(img, P, pose, box_c=None):
    P = np.asarray(P, float)
    sh = P + L_TR * up(pose["trunk"])
    legs = {}
    for side in ("far", "near"):
        t, s = pose[side + "_t"], pose[side + "_s"]
        k = P + L_TH * down(t); a = k + L_SH * down(s)
        legs[side] = (k, a, s)
    arms = {}
    for side in ("far", "near"):
        if pose.get("hand") is not None:
            tgt = np.asarray(pose["hand"], float) + (np.array([0, 0]) if side == "near" else np.array([6, -3]))
            e, wr = ik(sh, tgt, L_UA, L_FA, pose.get("elbow_sign", 1))
        else:
            e = sh + L_UA * down(pose[side + "_b"]); wr = e + L_FA * down(pose[side + "_c"])
        arms[side] = (e, wr)

    def leg(side, cl, cd):
        k, a, s = legs[side]
        capsule(img, P, k, 30, cl); capsule(img, k, a, 25, cl)
        fwd = np.array([math.cos(math.radians(s)), -math.sin(math.radians(s))])
        dn = down(s)
        poly(img, [a - 10 * fwd - 4 * dn, a + 30 * fwd - 2 * dn, a + 34 * fwd + 12 * dn, a - 12 * fwd + 12 * dn], BOOT)
    def arm(side, cl, sk):
        e, wr = arms[side]
        capsule(img, sh, e, 22, cl); capsule(img, e, wr, 18, cl)
        hand = wr + 10 * (wr - e) / max(np.linalg.norm(wr - e), 1e-6)
        capsule(img, wr, hand, 15, sk)

    arm("far", BLUE_D, SKIN_D)
    leg("far", BLUE_D, BLUE_D)
    # torso: quad from hip line to shoulder line, then hi-vis vest
    ax = up(pose["trunk"]); nrm = np.array([-ax[1], ax[0]])   # forward-perpendicular to the trunk
    hb, ht = 25, 27
    torso = [P - hb * nrm, P + hb * nrm, sh + ht * nrm + 6 * ax, sh - ht * nrm + 6 * ax]
    poly(img, torso, BLUE)
    vest = [P + 0.15 * (sh - P) - (hb - 2) * nrm, P + 0.15 * (sh - P) + (hb - 2) * nrm,
            P + 0.85 * (sh - P) + (ht - 2) * nrm, P + 0.85 * (sh - P) - (ht - 2) * nrm]
    poly(img, vest, VEST)
    for f in (0.35, 0.6):
        a0 = P + f * (sh - P); cv2.line(img, S(a0 - (hb - 2) * nrm), S(a0 + (hb - 2) * nrm), (220, 225, 225), 4 * SS, cv2.LINE_AA)
    capsule(img, P - 4 * ax, P - 4 * ax, 46, BLUE)     # hips
    leg("near", BLUE, BLUE)
    # neck and head
    na = pose["trunk"] + pose["neck"]
    neck_top = sh + 22 * up(na); head = neck_top + 20 * up(na)
    capsule(img, sh, neck_top, 18, SKIN)
    cv2.circle(img, S(head), 25 * SS, (25, 25, 30), -1, cv2.LINE_AA)
    cv2.circle(img, S(head), 23 * SS, SKIN, -1, cv2.LINE_AA)
    face = np.array([math.cos(math.radians(na)), math.sin(math.radians(na))])  # forward direction of face
    upv = up(na)
    nose = head + 23 * face - 2 * upv
    poly(img, [head + 18 * face + 4 * upv, nose + 7 * face - 3 * upv, head + 19 * face - 8 * upv], SKIN)
    cv2.circle(img, S(head + 12 * face + 7 * upv), 3 * SS, (30, 30, 30), -1, cv2.LINE_AA)        # eye
    cv2.ellipse(img, S(head - 3 * face), (5 * SS, 8 * SS), 0, 0, 360, SKIN_D, -1, cv2.LINE_AA)     # ear
    cv2.line(img, S(head + 10 * face - 13 * upv), S(head + 17 * face - 13 * upv), (60, 60, 120), 2 * SS, cv2.LINE_AA)  # mouth
    ang = -math.degrees(math.atan2(upv[1], upv[0]))
    cv2.ellipse(img, S(head + 4 * upv), (26 * SS, 24 * SS), -ang + 90, 180, 360, HAT, -1, cv2.LINE_AA)  # helmet dome
    cv2.line(img, S(head + 6 * upv - 26 * face), S(head + 6 * upv + 34 * face), HAT, 5 * SS, cv2.LINE_AA)  # brim
    if box_c is not None: draw_box(img, box_c)
    arm("near", BLUE, SKIN)

# ---------------------------------------------------------------- choreography
def smooth(u): u = min(max(u, 0), 1); return u * u * (3 - 2 * u)
def lerp(a, b, u): return a + (b - a) * u

STAND = dict(trunk=0, neck=0, near_t=0, near_s=0, far_t=0, far_s=0, near_b=0, near_c=5, far_b=0, far_c=5)
STOOP = dict(trunk=88, neck=-25, near_t=20, near_s=2, far_t=20, far_s=2)
CARRY = dict(trunk=-7, neck=5, near_t=0, near_s=0, far_t=0, far_s=0)
STRIDE = 175.0
ANKLE = 534.0                      # where the feet stop for the lift
T = dict(walk1=(0, 4.2), stoop=(4.5, 5.9), grip=(5.9, 6.9), lift=(6.9, 8.6), walk2=(8.9, 13.9), end=15.0)

def gait(pose, x, x0, u, arms=True):
    amp = min(1.0, min(u, 1 - u) / 0.12)
    ph = (x - x0) / STRIDE * 2 * math.pi
    for side, off in (("near", 0), ("far", math.pi)):
        t = 24 * amp * math.sin(ph + off)
        kf = amp * (8 + 42 * max(0.0, math.cos(ph + off)) ** 1.5)
        pose[side + "_t"], pose[side + "_s"] = t, t - kf
        if arms:
            b = -18 * amp * math.sin(ph + off); pose[side + "_b"], pose[side + "_c"] = b, b + 8 + 10 * amp
    return pose

def pelvis_y(pose):
    reach = max(L_TH * math.cos(math.radians(pose[s + "_t"])) + L_SH * math.cos(math.radians(pose[s + "_s"])) for s in ("near", "far"))
    return FLOOR - 13 - reach

def ankle_dx(pose):
    return L_TH * math.sin(math.radians(pose["near_t"])) + L_SH * math.sin(math.radians(pose["near_s"]))

def frame_state(t):
    box_rest = np.array([BOX_X0, FLOOR - PALLET_H - BOX_H / 2])
    if t < T["walk1"][1] or t < T["stoop"][0]:
        u = min(t / T["walk1"][1], 1.0)
        x = lerp(80, ANKLE, smooth(u) * 0.5 + u * 0.5)
        pose = gait(dict(STAND), x, 80, u)
        return np.array([x, pelvis_y(pose)]), pose, None, box_rest
    if t < T["lift"][0]:       # bend down, then hold the grip
        u = smooth((t - T["stoop"][0]) / (T["stoop"][1] - T["stoop"][0]))
        pose = {k: lerp(STAND[k], STOOP[k], u) for k in STOOP}
        pose.update(near_b=lerp(0, 10, u), near_c=lerp(5, 5, u), far_b=lerp(0, 10, u), far_c=5)
        P = np.array([ANKLE - ankle_dx(pose), pelvis_y(pose)])
        hand = None
        if u > 0.55:
            sh = P + L_TR * up(pose["trunk"])
            free = sh + L_UA * down(10) + (L_FA + 10) * down(5)
            grip = box_rest + np.array([-12, -10])
            hand = lerp(free, grip, smooth((u - 0.55) / 0.45))
            pose["hand"], pose["elbow_sign"] = hand, 1
        return P, pose, None, box_rest
    if t < T["walk2"][0]:      # lift with straight legs, box comes up to the waist
        u = smooth((t - T["lift"][0]) / (T["lift"][1] - T["lift"][0]))
        pose = {k: lerp(STOOP[k], CARRY[k], u) for k in STOOP}
        P = np.array([ANKLE - ankle_dx(pose), pelvis_y(pose)])
        grip = box_rest + np.array([-12, -10])
        carry = P + np.array([58, -42])
        hand = lerp(grip, carry, u)
        pose["hand"], pose["elbow_sign"] = hand, 1
        return P, pose, hand + np.array([12, 10]), None
    u = min((t - T["walk2"][0]) / (T["walk2"][1] - T["walk2"][0]), 1.0)
    x = lerp(ANKLE, 1150, smooth(u) * 0.5 + u * 0.5)
    pose = gait(dict(CARRY), x, ANKLE, u, arms=False)
    P = np.array([x, pelvis_y(pose)])
    hand = P + np.array([58, -42])
    pose["hand"], pose["elbow_sign"] = hand, 1
    return P, pose, hand + np.array([12, 10]), None

def main():
    out = sys.argv[1]
    dump = sys.argv[sys.argv.index("--frames") + 1] if "--frames" in sys.argv else None
    bg = background()
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    n = int(T["end"] * FPS)
    for i in range(n):
        t = i / FPS
        img = bg.copy()
        P, pose, carried, resting = frame_state(t)
        if resting is not None: draw_box(img, resting)
        draw_worker(img, P, pose, carried)
        frame = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        vw.write(frame)
        if dump and i % 25 == 0: cv2.imwrite(os.path.join(dump, "f%03d.jpg" % i), frame)
    vw.release()
    print("wrote", out, n, "frames")

if __name__ == "__main__":
    main()
