"""Offline Inkling/Small budgeting, cancellation and evidence contract regressions."""
import json

import pytest

from test_audio_evaluator import fake_client, response, wav_file  # noqa: F401
from model import audio, baseten
from model.baseten import BasetenError, BasetenRequestError


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline test tried a live Baseten request")
    monkeypatch.setattr(baseten, "request_json", forbidden)


def evaluate(path, **kwargs):
    return audio.evaluate_file(path, expected_phrase="A2", attempt_id="one", allow_upload=True, **kwargs)


def test_current_duration_boundary_is_preserved(tmp_path):
    assert audio.prepare_clip(wav_file(tmp_path, seconds=audio.MAX_SECONDS)).metadata["duration_s"] == audio.MAX_SECONDS


@pytest.mark.parametrize("http_status", [None, 408, 429, 500, 502, 503, 504, 529])
def test_transient_failure_uses_one_visible_small_fallback(tmp_path, fake_client, http_status):
    client, factory = fake_client
    client.chat.side_effect = [BasetenRequestError("Fixture transport failure", status_code=http_status), response()]
    report = evaluate(wav_file(tmp_path))
    assert report["status"] == "assessed"
    assert report["primary_model"] == report["model_fallback_from"] == "thinkingmachines/inkling"
    assert report["model"] == "thinkingmachines/inkling-small"
    assert [call.kwargs["model"] for call in factory.call_args_list] == ["thinkingmachines/inkling", "thinkingmachines/inkling-small"]
    assert [r["status"] for r in report["requests"]] == ["unavailable", "assessed"]
    assert report["requests"][0]["http_status"] == http_status
    assert "error" not in report


@pytest.mark.parametrize("http_status", [400, 401, 402, 403, 404, 422])
def test_access_billing_or_invalid_requests_do_not_trigger_fallback(tmp_path, fake_client, http_status):
    client, factory = fake_client
    client.chat.side_effect = BasetenRequestError("Fixture access/request failure", status_code=http_status)
    report = evaluate(wav_file(tmp_path))
    assert report["status"] == "unavailable" and report["assessment"] is None
    assert factory.call_count == client.chat.call_count == 1
    assert "model_fallback_from" not in report


def test_two_transport_failures_exhaust_request_budget(tmp_path, fake_client):
    client, factory = fake_client
    client.chat.side_effect = BasetenRequestError("Fixture timeout", kind="timeout")
    report = evaluate(wav_file(tmp_path))
    assert factory.call_count == client.chat.call_count == 2
    assert report["status"] == "unavailable" and report["assessment"] is None
    assert len(report["requests"]) == 2 and report["error_kind"] == "timeout"


def test_explicit_small_has_no_further_fallback(tmp_path, fake_client, monkeypatch):
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "thinkingmachines/inkling-small")
    client, _ = fake_client
    client.chat.side_effect = BasetenRequestError("Fixture timeout")
    report = evaluate(wav_file(tmp_path))
    assert client.chat.call_count == report["max_requests"] == 1
    assert report["assessment"] is None


def test_cancellation_blocks_initial_request(tmp_path, fake_client):
    report = evaluate(wav_file(tmp_path), should_stop=lambda: True)
    assert not fake_client[1].called
    assert report["error_kind"] == "cancelled" and report["requests"] == []


def test_stop_during_primary_failure_blocks_fallback(tmp_path, fake_client):
    client, factory = fake_client
    stopped = []
    def fail(*args, **kwargs):
        stopped.append(True)
        raise BasetenRequestError("Fixture timeout")
    client.chat.side_effect = fail
    report = evaluate(wav_file(tmp_path), should_stop=lambda: bool(stopped))
    assert client.chat.call_count == factory.call_count == 1
    assert report["assessment"] is None and report["error_kind"] == "cancelled"


@pytest.mark.parametrize("late_response", [False, True])
def test_expired_budget_discards_result_or_blocks_fallback(tmp_path, fake_client, monkeypatch, late_response):
    client, factory = fake_client
    now = [0.0]
    monkeypatch.setattr(audio.time, "monotonic", lambda: now[0])
    def complete_late(*args, **kwargs):
        now[0] = 76
        if late_response:
            return response()
        raise BasetenRequestError("Fixture timeout")
    client.chat.side_effect = complete_late
    report = evaluate(wav_file(tmp_path))
    assert client.chat.call_count == factory.call_count == 1
    assert report["assessment"] is None and report["status"] == "unavailable"
    assert report["error_kind"] in {"deadline", "cancelled_or_late"}


