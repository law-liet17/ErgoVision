"""ErgoVision API and web app.

    python app.py            then open http://127.0.0.1:5000/

Vision (posture lab)
    POST /analyze             multipart image  -> angles, RULA, REBA, OWAS, insights, overlay
    POST /analyze-video       multipart video  -> per-frame scores + worst frame
    POST /score               JSON angles + modifiers -> rescored, no re-upload
    GET  /reference/tables    RULA/REBA tables and thresholds

Assessment tools
    GET  /api/tools           catalogue with input schemas
    POST /api/tools/<id>      run one tool  {inputs...}
    POST /api/tools/niosh/composite   {tasks: [...], duration}

Risk register
    GET/POST      /api/workstations          PATCH/DELETE /api/workstations/<id>
    GET/POST      /api/assessments           GET/DELETE   /api/assessments/<id>
    GET/POST      /api/actions               PATCH/DELETE /api/actions/<id>
    GET           /api/dashboard
    POST          /api/demo/seed    POST /api/demo/clear

Static
    GET /               the enterprise app (web/index.html)
    GET /lab            same app, opened on the posture lab
    GET /legacy         the earlier single-page 3D twin
    GET /health
"""

import json
import os
import tempfile
import traceback

import cv2
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import store
from ergonomics import (
    Modifiers,
    NoPoseDetected,
    PoseBackendUnavailable,
    analyse_image,
    angles_from_dict,
    backend_info,
    decode_image,
    score_angles,
)
from ergonomics import __version__ as engine_version
from ergonomics import angles as angles_mod
from ergonomics import reba, rula
from ergonomics.tools import TOOLS, VISION_TOOLS, catalogue, run_tool
from ergonomics.tools import niosh as niosh_tool

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

app = Flask(__name__, static_folder=None)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB uploads
MODEL_COMPLEXITY = int(os.environ.get("ERGOVISION_MODEL_COMPLEXITY", "1"))

TOOL_NAMES = {t["id"]: t["name"] for t in catalogue()["tools"]}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _modifiers_from_request():
    raw = request.form.get("options") or request.form.get("modifiers")
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("options must be valid JSON: %s" % exc) from exc
    else:
        data = {k: v for k, v in request.form.items() if k not in ("options", "modifiers")}
    return Modifiers.from_dict(data)


def _bool_arg(name, default=True):
    value = request.form.get(name, request.args.get(name))
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _json():
    return request.get_json(silent=True) or {}


def _error(message, code="bad_input", status=400):
    return jsonify({"error": message, "code": code}), status


# ---------------------------------------------------------------------------
# static app
# ---------------------------------------------------------------------------

@app.get("/")
@app.get("/lab")
@app.get("/app")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB, filename)


@app.get("/legacy")
def legacy():
    return send_from_directory(HERE, "ergovision.html")


@app.get("/health")
def health():
    pose = backend_info()
    return jsonify({
        "status": "ok" if pose["ready"] else "pose_model_missing",
        "engine": engine_version,
        "model_complexity": MODEL_COMPLEXITY,
        "pose": pose,
        "tools": len(TOOLS) + len(VISION_TOOLS),
    })


# ---------------------------------------------------------------------------
# vision
# ---------------------------------------------------------------------------

@app.get("/reference/tables")
def reference_tables():
    return jsonify({
        "rula": {
            "table_a": {"%d,%d" % k: v for k, v in rula.TABLE_A_ROWS.items()},
            "table_b": {str(k): v for k, v in rula.TABLE_B_ROWS.items()},
            "table_c": rula.TABLE_C,
            "action_levels": {str(k): v for k, v in rula.ACTION_LEVELS.items()},
        },
        "reba": {
            "table_a": {"%d,%d" % k: v for k, v in reba.TABLE_A_ROWS.items()},
            "table_b": {str(k): v for k, v in reba.TABLE_B_ROWS.items()},
            "table_c": reba.TABLE_C,
            "risk_bands": [{"from": lo, "to": hi, "risk": lab, "level": lvl, "action": act}
                           for lo, hi, lab, lvl, act in reba.RISK_BANDS],
        },
        "detection_thresholds": {
            "twist_deg": angles_mod.TWIST_DEG, "side_bend_deg": angles_mod.SIDE_BEND_DEG,
            "abduction_deg": angles_mod.ABDUCTION_DEG, "wrist_deviation_deg": angles_mod.WRIST_DEVIATION_DEG,
            "leg_asymmetry_deg": angles_mod.LEG_ASYMMETRY_DEG, "neutral_tolerance_deg": rula.NEUTRAL_TOLERANCE,
        },
    })


