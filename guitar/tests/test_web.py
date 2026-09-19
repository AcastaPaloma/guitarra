"""Local dashboard checks. Scripted backends only; no network inference or devices."""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")  # optional dashboard dependencies
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.backends import Turn  # noqa: E402
from agent.protocol import ToolCall  # noqa: E402
from orchestration.control import RunControl  # noqa: E402
from web.app import create_app  # noqa: E402

PROFILE = "dryrun_default"
PLAN = [("ready", {"arm": "pick"}),
        ("press", {"string": 5, "fret": 5, "profile": PROFILE}),
        ("pluck", {"string": 5, "profile": PROFILE}),
        ("release", {}), ("done", {"outcome": "completed", "reason": "offline web check"})]


class Scripted:
    name = "scripted_test"
    model = "offline_not_baseten"

    def __init__(self, entered=None, release=None):
        self.steps = iter(PLAN)
        self.n = 0
        self.entered, self.release = entered, release
        self.opening = None

    def next(self):
        name, args = next(self.steps)
        self.n += 1
        return Turn("", [ToolCall(str(self.n), name, args)], stop="tool_use")

    def begin(self, system, specs, text, image_jpeg):
        assert image_jpeg is None
        self.opening = json.loads(text)
        if self.entered:
            self.entered.set()
            assert self.release.wait(3)
        return self.next()

    def respond(self, results, note=None):
        return self.next()


