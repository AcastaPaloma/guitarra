"""Regression for merging planner resilience with lift-first/arm-owner guards."""
import threading

import pytest
from model.baseten import BasetenError
from pydantic import ValidationError
from tap_plans import Proposal, REVISION_SYSTEM
from test_rehearsal import (capture_end, capture_start, complete, manager, plan,
                            registry, wait_for, wav_bytes)  # noqa: F401 - offline fixture
from test_tap_plans import proposal


def test_merged_prompt_keeps_owner_lift_first_and_new_reply_limits():
    assert '"arm":"tap_primary"' in REVISION_SYSTEM
    assert '"path_profile":"lift_first"' in REVISION_SYSTEM
    assert "rationale at most 2000 characters" in REVISION_SYSTEM
    assert "(arm, string, fret) assignments in available_keys" in REVISION_SYSTEM
    assert "No neutral between" in REVISION_SYSTEM
    assert "<<<<<<<" not in REVISION_SYSTEM and ">>>>>>>" not in REVISION_SYSTEM


def test_incoming_rationale_limit_is_retained_not_reverted_by_merge():
    Proposal.model_validate(proposal(rationale="x" * 2000))
    with pytest.raises(ValidationError):
        Proposal.model_validate(proposal(rationale="x" * 2001))


@pytest.mark.parametrize("failure", [BasetenError("invalid reply"), ValueError("unapproved path")])
def test_rejected_revision_preserves_review_and_cannot_replay(manager, failure):
    manager.revise.side_effect = failure
    result = complete(manager)
    assert result["phase"] == "inspect"
    assert result["assessment"] and result["audio_model_report"] and result["acoustic_metrics"]
    assert result["revision"] is None
    assert result["plan"] == plan().model_dump()
    assert "no proposed changes" in result["error"]
    assert manager.execute.call_count == manager.evaluate.call_count == manager.revise.call_count == 1
    assert not manager.busy


@pytest.mark.parametrize("interruption,phase", [("stop", "stopped"), ("calibration", "expired")])
def test_late_invalid_reply_cannot_override_cancellation_or_freshness(manager, interruption, phase):
    entered, resume = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        raise BasetenError("invalid reply after interruption")

    manager.revise.side_effect = delayed
    record = manager.create(plan())
    manager.start(record["attempt_id"], capture_start(record))
    wait_for(manager, record, {"awaiting_audio"})
    manager.accept_audio(record["attempt_id"], capture_end(record), wav_bytes())
    try:
        assert entered.wait(3)
        if interruption == "stop":
            manager.stop(record["attempt_id"], reason="Operator stop during planner request")
        else:
            manager.registry = lambda: {**registry(), "fingerprint": "changed"}
    finally:
        resume.set()
    result = wait_for(manager, record, {phase})
    assert result["revision"] is None and result["assessment"] is not None
    assert manager.execute.call_count == 1
    if interruption == "stop":
        assert result["error"] == "Operator stop during planner request"