@app.post("/analyze")
def analyze():
    upload = request.files.get("image") or request.files.get("file")
    if upload is None:
        return _error("No file uploaded. Send the photo as the 'image' field.")
    try:
        modifiers = _modifiers_from_request()
        image = decode_image(upload.read())
        result = analyse_image(image, modifiers=modifiers, annotate=_bool_arg("annotate", True),
                               static=True, complexity=MODEL_COMPLEXITY)
    except NoPoseDetected as exc:
        return _error(str(exc), "no_pose", 422)
    except PoseBackendUnavailable as exc:
        return _error(str(exc), "pose_backend", 503)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:  # pragma: no cover
        app.logger.error(traceback.format_exc())
        return _error("Analysis failed. See the server log.", "server", 500)
    return jsonify(result)


@app.post("/analyze-video")
def analyze_video():
    upload = request.files.get("video") or request.files.get("file")
    if upload is None:
        return _error("No file uploaded. Send the clip as the 'video' field.")
    try:
        modifiers = _modifiers_from_request()
        every_ms = float(request.form.get("sample_ms", 500))
        max_frames = int(request.form.get("max_frames", 60))
    except ValueError as exc:
        return _error(str(exc))
    if not backend_info()["ready"]:
        return _error("Pose model not available. Run: python download_model.py", "pose_backend", 503)

    suffix = os.path.splitext(upload.filename or "clip.mp4")[1] or ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        upload.save(tmp.name)
        tmp.close()
        capture = cv2.VideoCapture(tmp.name)
        if not capture.isOpened():
            return _error("Could not read that video file.")
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(fps * every_ms / 1000.0)))
        frames, worst, index, sampled = [], None, 0, 0
        while sampled < max_frames:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step == 0:
                sampled += 1
                try:
                    result = analyse_image(frame, modifiers=modifiers, annotate=False, static=False,
                                           complexity=MODEL_COMPLEXITY)
                except NoPoseDetected:
                    index += 1
                    continue
                entry = {"time_s": round(index / fps, 2), "rula": result["rula"]["grand_score"],
                         "reba": result["reba"]["reba_score"], "owas": result["owas"]["score"],
                         "trunk": result["angles"]["trunk_flexion"], "neck": result["angles"]["neck_flexion"]}
                frames.append(entry)
                key = (result["reba"]["reba_score"], result["rula"]["grand_score"])
                if worst is None or key > worst[0]:
                    worst = (key, entry["time_s"], frame.copy())
            index += 1
        capture.release()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if not frames:
        return _error("No body detected in any sampled frame.", "no_pose", 422)

    out = analyse_image(worst[2], modifiers=modifiers, annotate=True, static=True, complexity=MODEL_COMPLEXITY)
    out["worst_frame_time_s"] = worst[1]
    out["timeline"] = frames
    out["frames_sampled"] = len(frames)
    out["peak"] = {"rula": max(f["rula"] for f in frames), "reba": max(f["reba"] for f in frames),
                   "mean_rula": round(sum(f["rula"] for f in frames) / len(frames), 2),
                   "mean_reba": round(sum(f["reba"] for f in frames) / len(frames), 2)}
    return jsonify(out)


@app.post("/score")
def score():
    payload = _json()
    angle_data = payload.get("angles")
    if not angle_data:
        return _error("Send {'angles': {...}, 'modifiers': {...}}.")
    try:
        modifiers = Modifiers.from_dict(payload.get("modifiers") or payload.get("options"))
        angles = angles_from_dict({**angle_data, "flags": payload.get("flags") or {}})
        result = score_angles(angles, modifiers)
    except ValueError as exc:
        return _error(str(exc))
    return jsonify(result)


