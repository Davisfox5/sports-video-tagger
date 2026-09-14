import json
import os
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as application


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with a temp data directory."""
    monkeypatch.setattr(application, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(application, "VIDEOS_DIR", str(tmp_path / "videos"))
    monkeypatch.setattr(application, "RECORDINGS_DIR", str(tmp_path / "recordings"))
    monkeypatch.setattr(application, "PROJECTS_FILE", str(tmp_path / "projects.json"))
    os.makedirs(tmp_path / "videos", exist_ok=True)
    os.makedirs(tmp_path / "recordings", exist_ok=True)
    application.app.config["TESTING"] = True
    with application.app.test_client() as c:
        yield c


def test_concurrent_clip_updates_are_not_lost(client, monkeypatch):
    rv = client.post("/api/projects", json={"name": "Concurrent"})
    pid = rv.get_json()["id"]

    rv = client.post(f"/api/projects/{pid}/clips", json={
        "tag_type": "Pass", "start": 1, "end": 3, "label": "orig-a",
    })
    clip_a = rv.get_json()["id"]

    rv = client.post(f"/api/projects/{pid}/clips", json={
        "tag_type": "Shot", "start": 5, "end": 8, "label": "orig-b",
    })
    clip_b = rv.get_json()["id"]

    armed = False
    barrier = threading.Barrier(2, timeout=5)
    original_load = application._load_projects

    def wrapped_load():
        projects = original_load()
        if armed:
            # With @_locked the second thread cannot enter _load_projects until
            # the first handler finishes, so the barrier times out. That timeout
            # path (BrokenBarrierError) is the expected behaviour when the lock
            # is present.
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return projects

    monkeypatch.setattr(application, "_load_projects", wrapped_load)
    armed = True

    errors = []

    def put_label(clip_id, label):
        try:
            c = application.app.test_client()
            resp = c.put(
                f"/api/projects/{pid}/clips/{clip_id}",
                json={"label": label},
            )
            if resp.status_code != 200:
                errors.append((clip_id, resp.status_code, resp.get_data(as_text=True)))
        except Exception as exc:
            errors.append((clip_id, repr(exc)))

    t1 = threading.Thread(target=put_label, args=(clip_a, "label-a"))
    t2 = threading.Thread(target=put_label, args=(clip_b, "label-b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, errors

    rv = client.get(f"/api/projects/{pid}")
    clips = {c["id"]: c["label"] for c in rv.get_json()["clips"]}
    assert clips[clip_a] == "label-a"
    assert clips[clip_b] == "label-b"