def test_configured_timeouts_cannot_outwait_total_budget(tmp_path, fake_client, monkeypatch):
    client, factory = fake_client
    monkeypatch.setenv("BASETEN_AUDIO_TIMEOUT_S", "999")
    now = [0.0]
    monkeypatch.setattr(audio.time, "monotonic", lambda: now[0])
    def fail(*args, **kwargs):
        now[0] += 37.5
        raise BasetenRequestError("Fixture timeout")
    client.chat.side_effect = fail
    evaluate(wav_file(tmp_path))
    assert [c.kwargs["timeout_s"] for c in factory.call_args_list] == [37.5, 37.5]


def metrics_for(path):
    return {"schema_version": "fixture", "status": "limited",
            "source_sha256": audio.prepare_clip(path).metadata["source_sha256"],
            "per_note": [{"index": 0, "pitch_match": None}],
            "alignment": {"calibrated": False, "intended_onset_schedule_available": False}}


def test_local_measurements_and_capture_estimates_reach_inkling(tmp_path, fake_client):
    path = wav_file(tmp_path)
    metrics = metrics_for(path)
    report = evaluate(path, acoustic_metrics=metrics)
    context = json.loads(fake_client[0].chat.call_args.args[0][1]["content"][0]["text"])
    assert context["local_acoustic_measurements"] == metrics
    assert context["capture_signal_estimates"]["rms_dbfs"] is None
    assert report["measurement_schema_version"] == "fixture"
    metrics["per_note"].clear()
    assert len(context["local_acoustic_measurements"]["per_note"]) == 1


@pytest.mark.parametrize("mutation", ["wrong_clip", "nonfinite", "oversize", "bad_alignment"])
def test_invalid_measurements_are_rejected_before_upload(tmp_path, fake_client, mutation):
    path = wav_file(tmp_path)
    metrics = metrics_for(path)
    if mutation == "wrong_clip": metrics["source_sha256"] = "0" * 64
    elif mutation == "nonfinite": metrics["per_note"][0]["hz"] = float("nan")
    elif mutation == "bad_alignment": metrics["alignment"] = None
    else: metrics["extra"] = "x" * audio.MAX_MEASUREMENT_CHARS
    with pytest.raises(ValueError):
        evaluate(path, acoustic_metrics=metrics)
    assert not fake_client[1].called


def test_unavailable_dsp_can_be_disclosed_without_fake_measurements(tmp_path, fake_client):
    metrics = {"status": "unavailable", "error": "Fixture analyzer unavailable"}
    report = evaluate(wav_file(tmp_path), acoustic_metrics=metrics)
    assert report["status"] == "assessed"
    context = json.loads(fake_client[0].chat.call_args.args[0][1]["content"][0]["text"])
    assert context["local_acoustic_measurements"] == metrics


@pytest.mark.parametrize("quality", ["unusable", "uncertain", "usable"])
def test_unassessed_audio_cannot_be_given_a_numeric_score(quality):
    raw = response()
    data = json.loads(raw["choices"][0]["message"]["content"])
    data.update(recording_quality=quality, score=0)
    raw["choices"][0]["message"]["content"] = json.dumps(data)
    with pytest.raises(BasetenError):
        audio.parse_assessment(raw)
    data["score"] = None
    raw["choices"][0]["message"]["content"] = json.dumps(data)
    assert audio.parse_assessment(raw)["score"] is None


def test_timing_accuracy_requires_a_target_not_encoder_offsets(tmp_path, fake_client):
    path = wav_file(tmp_path)
    raw = response()
    data = json.loads(raw["choices"][0]["message"]["content"])
    data.update(recording_quality="usable", notes_match="consistent", timing_match="consistent", score=7)
    raw["choices"][0]["message"]["content"] = json.dumps(data)
    fake_client[0].chat.return_value = raw
    report = evaluate(path, acoustic_metrics=metrics_for(path))
    assert report["status"] == "unavailable" and report["assessment"] is None
    assert "onset schedule" in report["error"]
    assert fake_client[0].chat.call_count == 1


def test_missing_dsp_does_not_create_a_timing_target(tmp_path, fake_client):
    raw = response()
    data = json.loads(raw["choices"][0]["message"]["content"])
    data.update(recording_quality="usable", notes_match="consistent", timing_match="consistent", score=7)
    raw["choices"][0]["message"]["content"] = json.dumps(data)
    fake_client[0].chat.return_value = raw
    report = evaluate(wav_file(tmp_path), acoustic_metrics={"status": "unavailable", "error": "Fixture"},
                      timing_target_available=False)
    assert report["status"] == "unavailable" and "onset schedule" in report["error"]
