"""Offline persistent sessions/tunings/audio; these fixtures are NOT real performances."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rehearsal import PartialCapture, RehearsalError, RehearsalManager
from tap_plans import TapPlan
from test_rehearsal import (
    capture_end,
    capture_start,
    complete,
    evaluate,
    execute,
    plan,
    registry,
    revise,
    wait_for,
    wav_bytes,
)


@pytest.fixture
def manager(tmp_path):
    instance = RehearsalManager(tmp_path, registry=registry, execute=MagicMock(side_effect=execute),
                               evaluate=MagicMock(side_effect=evaluate), revise=MagicMock(side_effect=revise))
    yield instance
    for attempt in instance.attempts.values():
        instance.stop(attempt.record["attempt_id"])


def performed_from_saved(manager, previous):
    record = manager.create(TapPlan.model_validate(previous["plan"]),
                            source_attempt_id=previous["attempt_id"], session_id=previous["session_id"])
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    return wait_for(manager, record, {"review_ready"})


def test_saved_sessions_and_audio_survive_restart_without_resuming(manager):
    first = complete(manager)
    second = complete(manager, TapPlan.model_validate(first["revision"]["plan"]), first["attempt_id"])
    fresh = RehearsalManager(manager.root, registry=registry, execute=MagicMock())
    sessions = fresh.sessions()
    assert sessions[0]["take_count"] == 2
    history = fresh.history(first["session_id"])
    assert [row["take_number"] for row in history["takes"]] == [1, 2]
    assert len({r["tuning_id"] for r in history["takes"]}) == 2
    assert all(row["audio_available"] and not row["audio_incomplete"] for row in history["takes"])
    assert fresh.saved_audio(first["attempt_id"]).read_bytes() == wav_bytes()
    assert fresh.active() is None and not fresh.execute.called
    with pytest.raises(RehearsalError, match="previous-server"):
        fresh.start(second["attempt_id"], capture_start(second))
    # Reusing an old tuning is a NEW explicit reservation and NEW capture, not resume.
    reserved = fresh.create(TapPlan.model_validate(second["plan"]), source_attempt_id=second["attempt_id"])
    assert reserved["phase"] == "ready" and reserved["take_number"] == 3
    assert reserved["capture_id"] != second["capture_id"] and not fresh.execute.called
    fresh.stop(reserved["attempt_id"])


def test_operator_can_continue_same_session_without_replanning_or_auto_play(manager):
    result = complete(manager)
    for _ in range(4):
        result = performed_from_saved(manager, result)
    history = manager.history(result["session_id"])
    assert len(history["takes"]) == 5
    assert result["take_number"] == 5 and result["attempt_number"] == 1
    assert len({r["tuning_id"] for r in history["takes"]}) == 1  # same cached tuning, five actual takes
    assert manager.execute.call_count == 5
    previous = manager.revise.call_args.kwargs["history"]
    assert len(previous) == 3 and [r["take_number"] for r in previous] == [2, 3, 4]
    assert "wav" not in json.dumps(previous) and "base64" not in json.dumps(previous)
    assert previous[-1]["local_acoustic_summary"]["schema_version"] == "guitarra.local-acoustics.v2"
    assert previous[-1]["local_acoustic_summary"]["alignment"]["calibrated"] is False
    assert "per_note" not in previous[-1]["local_acoustic_summary"]  # bounded summary, not waveform/full trace


def test_favorite_is_persistent_human_preference_not_model_score(manager):
    first = complete(manager)
    history = manager.prefer(first["session_id"], first["attempt_id"])
    assert history["takes"][0]["preferred_by_operator"] is True
    assert "score" not in history["takes"][0]
    memory = manager.archive.planner_context(first["session_id"], "future-attempt")
    assert memory[0]["preferred_by_operator"] is True
    assert memory[0]["assessment"]["notes_match"] == "inconsistent"  # human preference doesn't overwrite model data
    fresh = RehearsalManager(manager.root, registry=registry, execute=MagicMock())
    assert fresh.history(first["session_id"])["preferred_attempt_id"] == first["attempt_id"]
    assert not fresh.execute.called


def test_faster_command_trace_is_not_an_audio_quality_score(manager):
    first = complete(manager)
    second = performed_from_saved(manager, first)
    for record, duration in ((first, 2.0), (second, 1.5)):
        attempt = manager.attempts[record["attempt_id"]]
        attempt.record["playback_elapsed_s"] = duration
        manager._save(attempt)
    history = manager.history(first["session_id"])
    last = history["takes"][-1]
    assert last["command_delta_from_first_s"] == -0.5
    assert last["assessment"]["notes_match"] == "inconsistent"
    assert "not audio quality" in history["comparison_note"]
    # Same duration with a changed note order is NOT an apples-to-apples comparison.
    manager.attempts[second["attempt_id"]].record["plan"]["notes"].reverse()
    assert manager.history(first["session_id"])["takes"][-1]["command_delta_from_first_s"] is None


def test_stale_tuning_and_cross_session_cache_cannot_be_admitted(manager):
    first = complete(manager)
    other = complete(manager)
    with pytest.raises(RehearsalError, match="different session"):
        manager.create(plan(), source_attempt_id=first["attempt_id"], session_id=other["session_id"])
    manager.registry = lambda: {**registry(), "fingerprint": "changed"}
    with pytest.raises(RehearsalError, match="stale"):
        manager.create(plan(), source_attempt_id=first["attempt_id"])
    assert manager.execute.call_count == 2


def test_interrupted_audio_is_saved_locally_and_never_sent_to_model(manager):
    def interrupted(take, registered, stop, emit):
        stop.wait(2)
        return False
    manager.execute.side_effect = interrupted
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    manager.stop(record["attempt_id"])
    wait_for(manager, record, {"stopped"})
    metadata = PartialCapture(capture_id=record["capture_id"], sample_rate=16000, frames=4800, incomplete=True)
    result = manager.save_partial(record["attempt_id"], metadata, wav_bytes())
    assert result == {"saved_locally": True, "incomplete": True, "uploaded_to_baseten": False}
    assert not manager.evaluate.called and not manager.revise.called
    row = manager.history(record["session_id"])["takes"][0]
    assert row["audio_incomplete"] and row["audio_available"] and not row["can_load_tuning"]
    assert manager.saved_audio(record["attempt_id"]).name == "capture.partial.wav"
    with pytest.raises(RehearsalError):
        manager.create(plan(), source_attempt_id=record["attempt_id"])
    with pytest.raises(RehearsalError):
        manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    with pytest.raises(RehearsalError):
        manager.save_partial(record["attempt_id"], metadata, wav_bytes())


def test_wrong_partial_identity_or_truncation_never_enters_history(manager):
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.stop(record["attempt_id"])
    meta = PartialCapture(capture_id="0" * 36, sample_rate=16000, frames=4800, incomplete=True)
    with pytest.raises(RehearsalError, match="match"):
        manager.save_partial(record["attempt_id"], meta, wav_bytes())
    meta = meta.model_copy(update={"capture_id": record["capture_id"]})
    with pytest.raises(RehearsalError, match="invalid"):
        manager.save_partial(record["attempt_id"], meta, wav_bytes()[:-20])
    assert not manager.evaluate.called
    assert not manager.history(record["session_id"])["takes"][0]["audio_available"]


def test_audio_and_session_paths_reject_traversal_and_symlinks(manager, tmp_path):
    record = complete(manager)
    for value in ("../outside", "/etc/passwd", "x" * 36):
        with pytest.raises(RehearsalError):
            manager.saved_audio(value)
        with pytest.raises(RehearsalError):
            manager.history(value)
    wav = manager.saved_audio(record["attempt_id"])
    outside = tmp_path / "not-a-recording.txt"
    outside.write_text("must not be served")
    wav.unlink()
    wav.symlink_to(outside)
    with pytest.raises(RehearsalError):
        manager.saved_audio(record["attempt_id"])
    session = Path(manager.root) / "sessions" / (record["session_id"] + ".json")
    session.unlink()
    session.symlink_to(outside)
    with pytest.raises(RehearsalError):
        manager.history(record["session_id"])


def test_restoring_history_does_not_trust_an_interrupted_execution(manager):
    record = manager.create(plan())
    fresh = RehearsalManager(manager.root, registry=registry, execute=MagicMock())
    history = fresh.history(record["session_id"])
    assert history["takes"][0]["phase"] == "interrupted"
    assert not history["takes"][0]["can_load_tuning"]
    with pytest.raises(RehearsalError):
        fresh.create(plan(), source_attempt_id=record["attempt_id"])
    assert not fresh.execute.called
