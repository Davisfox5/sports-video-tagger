#!/usr/bin/env python3
"""
Sports Video Tagging App - A lightweight clone of SportsCode.
Tag clips in game footage, categorize them, and filter/review by type.
"""

import os
import io
import csv
import json
import uuid
import subprocess
import tempfile
from flask import Flask, jsonify, request, send_from_directory, send_file, render_template

app = Flask(__name__, static_folder="static", template_folder="templates")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VIDEOS_DIR = os.path.join(DATA_DIR, "videos")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(RECORDINGS_DIR, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


def _load_projects():
    if os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_projects(projects):
    with open(PROJECTS_FILE, "w") as f:
        json.dump(projects, f, indent=2)


# ── Pages ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Project CRUD ───────────────────────────────────────────────────────────

@app.route("/api/projects", methods=["GET"])
def list_projects():
    projects = _load_projects()
    return jsonify(list(projects.values()))


@app.route("/api/projects", methods=["POST"])
def create_project():
    data = request.json
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    projects = _load_projects()
    project_id = str(uuid.uuid4())[:8]
    projects[project_id] = {
        "id": project_id,
        "name": name,
        "video_filename": None,
        "tag_types": [
            {"name": "Goal", "color": "#e74c3c"},
            {"name": "Shot", "color": "#3498db"},
            {"name": "Pass", "color": "#2ecc71"},
            {"name": "Foul", "color": "#f39c12"},
            {"name": "Corner", "color": "#9b59b6"},
            {"name": "Free Kick", "color": "#1abc9c"},
            {"name": "Turnover", "color": "#e67e22"},
            {"name": "Save", "color": "#34495e"},
        ],
        "players": [],
        "clips": [],
    }
    _save_projects(projects)
    return jsonify(projects[project_id]), 201


@app.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    projects = _load_projects()
    project = projects.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(project)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    # Remove associated video file
    proj = projects[project_id]
    if proj.get("video_filename"):
        path = os.path.join(VIDEOS_DIR, proj["video_filename"])
        if os.path.exists(path):
            os.remove(path)
    del projects[project_id]
    _save_projects(projects)
    return jsonify({"ok": True})


# ── Video upload ───────────────────────────────────────────────────────────

@app.route("/api/projects/<project_id>/video", methods=["POST"])
def upload_video(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    video = request.files["video"]
    ext = os.path.splitext(video.filename)[1].lower()
    if ext not in (".mp4", ".webm", ".mov", ".mkv", ".avi"):
        return jsonify({"error": "Unsupported video format"}), 400

    filename = f"{project_id}{ext}"
    video.save(os.path.join(VIDEOS_DIR, filename))
    projects[project_id]["video_filename"] = filename
    _save_projects(projects)
    return jsonify({"filename": filename})


@app.route("/videos/<filename>")
def serve_video(filename):
    return send_from_directory(VIDEOS_DIR, filename)


# ── Tag types ──────────────────────────────────────────────────────────────

@app.route("/api/projects/<project_id>/tag_types", methods=["PUT"])
def update_tag_types(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    tag_types = request.json.get("tag_types", [])
    projects[project_id]["tag_types"] = tag_types
    _save_projects(projects)
    return jsonify(tag_types)


# ── Players CRUD ──────────────────────────────────────────────────────

def _is_duplicate_player(existing_players, name, number):
    """Check if a player with the same name (case-insensitive) and number exists."""
    for p in existing_players:
        if p["name"].lower() == name.lower() and p.get("number", "") == number:
            return True
    return False

@app.route("/api/projects/<project_id>/players", methods=["GET"])
def list_players(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(projects[project_id].get("players", []))


@app.route("/api/projects/<project_id>/players", methods=["POST"])
def create_player(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    data = request.json
    name = data.get("name", "").strip()
    number = data.get("number", "").strip()
    if not name:
        return jsonify({"error": "Player name is required"}), 400

    if "players" not in projects[project_id]:
        projects[project_id]["players"] = []

    existing = projects[project_id]["players"]
    if _is_duplicate_player(existing, name, number):
        return jsonify({"error": f"Player '{name}' #{number} already exists".rstrip(" #")}), 409

    player = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "number": number,
    }

    projects[project_id]["players"].append(player)
    _save_projects(projects)
    return jsonify(player), 201


@app.route("/api/projects/<project_id>/players/<player_id>", methods=["PUT"])
def update_player(project_id, player_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    data = request.json
    for player in projects[project_id].get("players", []):
        if player["id"] == player_id:
            player["name"] = data.get("name", player["name"]).strip()
            player["number"] = data.get("number", player["number"]).strip()
            _save_projects(projects)
            return jsonify(player)
    return jsonify({"error": "Player not found"}), 404


@app.route("/api/projects/<project_id>/players/<player_id>", methods=["DELETE"])
def delete_player(project_id, player_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    players = projects[project_id].get("players", [])
    projects[project_id]["players"] = [p for p in players if p["id"] != player_id]
    _save_projects(projects)
    return jsonify({"ok": True})


@app.route("/api/projects/<project_id>/players/import", methods=["POST"])
def import_roster(project_id):
    """Import players from an Excel (.xlsx/.xls) or CSV file.

    Expects columns for player name and jersey number. The endpoint
    auto-detects columns by scanning headers for keywords like 'name',
    'player', 'number', 'jersey', '#'. If no header matches, it falls
    back to column A = name, column B = number.
    """
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    fname = f.filename.lower()

    rows = []
    if fname.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c).strip() if c is not None else "" for c in row])
            wb.close()
        except Exception as e:
            return jsonify({"error": f"Could not read Excel file: {e}"}), 400
    elif fname.endswith(".csv"):
        try:
            import io as _io
            text = f.read().decode("utf-8-sig")
            reader = csv.reader(_io.StringIO(text))
            for row in reader:
                rows.append([c.strip() for c in row])
        except Exception as e:
            return jsonify({"error": f"Could not read CSV file: {e}"}), 400
    else:
        return jsonify({"error": "Unsupported file type. Upload .xlsx, .xls, or .csv"}), 400

    if not rows:
        return jsonify({"error": "File is empty"}), 400

    # Auto-detect columns from header row
    name_col = None
    number_col = None
    header = [h.lower() for h in rows[0]]
    name_keywords = ["name", "player", "first", "last", "athlete"]
    number_keywords = ["number", "jersey", "#", "no", "num"]

    for i, h in enumerate(header):
        if name_col is None and any(k in h for k in name_keywords):
            name_col = i
        if number_col is None and any(k in h for k in number_keywords):
            number_col = i

    has_header = name_col is not None
    if not has_header:
        # Fallback: col 0 = name, col 1 = number (if exists)
        name_col = 0
        number_col = 1 if len(rows[0]) > 1 else None
        data_rows = rows
    else:
        data_rows = rows[1:]  # skip header

    if "players" not in projects[project_id]:
        projects[project_id]["players"] = []

    existing = projects[project_id]["players"]
    imported = []
    skipped = 0
    for row in data_rows:
        if not row or name_col >= len(row):
            continue
        name = row[name_col].strip()
        if not name or name.lower() == "none":
            continue
        number = ""
        if number_col is not None and number_col < len(row):
            number = row[number_col].strip()
            if number.lower() == "none":
                number = ""
            # Clean up float numbers from Excel (e.g., "10.0" -> "10")
            try:
                num_val = float(number)
                if num_val == int(num_val):
                    number = str(int(num_val))
            except (ValueError, OverflowError):
                pass

        # Skip duplicates against existing roster + already-imported batch
        if _is_duplicate_player(existing, name, number):
            skipped += 1
            continue

        player = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "number": number,
        }
        existing.append(player)
        imported.append(player)

    _save_projects(projects)
    return jsonify({"imported": len(imported), "skipped": skipped, "players": imported}), 201


# ── Filter presets ────────────────────────────────────────────────────

def _get_presets(project):
    return project.setdefault("filter_presets", [])


def _preset_json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "Request body must be a JSON object"}), 400)
    return data, None


