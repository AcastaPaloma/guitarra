import io
import json
import math
import struct
import threading
import time
import wave
from unittest.mock import MagicMock

import pytest
from rehearsal import CaptureComplete, CaptureStart, RehearsalError, RehearsalManager
from tap_plans import Note, Proposal, TapPlan, compile_revision


def plan():
    return TapPlan(notes=[Note(string=1, fret=1), Note(string=1, fret=2)])


def registry():
    return {"keys": {(1, 1), (1, 2)}, "fingerprint": "fixture-not-physical", "grid": None}


def execute(take, registered, stop, emit):
    for index, _ in enumerate(take.notes):
        if stop.is_set():
            return False
        emit({"event": "note_start", "index": index})
        emit({"event": "note_end", "index": index, "source": "fake_test"})
    return True


def evaluate(*args, **kwargs):
    return {"status": "assessed", "assessment": {"recording_quality": "usable",
            "notes_match": "inconsistent", "timing_match": "not_assessed",
            "summary": "Offline fixture only.", "observations": [], "limitations": ["Mock model, synthetic audio."]}}


def revise(take, keys, assessment, telemetry, *, history=None, allowed_profiles=("rest_hub",),
           acoustic_metrics=None, enabled_arm_keys=None):
    notes = [{**n.model_dump(), "source_index": i} for i, n in enumerate(take.notes)]
    notes[0]["pause_ms"] += 50
    proposal = Proposal(decision="revise", rationale="Offline fixture proposal.", notes=notes,
                        path_profile=take.path_profile, inspection_notes=[])
    return compile_revision(proposal, take, keys, allowed_profiles)


