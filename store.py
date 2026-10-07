"""SQLite persistence for the risk register.

    workstations  where the work happens (plant / department / station / task)
    assessments   one tool run, saved against a workstation, with its inputs and result
    actions       follow-up items raised from an assessment

Everything is JSON-friendly and the schema is created on first use. The
database lives next to the app (ergovision.db) unless ERGOVISION_DB says
otherwise.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

DB_PATH = os.environ.get("ERGOVISION_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ergovision.db"))
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS workstations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    plant TEXT DEFAULT '',
    department TEXT DEFAULT '',
    task_type TEXT DEFAULT '',
    shift_hours REAL DEFAULT 8,
    workers INTEGER DEFAULT 1,
    notes TEXT DEFAULT '',
    demo INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workstation_id INTEGER,
    tool TEXT NOT NULL,
    tool_name TEXT DEFAULT '',
    inputs TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    band_level INTEGER DEFAULT 0,
    band_label TEXT DEFAULT '',
    score REAL,
    score_label TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    assessor TEXT DEFAULT '',
    note TEXT DEFAULT '',
    demo INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workstation_id) REFERENCES workstations(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER,
    workstation_id INTEGER,
    text TEXT NOT NULL,
    control TEXT DEFAULT 'engineering',
    owner TEXT DEFAULT '',
    due TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    demo INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);
"""


def _connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with _LOCK, _connect() as con:
        con.executescript(SCHEMA)


def _now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def _loads(record, *keys):
    for k in keys:
        if k in record and isinstance(record[k], str):
            try:
                record[k] = json.loads(record[k])
            except ValueError:
                pass
    return record


# ---------------------------------------------------------------------------
# workstations
# ---------------------------------------------------------------------------

def list_workstations():
    with _LOCK, _connect() as con:
        ws = _rows(con.execute("SELECT * FROM workstations ORDER BY plant, department, name"))
        stats = con.execute("""
            SELECT workstation_id, COUNT(*) AS n, MAX(band_level) AS worst, MAX(created_at) AS last
            FROM assessments GROUP BY workstation_id""").fetchall()
    by_id = {r["workstation_id"]: dict(r) for r in stats}
    for w in ws:
        s = by_id.get(w["id"], {})
        w["assessments"] = s.get("n", 0)
        w["worst_band"] = s.get("worst")
        w["last_assessed"] = s.get("last")
    return ws


def create_workstation(data):
    with _LOCK, _connect() as con:
        cur = con.execute(
            "INSERT INTO workstations (name, plant, department, task_type, shift_hours, workers, notes, demo, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (data.get("name") or "Unnamed station", data.get("plant", ""), data.get("department", ""),
             data.get("task_type", ""), float(data.get("shift_hours") or 8), int(data.get("workers") or 1),
             data.get("notes", ""), 1 if data.get("demo") else 0, _now()))
        return dict(con.execute("SELECT * FROM workstations WHERE id=?", (cur.lastrowid,)).fetchone())


def update_workstation(ws_id, data):
    fields = {k: data[k] for k in ("name", "plant", "department", "task_type", "shift_hours", "workers", "notes") if k in data}
    if not fields:
        return get_workstation(ws_id)
    sets = ", ".join("%s=?" % k for k in fields)
    with _LOCK, _connect() as con:
        con.execute("UPDATE workstations SET %s WHERE id=?" % sets, (*fields.values(), ws_id))
    return get_workstation(ws_id)


def get_workstation(ws_id):
    with _LOCK, _connect() as con:
        r = con.execute("SELECT * FROM workstations WHERE id=?", (ws_id,)).fetchone()
        return dict(r) if r else None


def delete_workstation(ws_id):
    with _LOCK, _connect() as con:
        con.execute("DELETE FROM actions WHERE workstation_id=?", (ws_id,))
        con.execute("DELETE FROM assessments WHERE workstation_id=?", (ws_id,))
        con.execute("DELETE FROM workstations WHERE id=?", (ws_id,))


# ---------------------------------------------------------------------------
# assessments
# ---------------------------------------------------------------------------