def _validate_preset_name(name, presets, exclude_id=None):
    if not isinstance(name, str):
        return None, (jsonify({"error": "name must be a string"}), 400)
    name = name.strip()
    if not name:
        return None, (jsonify({"error": "Name is required"}), 400)
    if len(name) > 60:
        return None, (jsonify({"error": "Name must be 60 characters or fewer"}), 400)
    for preset in presets:
        if exclude_id is not None and preset["id"] == exclude_id:
            continue
        if preset["name"].lower() == name.lower():
            return None, (jsonify({"error": f"A preset named '{name}' already exists"}), 409)
    return name, None


def _validate_preset_filter_value(field, value):
    if not isinstance(value, str):
        return None, (jsonify({"error": f"{field} must be a string"}), 400)
    if field in ("tag_type", "search"):
        value = value.strip()
    return value, None


@app.route("/api/projects/<project_id>/filter_presets", methods=["GET"])
def list_filter_presets(project_id):
    projects = _load_projects()
    project = projects.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(_get_presets(project))


@app.route("/api/projects/<project_id>/filter_presets", methods=["POST"])
def create_filter_preset(project_id):
    projects = _load_projects()
    project = projects.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data, err = _preset_json_body()
    if err:
        return err

    presets = _get_presets(project)
    name, err = _validate_preset_name(data.get("name"), presets)
    if err:
        return err

    fields = {}
    for field in ("tag_type", "player", "search"):
        value, err = _validate_preset_filter_value(field, data.get(field, ""))
        if err:
            return err
        fields[field] = value

    preset = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "tag_type": fields["tag_type"],
        "player": fields["player"],
        "search": fields["search"],
    }
    presets.append(preset)
    _save_projects(projects)
    return jsonify(preset), 201