# ---------------------------------------------------------------------------
# assessment tools
# ---------------------------------------------------------------------------

@app.get("/api/tools")
def api_tools():
    return jsonify(catalogue())


@app.post("/api/tools/niosh/composite")
def api_niosh_composite():
    body = _json()
    tasks = body.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        return _error("Send {'tasks': [...], 'duration': '8h'}.")
    return jsonify(niosh_tool.composite(tasks, body.get("duration", "8h")))


@app.post("/api/tools/<tool_id>")
def api_run_tool(tool_id):
    body = _json()
    inputs = body.get("inputs", body)
    try:
        return jsonify(run_tool(tool_id, inputs))
    except KeyError:
        return _error("Unknown tool %r" % tool_id, "not_found", 404)
    except (TypeError, ValueError) as exc:
        return _error("Bad input: %s" % exc)


# ---------------------------------------------------------------------------
# risk register
# ---------------------------------------------------------------------------

@app.get("/api/workstations")
def api_workstations():
    return jsonify(store.list_workstations())


@app.post("/api/workstations")
def api_workstation_create():
    body = _json()
    if not body.get("name"):
        return _error("A workstation needs a name.")
    return jsonify(store.create_workstation(body)), 201


@app.patch("/api/workstations/<int:ws_id>")
def api_workstation_update(ws_id):
    rec = store.update_workstation(ws_id, _json())
    return (jsonify(rec), 200) if rec else _error("No such workstation.", "not_found", 404)


@app.delete("/api/workstations/<int:ws_id>")
def api_workstation_delete(ws_id):
    store.delete_workstation(ws_id)
    return jsonify({"ok": True})


@app.get("/api/assessments")
def api_assessments():
    ws = request.args.get("workstation_id", type=int)
    return jsonify(store.list_assessments(workstation_id=ws, tool=request.args.get("tool"),
                                          limit=request.args.get("limit", 500, type=int)))


@app.post("/api/assessments")
def api_assessment_create():
    body = _json()
    tool = body.get("tool")
    if tool not in TOOL_NAMES:
        return _error("Unknown tool %r" % tool)
    result = body.get("result")
    if not result and tool in TOOLS:
        result = run_tool(tool, body.get("inputs") or {})
    if not result:
        return _error("A saved assessment needs a result (run the tool first).")
    body["result"] = result
    body["tool_name"] = TOOL_NAMES[tool]
    return jsonify(store.create_assessment(body)), 201


@app.get("/api/assessments/<int:a_id>")
def api_assessment(a_id):
    rec = store.get_assessment(a_id)
    return (jsonify(rec), 200) if rec else _error("No such assessment.", "not_found", 404)


@app.delete("/api/assessments/<int:a_id>")
def api_assessment_delete(a_id):
    store.delete_assessment(a_id)
    return jsonify({"ok": True})


@app.get("/api/actions")
def api_actions():
    return jsonify(store.list_actions(status=request.args.get("status")))


@app.post("/api/actions")
def api_action_create():
    body = _json()
    if not body.get("text"):
        return _error("An action needs text.")
    return jsonify(store.create_action(body)), 201


@app.patch("/api/actions/<int:action_id>")
def api_action_update(action_id):
    rec = store.update_action(action_id, _json())
    return (jsonify(rec), 200) if rec else _error("No such action.", "not_found", 404)


@app.delete("/api/actions/<int:action_id>")
def api_action_delete(action_id):
    store.delete_action(action_id)
    return jsonify({"ok": True})


@app.get("/api/dashboard")
def api_dashboard():
    return jsonify(store.dashboard())


@app.post("/api/demo/seed")
def api_demo_seed():
    return jsonify(store.seed_demo(run_tool, TOOL_NAMES))


@app.post("/api/demo/clear")
def api_demo_clear():
    if _json().get("everything"):
        store.clear_all()
    else:
        store.clear_demo()
    return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return _error("Upload is larger than 64 MB.", "too_large", 413)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
