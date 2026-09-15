"""Test-only server for the real-browser bulk-edit checks.

Serves the checked-out application from a disposable data directory with
synthetic projects, and adds one route the application itself does not have:
``POST /__test/reset`` rebuilds the fixtures so every scenario starts from the
same known state. Nothing here touches user footage or the real data dir.

Media: when ``ffmpeg`` is on PATH a 12-second synthetic H.264 clip is
generated; otherwise an empty placeholder file stands in. A placeholder proves
the tagging interaction only, not playback or ffmpeg behaviour, and the
startup line says which one is in use.

Run directly (prints one JSON line with url/data/media, then serves):

    python tests/browser/server.py

``GAMETAPE_ROOT`` overrides the source tree; ``GAMETAPE_PORT`` the port
(default 0 = pick a free one).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("GAMETAPE_ROOT", Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0, str(ROOT))
import app as application  # noqa: E402

DATA = Path(tempfile.mkdtemp(prefix="gametape-browser-"))
application.DATA_DIR = str(DATA)
application.PROJECTS_FILE = str(DATA / "projects.json")
application.VIDEOS_DIR = str(DATA / "videos")
application.RECORDINGS_DIR = str(DATA / "recordings")
for path in (application.VIDEOS_DIR, application.RECORDINGS_DIR):
    os.makedirs(path, exist_ok=True)
application.app.config["TESTING"] = True


def make_video():
    video = Path(application.VIDEOS_DIR) / "synthetic.mp4"
    if shutil.which("ffmpeg"):
        done = subprocess.run([
            "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=c=darkgreen:s=960x540:d=12:r=15", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-y", str(video)], capture_output=True)
        if done.returncode == 0 and video.stat().st_size:
            return video.name, "ffmpeg"
    video.write_bytes(b"")
    return video.name, "placeholder"


VIDEO_NAME, MEDIA = make_video()


def build_fixtures():
    """Two projects, one player, three clips each (Pass, Pass, Shot), two presets."""
    with application._STORE_LOCK:
        application._BULK_PREVIEWS.clear()
        application._save_projects({})
        fixtures = {}
        with application.app.test_client() as client:
            for name in ("Bulk QA Match", "Other QA Match"):
                pid = client.post("/api/projects", json={"name": name}).get_json()["id"]
                player = client.post(f"/api/projects/{pid}/players",
                                     json={"name": "Alex QA", "number": "9"}).get_json()
                clips = []
                for index, (tag, label) in enumerate([
                        ("Pass", "Left channel"), ("Pass", "Right channel"), ("Shot", "Goal attempt")]):
                    clip = client.post(f"/api/projects/{pid}/clips", json={
                        "tag_type": tag, "start": index * 3, "end": index * 3 + 2,
                        "label": label, "players": [player["id"]],
                    }).get_json()
                    clips.append(clip["id"])
                fixtures[name] = {"project_id": pid, "player_id": player["id"], "clip_ids": clips}
            pid = fixtures["Bulk QA Match"]["project_id"]
            for tag in ("Pass", "Goal"):
                client.post(f"/api/projects/{pid}/filter_presets", json={"name": "QA " + tag, "tag_type": tag})
        projects = application._load_projects()
        for project in projects.values():
            project["video_filename"] = VIDEO_NAME
        application._save_projects(projects)
    return fixtures


@application.app.route("/__test/reset", methods=["POST"])
def _reset_fixtures():
    return application.jsonify(build_fixtures())


def free_port():
    wanted = int(os.environ.get("GAMETAPE_PORT", "0"))
    if wanted:
        return wanted
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    port = free_port()
    fixtures = build_fixtures()
    print(json.dumps({"url": f"http://127.0.0.1:{port}", "data": str(DATA),
                      "media": MEDIA, "fixtures": fixtures}), flush=True)
    try:
        application.app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