@app.route("/api/projects/<project_id>/filter_presets/<preset_id>", methods=["PUT"])
def update_filter_preset(project_id, preset_id):
    projects = _load_projects()
    project = projects.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data, err = _preset_json_body()
    if err:
        return err

    presets = _get_presets(project)
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if not preset:
        return jsonify({"error": "Preset not found"}), 404

    if "name" in data:
        name, err = _validate_preset_name(data["name"], presets, exclude_id=preset_id)
        if err:
            return err
        preset["name"] = name

    for field in ("tag_type", "player", "search"):
        if field not in data:
            continue
        value, err = _validate_preset_filter_value(field, data[field])
        if err:
            return err
        preset[field] = value

    _save_projects(projects)
    return jsonify(preset)


@app.route("/api/projects/<project_id>/filter_presets/<preset_id>", methods=["DELETE"])
def delete_filter_preset(project_id, preset_id):
    projects = _load_projects()
    project = projects.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    presets = _get_presets(project)
    kept = [p for p in presets if p["id"] != preset_id]
    if len(kept) == len(presets):
        return jsonify({"error": "Preset not found"}), 404
    project["filter_presets"] = kept
    _save_projects(projects)
    return jsonify({"ok": True})


# ── Clips CRUD ─────────────────────────────────────────────────────────────