def create_assessment(data):
    result = data.get("result") or {}
    band = result.get("band") or {}
    with _LOCK, _connect() as con:
        cur = con.execute(
            "INSERT INTO assessments (workstation_id, tool, tool_name, inputs, result, band_level, band_label, score,"
            " score_label, summary, assessor, note, demo, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("workstation_id"), data.get("tool"), data.get("tool_name", ""),
             json.dumps(data.get("inputs") or {}), json.dumps(result),
             int(band.get("level", 0)), band.get("label", ""), result.get("score"),
             result.get("score_label", ""), result.get("summary", ""), data.get("assessor", ""),
             data.get("note", ""), 1 if data.get("demo") else 0, data.get("created_at") or _now()))
        new_id = cur.lastrowid
        for a in data.get("actions") or []:
            con.execute("INSERT INTO actions (assessment_id, workstation_id, text, control, owner, due, status, demo, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id, data.get("workstation_id"), a.get("text", ""), a.get("control", "engineering"),
                         a.get("owner", ""), a.get("due", ""), a.get("status", "open"), 1 if data.get("demo") else 0, _now()))
    return get_assessment(new_id)


def get_assessment(a_id):
    with _LOCK, _connect() as con:
        r = con.execute("""SELECT a.*, w.name AS workstation, w.department, w.plant FROM assessments a
                           LEFT JOIN workstations w ON w.id = a.workstation_id WHERE a.id=?""", (a_id,)).fetchone()
        if not r:
            return None
        rec = _loads(dict(r), "inputs", "result")
        rec["actions"] = _rows(con.execute("SELECT * FROM actions WHERE assessment_id=? ORDER BY id", (a_id,)))
        return rec