def wait_for(client, job_id, predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        job = client.get(f"/api/runs/{job_id}").json()
        if predicate(job):
            return job
        time.sleep(0.01)
    raise AssertionError("Worker did not reach expected state")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-server-credential-never-return")
    backends = []
    def factory(**kwargs):
        backend = Scripted()
        backends.append(backend)
        return backend
    app = create_app(root=tmp_path / "runs", backend_factory=factory, key_ready=lambda: True, request_interval=0)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        config = client.get("/api/bootstrap").json()
        headers = {"X-Session-Token": config["session_token"]}
        yield client, app, headers, backends


def test_bootstrap_static_files_and_secret_boundary(setup):
    client, _, _, _ = setup
    response = client.get("/api/bootstrap")
    assert response.json()["mode"] == "fake_only"
    assert response.json()["hardware_enabled"] is False
    assert "test-server-credential-never-return" not in response.text
    assert len(response.json()["tools"]) == 11
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/style.css").status_code == 200
    assert client.get("/assets/.env").status_code == 404
    assert client.get("/.env").status_code == 404
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_host_origin_csrf_and_consent_are_enforced(setup):
    client, _, headers, backends = setup
    body = {"scenario": "single-note", "allow_inference": True}
    assert client.post("/api/runs", json=body).status_code == 403
    assert client.post("/api/runs", headers={**headers, "Origin": "https://evil.example"}, json=body).status_code == 403
    assert client.get("/api/bootstrap", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/runs", headers=headers, json={"scenario": "single-note"}).status_code == 422
    assert client.post("/api/runs", headers=headers, json={**body, "hardware_enabled": True}).status_code == 422
    assert not backends


def test_rejects_credential_in_prompt_without_echoing_it(setup):
    client, _, headers, backends = setup
    response = client.post("/api/runs", headers=headers, json={"allow_inference": True,
        "prompt": "accidental test-server-credential-never-return"})
    assert response.status_code == 422
    assert "test-server-credential-never-return" not in response.text
    assert not backends


def test_run_prompt_events_history_and_downloads(setup):
    client, _, headers, backends = setup
    start = client.post("/api/runs", headers=headers, json={"scenario": "single-note",
        "allow_inference": True, "prompt": "Use minimal approach calls."})
    assert start.status_code == 202
    job_id = start.json()["id"]
    job = wait_for(client, job_id, lambda x: x["status"] == "finished")
    assert job["report"]["evaluation"]["passed"]
    assert backends[0].opening["operator_prompt"] == "Use minimal approach calls."
    events = client.get(f"/api/runs/{job_id}/events").json()
    assert any(e["type"] == "tool" for e in events["events"])
    assert any(e["type"] == "summary" for e in events["events"])
    assert client.get(f"/api/runs/{job_id}/events?after={events['next_cursor']}").json()["events"] == []
    download = client.get(f"/api/runs/{job_id}/files/summary.json")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert download.json()["hardware_enabled"] is False
    assert client.get(f"/api/runs/{job_id}/files/.env").status_code == 404
    assert client.get('/api/runs/not-a-valid-id').status_code == 404
    history = client.get("/api/runs").json()
    assert history["active_id"] is None and history["runs"][0]["id"] == job_id


def test_custom_notes_schema_and_fault_constraints(setup):
    client, _, headers, backends = setup
    for data in [
        {"scenario": "custom", "notes": []},
        {"scenario": "custom", "notes": [{"string": True, "fret": 5}]},
        {"scenario": "custom", "notes": [{"string": 5, "fret": 12}], "inject_fret_failure": True},
        {"scenario": "single-note", "notes": [{"string": 5, "fret": 5}]},
        {"seconds": -1}, {"max_calls": 10000}, {"prompt": "a" * 8001},
    ]:
        response = client.post("/api/runs", headers=headers, json={"allow_inference": True, **data})
        assert response.status_code == 422
    assert not backends
    start = client.post("/api/runs", headers=headers, json={"allow_inference": True, "scenario": "custom",
        "notes": [{"string": 5, "fret": 5}], "prompt": "One note then lift."})
    job = wait_for(client, start.json()["id"], lambda x: x["status"] == "finished")
    assert job["report"]["evaluation"]["passed"]
    assert job["report"]["scenario"] == "custom"


def test_cancel_during_request_discards_response_and_prevents_second_run(tmp_path):
    entered, release = threading.Event(), threading.Event()
    backend = Scripted(entered, release)
    app = create_app(root=tmp_path, backend_factory=lambda **kwargs: backend, key_ready=lambda: True, request_interval=0)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        headers = {"X-Session-Token": client.get("/api/bootstrap").json()["session_token"]}
        body = {"scenario": "single-note", "allow_inference": True}
        job_id = client.post("/api/runs", headers=headers, json=body).json()["id"]
        try:
            assert entered.wait(2)
            assert client.post("/api/runs", headers=headers, json=body).status_code == 409
            assert client.post(f"/api/runs/{job_id}/stop", headers=headers, json={}).json()["status"] == "stopping"
        finally:
            release.set()
        job = wait_for(client, job_id, lambda x: x["status"] == "finished")
        assert job["report"]["stop_reason"] == "cancelled"
        assert job["report"]["evaluation"]["status"] == "incomplete"
        assert job["report"]["evaluation"]["tool_calls"] == 0


def test_pause_gates_pending_call_until_resume(tmp_path):
    entered, release = threading.Event(), threading.Event()
    backend = Scripted(entered, release)
    app = create_app(root=tmp_path, backend_factory=lambda **kwargs: backend, key_ready=lambda: True, request_interval=0)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        headers = {"X-Session-Token": client.get("/api/bootstrap").json()["session_token"]}
        job_id = client.post("/api/runs", headers=headers, json={"scenario": "single-note", "allow_inference": True}).json()["id"]
        try:
            assert entered.wait(2)
            client.post(f"/api/runs/{job_id}/pause", headers=headers, json={})
        finally:
            release.set()
        paused = wait_for(client, job_id, lambda x: x["status"] == "paused")
        assert paused["state"]["plucks_so_far"] == 0
        assert not any(e["type"] == "tool" for e in client.get(f"/api/runs/{job_id}/events").json()["events"])
        client.post(f"/api/runs/{job_id}/resume", headers=headers, json={})
        done = wait_for(client, job_id, lambda x: x["status"] == "finished")
        assert done["report"]["evaluation"]["passed"]


def test_historical_reports_survive_restart_and_cannot_escape_root(tmp_path):
    root = tmp_path / "runs"
    directory = root / "old-batch" / "case"
    directory.mkdir(parents=True)
    (directory / "summary.json").write_text(json.dumps({"scenario": "single-note", "checked_at_utc": "2026-01-01T00:00:00Z", "evaluation": {"status": "passed", "passed": True}}))
    outside = tmp_path / "private.env"
    outside.write_text("must-not-be-served")
    (directory / "tools.json").symlink_to(outside)
    app = create_app(root=root, key_ready=lambda: False)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        rows = client.get("/api/runs").json()["runs"]
        assert rows[0]["result"] == "passed"
        job_id = rows[0]["id"]
        assert client.get(f"/api/runs/{job_id}/files/summary.json").status_code == 200
        rejected = client.get(f"/api/runs/{job_id}/files/tools.json")
        assert rejected.status_code == 404 and "must-not-be-served" not in rejected.text


def test_paused_budget_expires_without_dispatch():
    control = RunControl()
    control.pause()
    assert control.wait(time.monotonic() + 0.01) == "paused_budget_exhausted"
