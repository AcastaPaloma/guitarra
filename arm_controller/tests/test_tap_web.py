import json
from unittest.mock import MagicMock

import calibration
import fret
import pytest
import webapp
from fastapi.testclient import TestClient
from rehearsal import RehearsalManager
from path_fixtures import fake_arm, path_registry
from test_rehearsal import (
    capture_end,
    capture_start,
    evaluate,
    execute,
    plan,
    registry,
    revise,
    wait_for,
    wav_bytes,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "thinkingmachines/inkling")
    reg = {**registry(), "warnings": []}
    monkeypatch.setattr(webapp, "read_registry", lambda: reg)
    manager = RehearsalManager(tmp_path, registry=lambda: reg, execute=MagicMock(side_effect=execute),
                               evaluate=MagicMock(side_effect=evaluate), revise=MagicMock(side_effect=revise),
                               lock=calibration.ownership_lock, calibration_active=calibration.session_active)
    monkeypatch.setattr(webapp, "manager", manager)
    monkeypatch.setattr(calibration, "KEYFRAMES_PATH", tmp_path / "keypoints.json")
    calibration.KEYFRAMES_PATH.write_text("[]")
    with TestClient(webapp.app, base_url="http://127.0.0.1:8788") as client:
        client.headers.update({"X-Session-Token": webapp.SESSION_TOKEN,
                               "Origin": "http://127.0.0.1:8788"})
        yield client
    for attempt in list(manager.attempts.values()):
        manager.stop(attempt.record["attempt_id"])


def preparation():
    return {"plan": plan().model_dump(), "allow_audio_upload": True,
            "allow_revision_inference": True, "supervised_and_supported": True}