def wav_bytes(silence=False):
    stream = io.BytesIO()
    samples = [0 if silence else int(1000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(4800)]
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<4800h", *samples))
    return stream.getvalue()


def capture_start(record):
    return CaptureStart(capture_id=record["capture_id"], sample_rate=16000,
                        dispatch_frame=160, capture_ready=True)


def capture_end(record):
    return CaptureComplete(capture_id=record["capture_id"], sample_rate=16000, dispatch_frame=160,
                           completion_frame=3200, frames=4800, elapsed_s=0.3, interrupted=False)


def wait_for(manager, record, phases):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = manager.status(record["attempt_id"])
        if result["phase"] in phases:
            return result
        time.sleep(0.005)
    raise AssertionError(f"No expected phase {phases}; got {result['phase']}")


@pytest.fixture
def manager(tmp_path):
    instance = RehearsalManager(tmp_path, registry=registry, execute=MagicMock(side_effect=execute),
                               evaluate=MagicMock(side_effect=evaluate), revise=MagicMock(side_effect=revise))
    yield instance
    for record in list(instance.attempts.values()):
        instance.stop(record.record["attempt_id"])


def complete(manager, take=None, parent=None):
    record = manager.create(take or plan(), parent_attempt_id=parent)
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    return wait_for(manager, record, {"review_ready", "inspect", "unavailable", "keep"})


def test_full_cycle_requires_a_separate_approved_play(manager):
    result = complete(manager)
    assert result["phase"] == "review_ready"
    assert manager.execute.call_count == manager.evaluate.call_count == manager.revise.call_count == 1
    assert result["completed_notes"] == 2 and result["auto_replay"] is False
    assert not manager.busy
    assert manager.evaluate.call_args.kwargs["source"] == "browser_microphone"
    assert manager.evaluate.call_args.kwargs["allow_upload"] is True
    assert manager.evaluate.call_args.kwargs["acoustic_metrics"] == result["acoustic_metrics"]
    assert manager.revise.call_args.kwargs["acoustic_metrics"] == result["acoustic_metrics"]
    assert manager.evaluate.call_args.kwargs["should_stop"]() is False
    assert 0 < manager.evaluate.call_args.kwargs["budget_s"] <= 75
    assert result["acoustic_metrics"]["source_sha256"] == result["capture"]["clip"]["source_sha256"]
    report = manager.root / result["attempt_id"] / "attempt.json"
    saved = json.loads(report.read_text())
    assert saved["plan"]["notes"][0]["pause_ms"] == 250
    assert saved["revision"]["plan"]["notes"][0]["pause_ms"] == 300
    assert "base64" not in report.read_text()
    assert report.stat().st_mode & 0o777 == 0o600
    proposed = TapPlan.model_validate(result["revision"]["plan"])
    reserved = manager.create(proposed, parent_attempt_id=result["attempt_id"])
    assert reserved["phase"] == "ready" and manager.execute.call_count == 1
    assert reserved["original_plan"] == result["original_plan"]


def test_duplicate_start_never_replays(manager):
    record = manager.create(plan())
    start = capture_start(record)
    manager.start(record["attempt_id"], start)
    wait_for(manager, record, {"awaiting_audio"})
    manager.start(record["attempt_id"], start)
    assert manager.execute.call_count == 1


def test_audio_not_accepted_before_completed_play_or_from_another_capture(manager):
    record = manager.create(plan())
    with pytest.raises(RehearsalError, match="completed"):
        manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    wrong = capture_start(record).model_copy(update={"capture_id": "0" * 36})
    with pytest.raises(RehearsalError, match="belong"):
        manager.start(record["attempt_id"], wrong)
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    wrong = capture_end(record).model_copy(update={"capture_id": "0" * 36})
    with pytest.raises(RehearsalError, match="identity"):
        manager.accept_audio(record["attempt_id"], wrong, wav_bytes())
    assert not manager.evaluate.called


def test_one_clip_only_and_no_model_retry(manager):
    result = complete(manager)
    with pytest.raises(RehearsalError):
        manager.accept_audio(result["attempt_id"], capture_end(result), wav_bytes())
    assert manager.evaluate.call_count == 1


@pytest.mark.parametrize("invalid", ["truncated", "frames", "sample_rate", "coverage", "zero_samples"])
def test_bad_capture_cannot_trigger_compensation(manager, invalid):
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    meta, wav = capture_end(record), wav_bytes()
    if invalid == "truncated": wav = wav[:-500]
    elif invalid == "frames": meta = meta.model_copy(update={"frames": 3000})
    elif invalid == "sample_rate": meta = meta.model_copy(update={"sample_rate": 48000})
    elif invalid == "coverage": manager.attempts[record["attempt_id"]].record["playback_elapsed_s"] = 20
    elif invalid == "zero_samples": wav = wav_bytes(silence=True)
    try:
        manager.accept_audio(record["attempt_id"], meta, wav)
    except RehearsalError:
        pass
    assert not manager.evaluate.called and not manager.revise.called
    assert manager.execute.call_count == 1
    assert manager.status(record["attempt_id"])["assessment"] is None


def test_provider_timeout_is_unavailable_not_bad_performance(manager):
    manager.evaluate.side_effect = lambda *a, **kw: {"status": "unavailable", "assessment": None,
                                                  "error": "fixture timeout"}
    result = complete(manager)
    assert result["phase"] == "unavailable" and result["assessment"] is None
    assert not manager.revise.called and manager.execute.call_count == 1


def test_uncertain_audio_still_reaches_the_planner(manager):
    # Policy 2026-09-19: only "unusable" blocks; uncertain hearing proceeds
    # with its caveats so the operator still gets a graded review.
    report = evaluate()
    report["assessment"]["recording_quality"] = "uncertain"
    manager.evaluate.side_effect = lambda *a, **kw: report
    result = complete(manager)
    assert result["phase"] == "review_ready" and manager.revise.called


def test_unusable_audio_skips_revision(manager):
    report = evaluate()
    report["assessment"]["recording_quality"] = "unusable"
    manager.evaluate.side_effect = lambda *a, **kw: report
    result = complete(manager)
    assert result["phase"] == "inspect" and not manager.revise.called


def test_fault_never_uploads_or_homes(manager):
    manager.execute.side_effect = TimeoutError("fixture encoder timeout")
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    result = wait_for(manager, record, {"fault"})
    assert result["playback_outcome"] == "fault"
    with pytest.raises(RehearsalError):
        manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    assert not manager.evaluate.called


def test_stop_during_execution_prevents_review(manager):
    entered, resume = threading.Event(), threading.Event()
    def blocked(take, registry, stop, emit):
        entered.set()
        assert resume.wait(3)
        return not stop.is_set()
    manager.execute.side_effect = blocked
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    assert entered.wait(3)
    manager.stop(record["attempt_id"])
    resume.set()
    wait_for(manager, record, {"stopped"})
    assert not manager.evaluate.called


def test_late_model_result_discarded_after_stop(manager):
    entered, resume = threading.Event(), threading.Event()
    def blocked(*a, **kw):
        entered.set()
        assert resume.wait(3)
        return evaluate()
    manager.evaluate.side_effect = blocked
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    assert entered.wait(3)
    manager.stop(record["attempt_id"])
    resume.set()
    result = wait_for(manager, record, {"stopped"})
    assert result["revision"] is None and not manager.revise.called


def test_stale_calibration_cancels_before_any_motor_connection(manager):
    record = manager.create(plan())
    manager.registry = lambda: {**registry(), "fingerprint": "changed"}
    with pytest.raises(RehearsalError, match="changed"):
        manager.start(record["attempt_id"], capture_start(record))
    assert not manager.execute.called


def test_changed_or_expired_proposal_is_not_replayed(manager):
    result = complete(manager)
    take = TapPlan.model_validate(result["revision"]["plan"])
    with pytest.raises(RehearsalError, match="exactly"):
        manager.create(plan(), parent_attempt_id=result["attempt_id"])
    manager.attempts[result["attempt_id"]].proposal_deadline = 0
    with pytest.raises(RehearsalError, match="expired"):
        manager.create(take, parent_attempt_id=result["attempt_id"])
    assert manager.execute.call_count == 1


def test_attempt_chain_is_bounded_and_never_automatic(manager):
    first = complete(manager)
    second = complete(manager, TapPlan.model_validate(first["revision"]["plan"]), first["attempt_id"])
    third = complete(manager, TapPlan.model_validate(second["revision"]["plan"]), second["attempt_id"])
    assert third["phase"] == "inspect" and third["attempt_number"] == 3
    assert manager.execute.call_count == manager.evaluate.call_count == 3
    assert manager.revise.call_count == 2
    with pytest.raises(RehearsalError):
        manager.create(plan(), parent_attempt_id=third["attempt_id"])


def test_one_owner_calibration_and_browser_lease(manager):
    manager.calibration_active = lambda: True
    with pytest.raises(RehearsalError, match="calibration"):
        manager.create(plan())
    manager.calibration_active = lambda: False
    record = manager.create(plan())
    with pytest.raises(RehearsalError, match="Another"):
        manager.create(plan())
    manager.attempts[record["attempt_id"]].last_heartbeat -= 10
    result = wait_for(manager, record, {"stopped"})
    assert "heartbeat" in result["error"] and not manager.execute.called


def test_restart_never_resumes_previous_motion_or_recording(manager):
    record = complete(manager)
    fresh = RehearsalManager(manager.root, registry=registry, execute=execute)
    assert fresh.active() is None
    with pytest.raises(RehearsalError, match="previous-server"):
        fresh.start(record["attempt_id"], capture_start(record))


def test_stop_during_local_measurement_prevents_upload(manager, monkeypatch):
    import rehearsal
    record = manager.create(plan())
    def cancelled_measurement(*args, **kwargs):
        manager.stop(record["attempt_id"])
        return {"status": "unavailable", "error": "Fixture cancellation"}
    monkeypatch.setattr(rehearsal, "measure_take", cancelled_measurement)
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    result = wait_for(manager, record, {"stopped"})
    assert not manager.evaluate.called and not manager.revise.called
    assert result["assessment"] is None


def test_local_measurement_failure_is_forwarded_as_unavailable(manager, monkeypatch):
    import rehearsal
    def broken(*args, **kwargs):
        raise ValueError("Fixture DSP failure")
    monkeypatch.setattr(rehearsal, "measure_take", broken)
    result = complete(manager)
    metrics = manager.evaluate.call_args.kwargs["acoustic_metrics"]
    assert metrics["status"] == "unavailable"
    assert "per_note" not in metrics and "summary" not in metrics
    assert result["acoustic_metrics"] == metrics
