"""Vector helpers shared by every angle computation.

Everything here works for 2D or 3D numpy vectors.  Angles are returned in
degrees.  The sign convention used across ErgoVision is always stated by the
caller: `signed_angle(v, ref, pos)` is positive when `v` leans towards `pos`.
"""

import numpy as np

EPS = 1e-9


def vec(*points):
    """Turn one or more point-likes into float numpy arrays."""
    out = [np.asarray(p, dtype=float) for p in points]
    return out[0] if len(out) == 1 else out


def length(v):
    return float(np.linalg.norm(v))


def unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < EPS:
        return np.zeros_like(v)
    return v / n


def project_out(v, axis):
    """Component of `v` that is perpendicular to `axis`."""
    v = np.asarray(v, dtype=float)
    a = unit(axis)
    return v - np.dot(v, a) * a


def angle_between(v1, v2):
    """Unsigned angle between two vectors, 0..180 deg."""
    u1, u2 = unit(v1), unit(v2)
    if length(u1) < EPS or length(u2) < EPS:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(np.dot(u1, u2), -1.0, 1.0))))


def joint_angle(a, b, c):
    """Interior angle at joint `b` formed by segments b->a and b->c (0..180)."""
    a, b, c = vec(a, b, c)
    return angle_between(a - b, c - b)


def signed_angle(v, ref_axis, pos_axis):
    """Angle of `v` measured from `ref_axis`, positive towards `pos_axis`.

    `ref_axis` and `pos_axis` should be (roughly) orthogonal; the function
    orthogonalises `pos_axis` against `ref_axis` first.  The result is the
    angle of `v` **projected onto the plane** spanned by the two axes, in
    the range -180..180.
    """
    v = np.asarray(v, dtype=float)
    r = unit(ref_axis)
    p = unit(project_out(pos_axis, r))
    if length(r) < EPS or length(p) < EPS:
        return float("nan")
    return float(np.degrees(np.arctan2(np.dot(v, p), np.dot(v, r))))


def out_of_plane_angle(v, normal_axis):
    """How far `v` tilts out of a plane, given that plane's normal.

    Returns -90..90 deg: 0 means `v` lies in the plane.  Used for abduction and
    side bending, where a signed in-plane angle would flip to ~180 deg as soon
    as the reference axis reversed (e.g. an arm raised past horizontal).
    """
    u = unit(v)
    n = unit(normal_axis)
    if length(u) < EPS or length(n) < EPS:
        return float("nan")
    return float(np.degrees(np.arcsin(np.clip(np.dot(u, n), -1.0, 1.0))))


def rotation_about(axis, v_from, v_to):
    """Signed rotation from `v_from` to `v_to` about `axis` (-180..180 deg).

    Used for twist measurements (shoulder line vs hip line, ear line vs
    shoulder line) where both vectors are perpendicular to the same axis.
    """
    ax = unit(axis)
    a = unit(project_out(v_from, ax))
    b = unit(project_out(v_to, ax))
    if length(a) < EPS or length(b) < EPS:
        return float("nan")
    sin_t = float(np.dot(np.cross(a, b), ax)) if a.size == 3 else float(a[0] * b[1] - a[1] * b[0])
    cos_t = float(np.dot(a, b))
    return float(np.degrees(np.arctan2(sin_t, cos_t)))


def midpoint(a, b):
    a, b = vec(a, b)
    return (a + b) / 2.0