def test_page_loading_opens_no_device_or_model(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/capture.js").status_code == 200
    assert client.get("/calibrate").status_code == 200
    data = client.get("/api/bootstrap").json()
    assert data["path_profiles"] == [] and data["camera"] is False
    assert data["preferred_path_profile"] == "lift_first"
    assert data["auto_replay"] is False and data["active_attempt"] is None
    assert not webapp.manager.execute.called and not webapp.manager.evaluate.called


@pytest.mark.parametrize("field", ["allow_audio_upload", "allow_revision_inference", "supervised_and_supported"])
def test_each_take_requires_explicit_consent(client, field):
    data = preparation()
    del data[field]
    assert client.post("/api/attempts", json=data).status_code == 422
    for value in (False, 1, "true"):
        data[field] = value
        assert client.post("/api/attempts", json=data).status_code == 422
    assert not webapp.manager.execute.called


def test_capture_ready_required_and_end_to_end_wav_binding(client):
    record = client.post("/api/attempts", json=preparation()).json()
    assert record["phase"] == "ready" and not webapp.manager.execute.called
    start = {"attempt_id": record["attempt_id"], **capture_start(record).model_dump()}
    incomplete = {**start, "capture_ready": False}
    assert client.post("/api/play", json=incomplete).status_code == 422
    assert client.post("/api/play", json=start).status_code == 200
    wait_for(webapp.manager, record, {"awaiting_audio"})
    headers = {"Content-Type": "audio/wav", "X-Capture-Metadata": capture_end(record).model_dump_json()}
    result = client.post(f"/api/attempts/{record['attempt_id']}/audio", headers=headers, content=wav_bytes())
    assert result.status_code == 200, result.text
    final = wait_for(webapp.manager, record, {"review_ready"})
    assert final["revision"]["changes"][0]["after_ms"] == 300
    assert webapp.manager.execute.call_count == 1
    assert client.post("/api/play", json=start).status_code == 200  # idempotent, NOT replay
    assert webapp.manager.execute.call_count == 1


def test_session_history_audio_access_and_tuning_reuse_are_explicit(client):
    record = client.post("/api/attempts", json=preparation()).json()
    start = {"attempt_id": record["attempt_id"], **capture_start(record).model_dump()}
    client.post("/api/play", json=start)
    wait_for(webapp.manager, record, {"awaiting_audio"})
    headers = {"Content-Type": "audio/wav", "X-Capture-Metadata": capture_end(record).model_dump_json()}
    assert client.post(f"/api/attempts/{record['attempt_id']}/audio", headers=headers, content=wav_bytes()).status_code == 200
    wait_for(webapp.manager, record, {"review_ready"})
    session_id = record["session_id"]
    assert client.get("/api/sessions").json()["sessions"][0]["take_count"] == 1
    history = client.get(f"/api/sessions/{session_id}").json()
    assert history["takes"][0]["audio_available"]
    audio_url = f"/api/attempts/{record['attempt_id']}/audio"
    assert client.get(audio_url, headers={"X-Session-Token": ""}).status_code == 403
    assert client.get(audio_url).content == wav_bytes()
    preferred = client.post(f"/api/sessions/{session_id}/preferred", json={"attempt_id": record["attempt_id"]})
    assert preferred.json()["takes"][0]["preferred_by_operator"]
    reused = client.post("/api/attempts", json={**preparation(), "session_id": session_id,
                                               "source_attempt_id": record["attempt_id"]}).json()
    assert reused["take_number"] == 2 and reused["phase"] == "ready"
    assert reused["capture_id"] != record["capture_id"]
    assert webapp.manager.execute.call_count == 1  # loading never executes a recording or plan


def test_security_host_origin_token_content_type_and_size(client, monkeypatch):
    assert client.get("/api/bootstrap", headers={"Host": "evil.test"}).status_code == 403
    assert client.post("/api/attempts", json=preparation(), headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/attempts", json=preparation(), headers={"X-Session-Token": "wrong"}).status_code == 403
    assert client.post("/api/attempts", content='{}', headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/attempts", content='x' * 65537,
                       headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/attempts", content=iter([b'x' * 40000, b'y' * 40000]),
                       headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/attempts", json={**preparation(), "torque": 180}).status_code == 422
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "moonshotai/Kimi-K3")
    assert client.post("/api/attempts", json=preparation()).status_code == 409
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "thinkingmachines/inkling")
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN", raising=False)
    assert client.post("/api/attempts", json=preparation()).status_code == 409
    assert not webapp.manager.execute.called


def test_calibration_cannot_connect_or_change_grid_during_reserved_take(client):
    record = client.post("/api/attempts", json=preparation()).json()
    before = calibration.KEYFRAMES_PATH.read_bytes()
    assert client.post("/api/cal/connect", json={}).status_code == 409
    assert client.post("/api/cal/keypoints/clear", json={}).status_code == 409
    assert calibration.KEYFRAMES_PATH.read_bytes() == before
    assert client.post("/api/stop", json={"attempt_id": record["attempt_id"]}).json()["phase"] == "stopped"
    assert not webapp.manager.execute.called


def test_no_default_grid_fallback_or_planning_spend_with_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "empty-keypoints.json"
    path.write_text("[]")
    monkeypatch.setattr(fret, "KEYFRAMES_PATH", path)
    with pytest.raises(ValueError, match="backup/old"):
        webapp.read_registry()


def test_registry_rejects_partial_or_gripper_poses(tmp_path, monkeypatch):
    path = tmp_path / "keypoints.json"
    positions = {str(s): 1000 for s in fret.MOTOR_IDS}
    data = [{"name": "rest", "positions": positions}, {"name": "pose-r1-c1", "positions": positions}]
    path.write_text(json.dumps(data))
    monkeypatch.setattr(fret, "KEYFRAMES_PATH", path)
    snapshot = webapp.read_registry()
    positions["12"] = 1000
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        webapp.read_registry()
    positions.pop("12")
    positions["7"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        webapp.read_registry()
    assert snapshot["keys"] == {(1, 1)}


def test_executor_disconnect_is_body_only_no_homing_even_on_fault(monkeypatch):
    import threading
    arm = MagicMock()
    monkeypatch.setattr(webapp, "read_registry", path_registry)
    monkeypatch.setattr(fret, "FretArm", lambda **kwargs: arm)
    take = plan().model_copy(update={"path_profile": "lift_first"})
    assert webapp.execute_take(take, path_registry(), threading.Event(), lambda event: None)
    arm.close.assert_called_once_with(torque_off=False)  # reviewed final exit; held there
    arm.rest.assert_called_once()
    assert "deadline" in arm.rest.call_args.kwargs
    arm.reset_mock()
    arm.tap_key.side_effect = TimeoutError("fixture")
    with pytest.raises(TimeoutError):
        webapp.execute_take(take, path_registry(), threading.Event(), lambda event: None)
    arm.close.assert_called_once_with(torque_off=True)
    arm.rest.assert_not_called()
    assert arm.tap_key.call_count == 1


def test_gripper_never_commanded_on_disconnect_or_any_stage():
    arm = object.__new__(fret.FretArm)
    arm.bus = MagicMock()
    arm.close(torque_off=True)
    assert [call.args for call in arm.bus.set_torque.call_args_list] == [(sid, False) for sid in fret.MOTOR_IDS]
    assert 12 not in fret.MOTOR_IDS
    bad_pose = {sid: 1000 for sid in [7, 8, 9, 10, 11, 12]}
    with pytest.raises(ValueError):
        arm._move(bad_pose, fret.TRAVEL_SPEED)
    arm.bus.goto.assert_not_called()


def test_encoder_timeout_is_not_ignored_and_does_not_press(monkeypatch):
    arm = object.__new__(fret.FretArm)
    arm.bus = MagicMock()
    arm.bus.read_pos.return_value = None
    pose = {sid: 1000 for sid in fret.MOTOR_IDS}
    monkeypatch.setattr(fret, "SETTLE_TIMEOUT", 0.001)
    with pytest.raises(TimeoutError):
        arm._move(pose, fret.TRAVEL_SPEED)
    assert {call.args[0] for call in arm.bus.goto.call_args_list} == set(fret.MOTOR_IDS)
    arm, _, _, _ = fake_arm(monkeypatch)
    arm._move = MagicMock(side_effect=TimeoutError("fixture"))
    with pytest.raises(TimeoutError):
        arm.tap_key(1, 1)
    assert arm._move.call_count == 1  # no press/lift/recovery after failed initial hover entry
