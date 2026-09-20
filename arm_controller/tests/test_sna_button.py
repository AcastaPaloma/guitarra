"""The extra-pose riff cannot bypass the current lift-first requirement."""
from unittest.mock import Mock

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
    assert response.status_code == 409 and "lift/hover paths" in response.json()["detail"]


def test_riff_blocks_takes_and_takes_block_riff(client, monkeypatch):  # noqa: F811
    webapp._sna["running"] = True
    try:
        assert client.post("/api/attempts", json=preparation()).status_code == 409
        monkeypatch.setattr(fret, "load_map", all_extras)
        assert client.post("/api/play-sna",
                           json={"supervised_and_supported": True}).status_code == 409
    finally:
        webapp._sna["running"] = False


def test_recorded_extra_contacts_alone_do_not_allow_riff_motion(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(fret, "load_map", all_extras)
    factory = Mock(side_effect=AssertionError("contact-only riff must not connect"))
    monkeypatch.setattr(fret, "FretArm", factory)
    response = client.post("/api/play-sna", json={"supervised_and_supported": True})
    assert response.status_code == 409 and "no rest-hub fallback" in response.json()["detail"]
    factory.assert_not_called()
    status = client.get("/api/status").json()["sna"]
    assert status["running"] is False and status["error"] is None