@app.route("/api/projects/<project_id>/clips", methods=["GET"])
def list_clips(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(projects[project_id]["clips"])


@app.route("/api/projects/<project_id>/clips", methods=["POST"])
def create_clip(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    data = request.json
    clip = {
        "id": str(uuid.uuid4())[:8],
        "tag_type": data.get("tag_type", ""),
        "start": data.get("start", 0),
        "end": data.get("end", 0),
        "label": data.get("label", ""),
        "notes": data.get("notes", ""),
        "players": data.get("players", []),
        "recordings": [],
    }

    if clip["end"] <= clip["start"]:
        return jsonify({"error": "End time must be after start time"}), 400

    projects[project_id]["clips"].append(clip)
    _save_projects(projects)
    return jsonify(clip), 201


@app.route("/api/projects/<project_id>/clips/<clip_id>", methods=["PUT"])
def update_clip(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    data = request.json
    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            clip["tag_type"] = data.get("tag_type", clip["tag_type"])
            clip["start"] = data.get("start", clip["start"])
            clip["end"] = data.get("end", clip["end"])
            clip["label"] = data.get("label", clip["label"])
            clip["notes"] = data.get("notes", clip["notes"])
            clip["players"] = data.get("players", clip.get("players", []))
            _save_projects(projects)
            return jsonify(clip)
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>", methods=["DELETE"])
def delete_clip(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    clips = projects[project_id]["clips"]
    projects[project_id]["clips"] = [c for c in clips if c["id"] != clip_id]
    _save_projects(projects)
    return jsonify({"ok": True})


# ── Annotations CRUD ──────────────────────────────────────────────────

@app.route("/api/projects/<project_id>/clips/<clip_id>/annotations", methods=["GET"])
def list_annotations(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            return jsonify(clip.get("annotations", []))
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>/annotations", methods=["POST"])
def create_annotation(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            data = request.json
            ann = {
                "id": str(uuid.uuid4())[:8],
                "type": data.get("type", ""),       # arrow, rect, circle, freehand, text
                "color": data.get("color", "#ff0000"),
                "lineWidth": data.get("lineWidth", 3),
                "startTime": data.get("startTime", clip["start"]),
                "endTime": data.get("endTime", clip["end"]),
                "data": data.get("data", {}),        # shape-specific coords (normalized 0-1)
            }
            if ann["type"] not in ("arrow", "rect", "circle", "freehand", "text"):
                return jsonify({"error": "Invalid annotation type"}), 400
            if "annotations" not in clip:
                clip["annotations"] = []
            clip["annotations"].append(ann)
            _save_projects(projects)
            return jsonify(ann), 201
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>/annotations/<ann_id>", methods=["PUT"])
def update_annotation(project_id, clip_id, ann_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            for ann in clip.get("annotations", []):
                if ann["id"] == ann_id:
                    data = request.json
                    ann["color"] = data.get("color", ann["color"])
                    ann["lineWidth"] = data.get("lineWidth", ann["lineWidth"])
                    ann["startTime"] = data.get("startTime", ann["startTime"])
                    ann["endTime"] = data.get("endTime", ann["endTime"])
                    ann["data"] = data.get("data", ann["data"])
                    _save_projects(projects)
                    return jsonify(ann)
            return jsonify({"error": "Annotation not found"}), 404
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>/annotations/<ann_id>", methods=["DELETE"])
def delete_annotation(project_id, clip_id, ann_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            anns = clip.get("annotations", [])
            clip["annotations"] = [a for a in anns if a["id"] != ann_id]
            _save_projects(projects)
            return jsonify({"ok": True})
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>/annotations", methods=["DELETE"])
def clear_annotations(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            clip["annotations"] = []
            _save_projects(projects)
            return jsonify({"ok": True})
    return jsonify({"error": "Clip not found"}), 404


# ── Recordings CRUD ───────────────────────────────────────────────────

@app.route("/api/projects/<project_id>/clips/<clip_id>/recordings", methods=["GET"])
def list_recordings(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404
    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            return jsonify(clip.get("recordings", []))
    return jsonify({"error": "Clip not found"}), 404


@app.route("/api/projects/<project_id>/clips/<clip_id>/recordings", methods=["POST"])
def upload_recording(project_id, clip_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    clip_found = None
    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            clip_found = clip
            break
    if not clip_found:
        return jsonify({"error": "Clip not found"}), 404

    if "recording" not in request.files:
        return jsonify({"error": "No recording file provided"}), 400

    rec_file = request.files["recording"]
    rec_id = str(uuid.uuid4())[:8]
    filename = f"{clip_id}_{rec_id}.webm"
    rec_file.save(os.path.join(RECORDINGS_DIR, filename))

    rec_meta = {
        "id": rec_id,
        "filename": filename,
        "duration": request.form.get("duration", ""),
    }

    if "recordings" not in clip_found:
        clip_found["recordings"] = []
    clip_found["recordings"].append(rec_meta)
    _save_projects(projects)
    return jsonify(rec_meta), 201


@app.route("/api/projects/<project_id>/clips/<clip_id>/recordings/<rec_id>", methods=["DELETE"])
def delete_recording(project_id, clip_id, rec_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    for clip in projects[project_id]["clips"]:
        if clip["id"] == clip_id:
            recs = clip.get("recordings", [])
            target = None
            for r in recs:
                if r["id"] == rec_id:
                    target = r
                    break
            if not target:
                return jsonify({"error": "Recording not found"}), 404
            # Remove file
            path = os.path.join(RECORDINGS_DIR, target["filename"])
            if os.path.exists(path):
                os.remove(path)
            clip["recordings"] = [r for r in recs if r["id"] != rec_id]
            _save_projects(projects)
            return jsonify({"ok": True})
    return jsonify({"error": "Clip not found"}), 404


@app.route("/recordings/<filename>")
def serve_recording(filename):
    return send_from_directory(RECORDINGS_DIR, filename)


# ── Video Editing ─────────────────────────────────────────────────────

def _ffmpeg_cut(input_path, output_path, start=None, end=None, duration=None):
    """Cut a segment from a video using ffmpeg. Returns (success, error)."""
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if duration is not None:
        cmd += ["-t", str(duration)]
    elif end is not None:
        if start is not None:
            cmd += ["-t", str(end - start)]
        else:
            cmd += ["-t", str(end)]
    cmd += ["-c", "copy", "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero", output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return False, result.stderr.decode()[-300:]
        return True, None
    except FileNotFoundError:
        return False, "ffmpeg not found"
    except subprocess.TimeoutExpired:
        return False, "Operation timed out"


def _ffmpeg_concat(segment_paths, output_path):
    """Concatenate video segments using ffmpeg. Returns (success, error)."""
    tmpdir = tempfile.mkdtemp()
    concat_file = os.path.join(tmpdir, "concat.txt")
    with open(concat_file, "w") as f:
        for seg in segment_paths:
            f.write(f"file '{seg}'\n")
    try:
        # Re-encode for reliable concat (segments may have different keyframe alignment)
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            output_path,
        ], capture_output=True, timeout=600)
        if result.returncode != 0:
            return False, result.stderr.decode()[-300:]
        return True, None
    except FileNotFoundError:
        return False, "ffmpeg not found"
    except subprocess.TimeoutExpired:
        return False, "Operation timed out"


def _get_video_path(project):
    """Get the video file path for a project, or None."""
    if not project.get("video_filename"):
        return None
    path = os.path.join(VIDEOS_DIR, project["video_filename"])
    return path if os.path.exists(path) else None


def _adjust_clips_after_edit(clips, time_offset, removed_ranges=None):
    """Adjust clip timestamps after a video edit.

    time_offset: subtract this from all timestamps (for trim start removal).
    removed_ranges: list of (start, end) ranges removed from video.
    Returns adjusted clips (clips fully inside removed ranges are dropped).
    """
    adjusted = []
    for c in clips:
        cs, ce = c["start"], c["end"]

        if removed_ranges:
            skip = False
            total_removed_before = 0
            for rs, re in removed_ranges:
                # Clip fully inside removed range -> drop it
                if cs >= rs and ce <= re:
                    skip = True
                    break
                # Removed range fully before clip -> shift
                if re <= cs:
                    total_removed_before += (re - rs)
                # Partial overlap -> clamp
                elif rs < ce and re > cs:
                    # Clip starts before removal
                    if cs < rs:
                        ce = min(ce, rs)
                    else:
                        cs = re
                        total_removed_before += (re - rs) - (cs - re) if cs > re else 0
            if skip:
                continue
            cs -= total_removed_before
            ce -= total_removed_before
        else:
            cs -= time_offset
            ce -= time_offset

        cs = max(cs, 0)
        if ce > cs:
            clip_copy = dict(c)
            clip_copy["start"] = round(cs, 3)
            clip_copy["end"] = round(ce, 3)
            adjusted.append(clip_copy)
    return adjusted


@app.route("/api/projects/<project_id>/video/trim", methods=["POST"])
def trim_video(project_id):
    """Trim the video to keep only the segment between start and end."""
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    video_path = _get_video_path(project)
    if not video_path:
        return jsonify({"error": "No video uploaded"}), 400

    data = request.json or {}
    start = data.get("start")
    end = data.get("end")
    if start is None or end is None:
        return jsonify({"error": "Both start and end times are required"}), 400
    if end <= start:
        return jsonify({"error": "End must be after start"}), 400

    ext = os.path.splitext(video_path)[1]
    output_path = os.path.join(VIDEOS_DIR, f"{project_id}_trimmed{ext}")
    ok, err = _ffmpeg_cut(video_path, output_path, start=start, end=end)
    if not ok:
        return jsonify({"error": f"Trim failed: {err}"}), 500

    # Replace the original video
    os.replace(output_path, video_path)

    # Adjust clip timestamps
    project["clips"] = _adjust_clips_after_edit(project["clips"], time_offset=start)
    _save_projects(projects)

    return jsonify({"ok": True, "message": f"Trimmed to {start}s - {end}s"})


@app.route("/api/projects/<project_id>/video/split", methods=["POST"])
def split_video(project_id):
    """Split the video at a timestamp into two projects."""
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    video_path = _get_video_path(project)
    if not video_path:
        return jsonify({"error": "No video uploaded"}), 400

    data = request.json or {}
    split_at = data.get("split_at")
    if split_at is None:
        return jsonify({"error": "split_at timestamp is required"}), 400
    if split_at <= 0:
        return jsonify({"error": "split_at must be positive"}), 400

    ext = os.path.splitext(video_path)[1]

    # Cut part 1: 0 to split_at
    part1_path = os.path.join(VIDEOS_DIR, f"{project_id}_part1{ext}")
    ok, err = _ffmpeg_cut(video_path, part1_path, start=0, end=split_at)
    if not ok:
        return jsonify({"error": f"Split failed (part 1): {err}"}), 500

    # Cut part 2: split_at to end
    part2_path = os.path.join(VIDEOS_DIR, f"{project_id}_part2{ext}")
    ok, err = _ffmpeg_cut(video_path, part2_path, start=split_at)
    if not ok:
        if os.path.exists(part1_path):
            os.remove(part1_path)
        return jsonify({"error": f"Split failed (part 2): {err}"}), 500

    # Create new project for part 2
    new_id = str(uuid.uuid4())[:8]
    new_video_filename = f"{new_id}{ext}"
    os.rename(part2_path, os.path.join(VIDEOS_DIR, new_video_filename))

    # Part 2 clips: those starting after split_at, shifted back
    part2_clips = _adjust_clips_after_edit(
        [c for c in project["clips"] if c["start"] >= split_at],
        time_offset=split_at
    )

    projects[new_id] = {
        "id": new_id,
        "name": f"{project['name']} (Part 2)",
        "video_filename": new_video_filename,
        "tag_types": list(project["tag_types"]),
        "players": list(project.get("players", [])),
        "clips": part2_clips,
    }

    # Replace original video with part 1
    os.replace(part1_path, video_path)

    # Keep only clips before split_at in original project
    project["clips"] = [c for c in project["clips"] if c["end"] <= split_at]
    project["name"] = f"{project['name']} (Part 1)" if "(Part" not in project["name"] else project["name"]

    _save_projects(projects)
    return jsonify({
        "ok": True,
        "original_project": project_id,
        "new_project": new_id,
        "message": f"Split at {split_at}s into two projects",
    })


@app.route("/api/projects/<project_id>/video/cut", methods=["POST"])
def cut_video(project_id):
    """Remove a section from the middle of the video (e.g., halftime)."""
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    video_path = _get_video_path(project)
    if not video_path:
        return jsonify({"error": "No video uploaded"}), 400

    data = request.json or {}
    cut_start = data.get("cut_start")
    cut_end = data.get("cut_end")
    if cut_start is None or cut_end is None:
        return jsonify({"error": "Both cut_start and cut_end are required"}), 400
    if cut_end <= cut_start:
        return jsonify({"error": "cut_end must be after cut_start"}), 400

    ext = os.path.splitext(video_path)[1]
    tmpdir = tempfile.mkdtemp()

    # Segment before the cut
    seg1_path = os.path.join(tmpdir, f"seg1{ext}")
    ok, err = _ffmpeg_cut(video_path, seg1_path, start=0, end=cut_start)
    if not ok:
        return jsonify({"error": f"Cut failed (segment 1): {err}"}), 500

    # Segment after the cut
    seg2_path = os.path.join(tmpdir, f"seg2{ext}")
    ok, err = _ffmpeg_cut(video_path, seg2_path, start=cut_end)
    if not ok:
        return jsonify({"error": f"Cut failed (segment 2): {err}"}), 500

    # Concatenate the two segments
    output_path = os.path.join(tmpdir, f"output{ext}")
    ok, err = _ffmpeg_concat([seg1_path, seg2_path], output_path)
    if not ok:
        return jsonify({"error": f"Cut concat failed: {err}"}), 500

    # Replace original
    os.replace(output_path, video_path)

    # Adjust clips: drop those inside the cut, shift those after
    cut_duration = cut_end - cut_start
    adjusted = []
    for c in project["clips"]:
        cs, ce = c["start"], c["end"]
        # Fully inside the cut -> drop
        if cs >= cut_start and ce <= cut_end:
            continue
        # Fully before the cut -> keep as-is
        if ce <= cut_start:
            adjusted.append(c)
            continue
        # Fully after the cut -> shift back
        if cs >= cut_end:
            clip_copy = dict(c)
            clip_copy["start"] = round(cs - cut_duration, 3)
            clip_copy["end"] = round(ce - cut_duration, 3)
            adjusted.append(clip_copy)
            continue
        # Partial overlap with cut start -> clamp end
        if cs < cut_start and ce > cut_start:
            clip_copy = dict(c)
            clip_copy["end"] = round(cut_start, 3)
            if clip_copy["end"] > clip_copy["start"]:
                adjusted.append(clip_copy)
            continue
        # Partial overlap with cut end -> clamp start, shift
        if cs < cut_end and ce > cut_end:
            clip_copy = dict(c)
            clip_copy["start"] = round(cut_start, 3)
            clip_copy["end"] = round(ce - cut_duration, 3)
            if clip_copy["end"] > clip_copy["start"]:
                adjusted.append(clip_copy)

    project["clips"] = adjusted
    _save_projects(projects)

    return jsonify({
        "ok": True,
        "message": f"Removed {cut_start}s - {cut_end}s ({cut_duration}s)",
    })


# ── Export ─────────────────────────────────────────────────────────────

def _filter_clips(project, params):
    """Filter clips by tag_type, player, and search query string."""
    clips = list(project["clips"])
    tag_type = params.get("tag_type", "")
    player = params.get("player", "")
    search = params.get("search", "").lower()
    clip_ids = params.get("clip_ids", "")

    if clip_ids:
        id_set = set(clip_ids.split(","))
        clips = [c for c in clips if c["id"] in id_set]
    if tag_type:
        clips = [c for c in clips if c["tag_type"] == tag_type]
    if player:
        clips = [c for c in clips if player in c.get("players", [])]
    if search:
        clips = [c for c in clips if
                 search in c.get("label", "").lower() or
                 search in c.get("notes", "").lower() or
                 search in c.get("tag_type", "").lower()]

    clips.sort(key=lambda c: c["start"])
    return clips


@app.route("/api/projects/<project_id>/export/csv")
def export_csv(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    clips = _filter_clips(project, request.args)
    players_map = {p["id"]: p for p in project.get("players", [])}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Clip ID", "Tag Type", "Start (s)", "End (s)",
                      "Duration (s)", "Label", "Notes", "Players"])

    for c in clips:
        player_names = []
        for pid in c.get("players", []):
            p = players_map.get(pid)
            if p:
                player_names.append(f"#{p['number']} {p['name']}" if p.get("number") else p["name"])
        writer.writerow([
            c["id"],
            c["tag_type"],
            round(c["start"], 2),
            round(c["end"], 2),
            round(c["end"] - c["start"], 2),
            c.get("label", ""),
            c.get("notes", ""),
            "; ".join(player_names),
        ])

    output.seek(0)
    safe_name = project["name"].replace(" ", "_")
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{safe_name}_clips.csv",
    )


@app.route("/api/projects/<project_id>/export/json")
def export_json(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    clips = _filter_clips(project, request.args)
    players_map = {p["id"]: p for p in project.get("players", [])}

    export_clips = []
    for c in clips:
        player_names = []
        for pid in c.get("players", []):
            p = players_map.get(pid)
            if p:
                player_names.append({"id": p["id"], "name": p["name"], "number": p.get("number", "")})
        export_clips.append({
            "id": c["id"],
            "tag_type": c["tag_type"],
            "start": round(c["start"], 2),
            "end": round(c["end"], 2),
            "duration": round(c["end"] - c["start"], 2),
            "label": c.get("label", ""),
            "notes": c.get("notes", ""),
            "players": player_names,
        })

    payload = json.dumps({
        "project": project["name"],
        "clip_count": len(export_clips),
        "clips": export_clips,
    }, indent=2)

    safe_name = project["name"].replace(" ", "_")
    return send_file(
        io.BytesIO(payload.encode("utf-8")),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"{safe_name}_clips.json",
    )


@app.route("/api/projects/<project_id>/export/video", methods=["POST"])
def export_video(project_id):
    projects = _load_projects()
    if project_id not in projects:
        return jsonify({"error": "Project not found"}), 404

    project = projects[project_id]
    if not project.get("video_filename"):
        return jsonify({"error": "No video uploaded for this project"}), 400

    video_path = os.path.join(VIDEOS_DIR, project["video_filename"])
    if not os.path.exists(video_path):
        return jsonify({"error": "Video file not found on disk"}), 404

    params = request.json or {}
    clips = _filter_clips(project, params)

    if not clips:
        return jsonify({"error": "No clips match the current filters"}), 400

    try:
        tmpdir = tempfile.mkdtemp()
        segment_files = []

        # Cut each clip segment
        for i, c in enumerate(clips):
            seg_path = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            duration = c["end"] - c["start"]
            result = subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(c["start"]),
                "-i", video_path,
                "-t", str(duration),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero",
                seg_path,
            ], capture_output=True, timeout=120)
            if result.returncode != 0:
                return jsonify({"error": f"ffmpeg segment cut failed: {result.stderr.decode()[-200:]}"}), 500
            segment_files.append(seg_path)

        # Build concat list
        concat_list_path = os.path.join(tmpdir, "concat.txt")
        with open(concat_list_path, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")

        # Concatenate
        output_path = os.path.join(tmpdir, "export.mp4")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ], capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": f"ffmpeg concat failed: {result.stderr.decode()[-200:]}"}), 500

        safe_name = project["name"].replace(" ", "_")
        return send_file(
            output_path,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"{safe_name}_playlist.mp4",
        )
    except FileNotFoundError:
        return jsonify({"error": "ffmpeg not found. Install ffmpeg to export video compilations."}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Video export timed out"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