def list_assessments(workstation_id=None, tool=None, limit=500):
    where, params = [], []
    if workstation_id:
        where.append("a.workstation_id=?"); params.append(workstation_id)
    if tool:
        where.append("a.tool=?"); params.append(tool)
    sql = """SELECT a.id, a.workstation_id, a.tool, a.tool_name, a.band_level, a.band_label, a.score, a.score_label,
                    a.summary, a.assessor, a.note, a.demo, a.created_at, w.name AS workstation, w.department, w.plant
             FROM assessments a LEFT JOIN workstations w ON w.id = a.workstation_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.created_at DESC, a.id DESC LIMIT ?"
    params.append(limit)
    with _LOCK, _connect() as con:
        return _rows(con.execute(sql, params))


def delete_assessment(a_id):
    with _LOCK, _connect() as con:
        con.execute("DELETE FROM assessments WHERE id=?", (a_id,))


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

def list_actions(status=None):
    sql = """SELECT ac.*, w.name AS workstation, a.tool, a.band_level FROM actions ac
             LEFT JOIN workstations w ON w.id = ac.workstation_id
             LEFT JOIN assessments a ON a.id = ac.assessment_id"""
    params = []
    if status:
        sql += " WHERE ac.status=?"; params.append(status)
    sql += " ORDER BY CASE ac.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, ac.due, ac.id"
    with _LOCK, _connect() as con:
        return _rows(con.execute(sql, params))


def create_action(data):
    with _LOCK, _connect() as con:
        cur = con.execute("INSERT INTO actions (assessment_id, workstation_id, text, control, owner, due, status, demo, created_at)"
                          " VALUES (?,?,?,?,?,?,?,?,?)",
                          (data.get("assessment_id"), data.get("workstation_id"), data.get("text", ""),
                           data.get("control", "engineering"), data.get("owner", ""), data.get("due", ""),
                           data.get("status", "open"), 0, _now()))
        return dict(con.execute("SELECT * FROM actions WHERE id=?", (cur.lastrowid,)).fetchone())


def update_action(action_id, data):
    fields = {k: data[k] for k in ("text", "control", "owner", "due", "status") if k in data}
    if not fields:
        return None
    sets = ", ".join("%s=?" % k for k in fields)
    with _LOCK, _connect() as con:
        con.execute("UPDATE actions SET %s WHERE id=?" % sets, (*fields.values(), action_id))
        r = con.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return dict(r) if r else None


def delete_action(action_id):
    with _LOCK, _connect() as con:
        con.execute("DELETE FROM actions WHERE id=?", (action_id,))


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------

def dashboard():
    with _LOCK, _connect() as con:
        by_band = {int(r["band_level"]): r["n"] for r in con.execute(
            "SELECT band_level, COUNT(*) AS n FROM assessments GROUP BY band_level")}
        by_tool = _rows(con.execute(
            "SELECT tool, tool_name, COUNT(*) AS n, AVG(band_level) AS mean_band, MAX(band_level) AS worst"
            " FROM assessments GROUP BY tool ORDER BY n DESC"))
        # latest result per (workstation, tool) for the heat-map
        latest = _rows(con.execute("""
            SELECT a.workstation_id, a.tool, a.band_level, a.score, a.score_label, a.id, a.created_at
            FROM assessments a
            JOIN (SELECT workstation_id, tool, MAX(created_at) AS m FROM assessments GROUP BY workstation_id, tool) t
              ON t.workstation_id = a.workstation_id AND t.tool = a.tool AND t.m = a.created_at"""))
        actions = _rows(con.execute("SELECT status, COUNT(*) AS n FROM actions GROUP BY status"))
        overdue = con.execute("SELECT COUNT(*) AS n FROM actions WHERE status != 'done' AND due != '' AND due < ?",
                              (datetime.utcnow().date().isoformat(),)).fetchone()["n"]
        trend = _rows(con.execute("""
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n, AVG(band_level) AS mean_band, MAX(band_level) AS worst
            FROM assessments GROUP BY day ORDER BY day"""))
        n_ws = con.execute("SELECT COUNT(*) AS n FROM workstations").fetchone()["n"]
        n_ass = con.execute("SELECT COUNT(*) AS n FROM assessments").fetchone()["n"]
        demo = con.execute("SELECT COUNT(*) AS n FROM assessments WHERE demo=1").fetchone()["n"]
    ws = list_workstations()
    priority = sorted([w for w in ws if w["worst_band"] is not None],
                      key=lambda w: (-(w["worst_band"] or 0), -(w["assessments"] or 0)))[:8]
    return {
        "counts": {"workstations": n_ws, "assessments": n_ass,
                   "high_or_worse": by_band.get(3, 0) + by_band.get(4, 0),
                   "actions_open": sum(a["n"] for a in actions if a["status"] != "done"),
                   "actions_overdue": overdue, "demo_records": demo},
        "by_band": [by_band.get(i, 0) for i in range(5)],
        "by_tool": by_tool,
        "heatmap": latest,
        "workstations": ws,
        "priority": priority,
        "actions": actions,
        "trend": trend,
        "recent": list_assessments(limit=8),
    }


# ---------------------------------------------------------------------------
# demo data
# ---------------------------------------------------------------------------

def clear_demo():
    with _LOCK, _connect() as con:
        con.execute("DELETE FROM actions WHERE demo=1")
        con.execute("DELETE FROM assessments WHERE demo=1")
        con.execute("DELETE FROM workstations WHERE demo=1")


def clear_all():
    with _LOCK, _connect() as con:
        con.execute("DELETE FROM actions")
        con.execute("DELETE FROM assessments")
        con.execute("DELETE FROM workstations")


def seed_demo(run_tool, tool_names):
    """Populate a believable plant so the dashboard has something to show.

    Every assessment is produced by really running the tool, so the register
    holds genuine numbers rather than invented ones.
    """
    clear_demo()
    plant = "Riverside Assembly Plant"
    stations = [
        ("Packaging", "Case packing line 2", "lifting", [
            ("niosh", {"load_kg": 14, "lifts_per_min": 3, "duration": "8h", "coupling": "fair", "h_origin_cm": 52,
                       "v_origin_cm": 35, "a_origin_deg": 30, "h_dest_cm": 40, "v_dest_cm": 110, "a_dest_deg": 45}),
            ("kim", {"activity": "lifting", "quantity": 900, "load_kg": 14, "sex": "female", "posture": "low_bend", "conditions": "restricted"}),
            ("biomech", {"body_mass_kg": 70, "stature_cm": 168, "load_kg": 14, "trunk_flexion_deg": 55, "upper_arm_flexion_deg": 35, "elbow_flexion_deg": 20}),
        ]),
        ("Packaging", "Shrink-wrap station", "repetitive", [
            ("strain_index", {"intensity": "somewhat_hard", "duration_pct": 60, "efforts_per_min": 16, "posture": "bad", "speed": "fast", "hours_per_day": 7}),
            ("art", {"arm_movements": "very_frequent", "repetition": "gt20", "force_level": "moderate", "force_time": "regular",
                     "wrist": "bent_most", "grip": "pinch_some", "breaks": "every_2h", "pace": "some_difficulty", "duration": "4to8h"}),
        ]),
        ("Warehouse", "Inbound roll-cage transfer", "push_pull", [
            ("rapp", {"equipment": "large_wheeled", "load_kg": 450, "posture": "reasonable", "grip": "reasonable", "pattern": "reasonable",
                      "distance": "medium", "condition": "reasonable", "floor": "reasonable", "obstacles": "some", "other": "none"}),
        ]),
        ("Warehouse", "Pallet break-down bay", "lifting", [
            ("niosh", {"load_kg": 18, "lifts_per_min": 1.5, "duration": "2h", "coupling": "poor", "h_origin_cm": 60,
                       "v_origin_cm": 15, "a_origin_deg": 60, "h_dest_cm": 45, "v_dest_cm": 90, "a_dest_deg": 20}),
            ("owas", {"back": 4, "arms": 1, "legs": 4, "load": 2}),
        ]),
        ("Assembly", "Sub-assembly bench A", "bench", [
            ("fit", {"sex": "female", "percentile": 5, "work_type": "light", "surface_height_cm": 108, "reach_cm": 58}),
            ("strain_index", {"intensity": "light", "duration_pct": 45, "efforts_per_min": 10, "posture": "fair", "speed": "fair", "hours_per_day": 8}),
        ]),
        ("Assembly", "Overhead fastening cell", "overhead", [
            ("owas", {"back": 1, "arms": 3, "legs": 2, "load": 1}),
            ("art", {"arm_movements": "frequent", "repetition": "11to20", "force_level": "strong", "force_time": "some",
                     "arm": "raised_most", "head": "awkward_most", "wrist": "bent_some", "breaks": "regular", "duration": "4to8h"}),
        ]),
        ("Quality", "Inspection microscope station", "precision", [
            ("fit", {"sex": "male", "percentile": 95, "work_type": "precision", "surface_height_cm": 95, "screen_top_cm": 150}),
        ]),
        ("Offices", "Planning desk 14", "office", [
            ("rosa", {"chair_height": 2, "height_not_adjustable": True, "seat_pan": 1, "armrest": 2, "armrest_hard": True,
                      "backrest": 2, "chair_duration": "gt4h", "monitor": 2, "no_document_holder": True, "monitor_duration": "gt4h",
                      "phone": 2, "neck_shoulder_hold": True, "phone_duration": "1to4h", "mouse": 2, "mouse_duration": "gt4h",
                      "keyboard": 2, "wrist_deviation": True, "keyboard_duration": "gt4h"}),
        ]),
        ("Offices", "Reception desk", "office", [
            ("rosa", {"chair_duration": "gt4h", "monitor_duration": "gt4h", "mouse_duration": "gt4h", "keyboard_duration": "gt4h",
                      "phone": 1, "phone_duration": "gt4h"}),
        ]),
    ]
    owners = ["M. Perera", "K. Silva", "A. Fernando", "R. Jayasuriya"]
    today = datetime.utcnow().date()
    for i, (dept, name, task_type, runs) in enumerate(stations):
        ws = create_workstation({"name": name, "plant": plant, "department": dept, "task_type": task_type,
                                 "shift_hours": 8, "workers": 2 + (i % 4), "demo": True,
                                 "notes": "Demo record - replace with your own survey."})
        for j, (tool, inputs) in enumerate(runs):
            result = run_tool(tool, inputs)
            when = datetime.utcnow() - timedelta(days=(len(stations) - i) * 3 + j)
            actions = []
            if result["band"]["level"] >= 2:
                top = result["insights"][0]
                actions.append({"text": top["actions"][0], "control": top["control"], "owner": owners[(i + j) % 4],
                                "due": (today + timedelta(days=(-6 if i % 5 == 0 else 14 + 7 * (i % 3)))).isoformat(),
                                "status": ["open", "in_progress", "open"][j % 3]})
            create_assessment({"workstation_id": ws["id"], "tool": tool, "tool_name": tool_names.get(tool, tool),
                               "inputs": inputs, "result": result, "assessor": "Demo survey", "demo": True,
                               "created_at": when.replace(microsecond=0).isoformat() + "Z", "actions": actions})
    return dashboard()["counts"]


init_db()
