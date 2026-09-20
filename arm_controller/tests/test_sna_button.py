"""Riff button: consent + ownership gating, and the end-of-motion contract."""
import time

import fret
import webapp
from test_tap_web import client, preparation  # noqa: F401 - fixture + helper

POSE = {sid: 1000 for sid in fret.MOTOR_IDS}


def all_extras(**_kwargs):
    return {"extras": {name: POSE for name, _ in fret.SNA_RIFF}}


def test_riff_requires_explicit_consent(client):  # noqa: F811
    assert client.post("/api/play-sna", json={}).status_code == 422
    assert client.post("/api/play-sna",
                       json={"supervised_and_supported": "yes"}).status_code == 422


def test_riff_refuses_without_recorded_poses(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fret, "load_map", lambda **kwargs: {"extras": {}})
    response = client.post("/api/play-sna", json={"supervised_and_supported": True})
    assert response.status_code == 409 and "poses" in response.json()["detail"]


def test_riff_blocks_takes_and_takes_block_riff(client, monkeypatch):  # noqa: F811
    webapp._sna["running"] = True
    try:
        assert client.post("/api/attempts", json=preparation()).status_code == 409
        monkeypatch.setattr(fret, "load_map", all_extras)
        assert client.post("/api/play-sna",
                           json={"supervised_and_supported": True}).status_code == 409
    finally:
        webapp._sna["running"] = False


class FakeArm:
    def __init__(self, **kwargs):
        self.calls = []

    def tap_pose(self, name, **_kwargs):
        self.calls.append(("tap", name))
        return {"status": "command_completed", "pose": name}

    def rest(self):
        self.calls.append(("rest",))

    def close(self, torque_off=False):
        self.calls.append(("close", torque_off))


def test_riff_plays_all_taps_then_parks_and_holds(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fret, "load_map", all_extras)
    monkeypatch.setattr(fret, "SNA_RIFF", [("7", 0), ("10", 0)])
    arms = []

    def fake_arm(**kwargs):
        arm = FakeArm(**kwargs)
        arms.append(arm)
        return arm

    monkeypatch.setattr(fret, "FretArm", fake_arm)
    response = client.post("/api/play-sna", json={"supervised_and_supported": True})
    assert response.status_code == 200 and response.json()["total"] == 2
    deadline = time.monotonic() + 5
    while webapp.sna_running() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not webapp.sna_running()
    assert arms[0].calls == [("tap", "7"), ("tap", "10"), ("rest",), ("close", False)]
    status = client.get("/api/status").json()["sna"]
    assert status["running"] is False and status["error"] is None
