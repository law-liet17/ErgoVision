"""ErgoVision API and web app.

    python app.py            then open http://127.0.0.1:5000/

Vision (posture lab)
    POST /analyze             multipart image  -> angles, RULA, REBA, OWAS, insights, overlay
                              (several people and no 'person' box -> 409 choose_person)
    POST /analyze-multi       1-3 photos of one task ('images') -> one combined assessment,
                              the source photo of every angle, alerts for hidden joints
    POST /analyze-video       multipart video  -> scores sampled across the whole clip,
                              worst frame in full, time spent at each risk level
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
import math
import mimetypes
import os
import tempfile
import traceback

import cv2
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import store
from ergonomics import (
    Modifiers,
    MultiplePeople,
    NoPoseDetected,
    PoseBackendUnavailable,
    analyse_image,
    analyse_views,
    angles_from_dict,
    backend_info,
    decode_image,
    score_angles,
)
from ergonomics import __version__ as engine_version
from ergonomics import angles as angles_mod
from ergonomics import methods, reba, rula
from ergonomics.tools import TOOLS, VISION_TOOLS, catalogue, run_tool
from ergonomics.tools import niosh as niosh_tool

# Windows reads MIME types from the registry, where .js is often mapped to
# text/plain; browsers then refuse to run app.js as a module and the console
# never loads. Pin the types the web app needs.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

app = Flask(__name__, static_folder=None)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB: a minute of 1080p phone video fits
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


def _person_from_request():
    """The worker chosen on the photo: a normalised [x0, y0, x1, y1] box, or None."""
    raw = request.form.get("person")
    if not raw:
        return None
    try:
        box = [float(v) for v in json.loads(raw)]
    except (ValueError, TypeError) as exc:
        raise ValueError("person must be a JSON box [x0, y0, x1, y1]") from exc
    if len(box) != 4 or not all(0.0 <= v <= 1.0 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("person must be a box [x0, y0, x1, y1] with values between 0 and 1")
    return box


def _choose_person(exc, **extra):
    """409: several people in the frame - the client shows them and asks which is the worker."""
    body = {"error": str(exc), "code": "choose_person", "people": exc.people,
            "image": exc.image, "preview": exc.preview}
    body.update(extra)
    return jsonify(body), 409


def _bool_arg(name, default=True):
    value = request.form.get(name, request.args.get(name))
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _json():
    return request.get_json(silent=True) or {}


def _error(message, code="bad_input", status=400):
    return jsonify({"error": message, "code": code}), status


VIDEO_UNREADABLE = ("Could not read that video. Try an MP4 recorded in H.264 "
                    "(on iPhone: Settings > Camera > Formats > Most Compatible).")


def _most_urgent(result):
    """How urgent the more urgent of RULA's and REBA's own action levels is (0-4).

    It orders the moments of a clip and times the exposure; it is not a score.
    It follows the console's rule - the method that reads the posture more
    kindly never hides the other. OWAS is reported beside it but does not lead:
    it is a transcribed sheet and its leg code is unreliable when the feet are
    out of shot.
    """
    return max(m["urgency"] for m in result["methods"] if m["id"] in ("rula", "reba"))


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
        person = _person_from_request()
        image = decode_image(upload.read())
        result = analyse_image(image, modifiers=modifiers, annotate=_bool_arg("annotate", True),
                               static=True, complexity=MODEL_COMPLEXITY, person=person)
    except MultiplePeople as exc:
        return _choose_person(exc)
    except NoPoseDetected as exc:
        return _error(str(exc), "no_pose", 422)
    except PoseBackendUnavailable as exc:
        return _error(str(exc), "pose_backend", 503)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # pragma: no cover
        app.logger.error(traceback.format_exc())
        return _error("Analysis failed: %s: %s" % (type(exc).__name__, exc), "server", 500)
    return jsonify(result)


@app.post("/analyze-multi")
def analyze_multi():
    uploads = [u for u in request.files.getlist("images") if u and u.filename]
    if not uploads:
        return _error("No photos uploaded. Send 1-3 photos of the same task as the 'images' field.")
    try:
        modifiers = _modifiers_from_request()
        images = []
        for number, upload in enumerate(uploads, 1):
            try:
                images.append(decode_image(upload.read()))
            except ValueError as exc:
                raise ValueError("Photo %d (%s): %s" % (number, upload.filename, exc)) from exc
        result = analyse_views(images, modifiers=modifiers, annotate=_bool_arg("annotate", True),
                               complexity=MODEL_COMPLEXITY)
    except NoPoseDetected as exc:
        return _error(str(exc), "no_pose", 422)
    except PoseBackendUnavailable as exc:
        return _error(str(exc), "pose_backend", 503)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # pragma: no cover
        app.logger.error(traceback.format_exc())
        return _error("Analysis failed: %s: %s" % (type(exc).__name__, exc), "server", 500)
    return jsonify(result)


@app.post("/analyze-video")
def analyze_video():
    upload = request.files.get("video") or request.files.get("file")
    if upload is None:
        return _error("No file uploaded. Send the clip as the 'video' field.")
    try:
        modifiers = _modifiers_from_request()
        person = _person_from_request()
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
            return _error(VIDEO_UNREADABLE, "bad_video", 422)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps or fps > 1000:  # missing or NaN in some phone containers
            fps = 25.0
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Spread the samples over the WHOLE clip: one every `every_ms` at most, and
        # never more than `max_frames`, so a long clip is sampled more sparsely
        # instead of only its first half-minute being looked at.
        step = max(1, int(round(fps * every_ms / 1000.0)))
        if total > 0:
            step = max(step, int(math.ceil(total / float(max_frames))))
        frames, worst, index, sampled, decoded = [], None, 0, 0, 0
        # The worker is followed through the clip by their box: the one clicked on
        # the first frame, else the only person seen first. Each sample then takes
        # the body overlapping the worker's last box, so someone walking past is
        # never scored instead.
        track = person
        while sampled < max_frames:
            if index % step:
                if not capture.grab():  # skip without decoding: much faster on long clips
                    break
                index += 1
                continue
            ok, frame = capture.read()
            if not ok:
                break
            decoded += 1
            sampled += 1
            try:
                result = analyse_image(frame, modifiers=modifiers, annotate=False, static=False,
                                       complexity=MODEL_COMPLEXITY, person=track)
            except NoPoseDetected:
                index += 1
                continue
            except MultiplePeople as exc:  # nobody chosen yet, and the first worker seen is ambiguous
                capture.release()
                return _choose_person(exc, time_s=round(index / fps, 2))
            track = result["person"]["box"]
            level = _most_urgent(result)
            entry = {"time_s": round(index / fps, 2), "rula": result["rula"]["grand_score"],
                     "reba": result["reba"]["reba_score"], "owas": result["owas"]["score"],
                     "level": level,
                     "trunk": result["angles"]["trunk_flexion"], "neck": result["angles"]["neck_flexion"]}
            frames.append(entry)
            key = (level, result["reba"]["reba_score"], result["rula"]["grand_score"])
            if worst is None or key > worst[0]:
                worst = (key, entry["time_s"], frame.copy(), track)
            index += 1
        capture.release()
        if decoded == 0:
            return _error(VIDEO_UNREADABLE, "bad_video", 422)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if not frames:
        return _error("No body detected in any sampled frame.", "no_pose", 422)

    out = analyse_image(worst[2], modifiers=modifiers, annotate=True, static=True,
                        complexity=MODEL_COMPLEXITY, person=worst[3])
    out["worst_frame_time_s"] = worst[1]
    out["timeline"] = frames
    out["frames_sampled"] = len(frames)
    out["peak"] = {"rula": max(f["rula"] for f in frames), "reba": max(f["reba"] for f in frames),
                   "mean_rula": round(sum(f["rula"] for f in frames) / len(frames), 2),
                   "mean_reba": round(sum(f["reba"] for f in frames) / len(frames), 2)}
    # How long the worker spent at each 0-4 risk level. Each sample stands for
    # `step / fps` seconds of the clip, so the shares are shares of time.
    counts = [0] * 5
    for f in frames:
        counts[f["level"]] += 1
    out["exposure"] = {
        "seconds_per_sample": round(step / fps, 2),
        "duration_s": round((total / fps) if total else frames[-1]["time_s"], 1),
        "pct_by_level": [round(100.0 * c / len(frames)) for c in counts],
        "pct_high": round(100.0 * sum(counts[3:]) / len(frames)),
    }
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
    result = niosh_tool.composite(tasks, body.get("duration", "8h"))
    result["method"] = methods.describe("niosh_cli", result)
    return jsonify(result)


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
    return _error("Upload is larger than 256 MB. Trim the clip to the task, or record at 1080p.",
                  "too_large", 413)


if __name__ == "__main__":
    # No reloader: MediaPipe touches files in the Python install while it
    # loads, the reloader treats that as a code change and restarts the server
    # mid-upload, which the browser reports as "Failed to fetch".
    app.run(debug=True, use_reloader=False, host="127.0.0.1", port=5000)
