"""row_hub path profile: qualification gating, bounded path revisions, registry."""
import hashlib
import json

import fret
import pytest
import webapp
from pydantic import ValidationError
from tap_plans import Note, Proposal, TapPlan, compile_revision, validate_take

KEYS = {(1, 1), (1, 2)}
BOTH = ("rest_hub", "row_hub")


def make_plan(profile="rest_hub"):
    return TapPlan(notes=[Note(string=1, fret=1), Note(string=1, fret=2)],
                   path_profile=profile)


def path_proposal(profile):
    plan = make_plan()
    return Proposal(decision="revise", rationale="Shorter travels within the row.",
                    notes=[{**n.model_dump(), "source_index": i} for i, n in enumerate(plan.notes)],
                    path_profile=profile, inspection_notes=[])


def test_validate_take_gates_on_qualified_profiles():
    with pytest.raises(ValueError, match="not qualified"):
        validate_take(make_plan("row_hub"), KEYS)
    validate_take(make_plan("row_hub"), KEYS, BOTH)
    validate_take(make_plan(), KEYS)  # rest_hub always allowed


def test_unknown_profile_rejected_by_schema():
    with pytest.raises(ValidationError):
        make_plan("hover_direct")
    with pytest.raises(ValidationError):
        path_proposal("direct_A_to_B")


def test_path_revision_requires_qualification_and_is_one_change():
    with pytest.raises(ValueError, match="not qualified"):
        compile_revision(path_proposal("row_hub"), make_plan(), KEYS)
    result = compile_revision(path_proposal("row_hub"), make_plan(), KEYS, BOTH)
    assert result["changes"] == [{"kind": "path", "before": "rest_hub", "after": "row_hub",
                                  "warning": "Staging family change; contact poses are unchanged"}]
    assert result["plan"]["path_profile"] == "row_hub"
    assert result["operator_approval_required"] is True and result["motion_authority"] is False


def test_path_change_cannot_combine_with_other_categories():
    proposal = path_proposal("row_hub")
    data = proposal.model_dump()
    data["notes"][0]["pause_ms"] += 50
    with pytest.raises(ValueError, match="one category"):
        compile_revision(Proposal.model_validate(data), make_plan(), KEYS, BOTH)


def _write_rig(tmp_path, monkeypatch, *, qualified=True, with_hub=True):
    positions = {str(s): 1000 for s in fret.MOTOR_IDS}
    entries = [{"name": "rest", "time": "t", "positions": positions},
               {"name": "pose-r1-c1", "time": "t", "positions": positions}]
    if with_hub:
        entries.append({"name": "rest-r1", "time": "t", "positions": positions})
    raw = json.dumps(entries).encode()
    (tmp_path / "keyframes.json").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest() if qualified else "0" * 64
    (tmp_path / "calibration_arm2.json").write_text(json.dumps(
        {"qualified_profiles": {"row_hub": {"keyframes_sha256": sha, "qualified_at": "t"}}}))
    monkeypatch.setattr(fret, "KEYFRAMES_PATH", tmp_path / "keyframes.json")
    monkeypatch.setattr(webapp, "HERE", tmp_path)


def test_registry_offers_row_hub_only_when_operator_qualified(tmp_path, monkeypatch):
    _write_rig(tmp_path, monkeypatch)
    assert webapp.read_registry()["path_profiles"] == ("rest_hub", "row_hub")


def test_registry_drops_row_hub_when_keyframes_changed(tmp_path, monkeypatch):
    _write_rig(tmp_path, monkeypatch, qualified=False)
    assert webapp.read_registry()["path_profiles"] == ("rest_hub",)


def test_registry_drops_row_hub_without_hubs_for_every_row(tmp_path, monkeypatch):
    _write_rig(tmp_path, monkeypatch, with_hub=False)
    assert webapp.read_registry()["path_profiles"] == ("rest_hub",)


def test_registry_fingerprint_tracks_qualification(tmp_path, monkeypatch):
    _write_rig(tmp_path, monkeypatch)
    qualified = webapp.read_registry()["fingerprint"]
    _write_rig(tmp_path, monkeypatch, qualified=False)
    assert webapp.read_registry()["fingerprint"] != qualified
