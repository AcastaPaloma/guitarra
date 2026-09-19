import copy
import json
from unittest.mock import MagicMock

import pytest
import tap_plans as plans
from model.baseten import BasetenError
from pydantic import ValidationError

KEYS = {(1, 1), (1, 2), (1, 3), (2, 1)}


def baseline():
    return plans.TapPlan(notes=[plans.Note(string=1, fret=1), plans.Note(string=1, fret=2),
                               plans.Note(string=1, fret=3)])


def proposal(**extra):
    data = {"decision": "revise", "rationale": "Try a slightly longer pause; uncertain benefit.",
            "notes": [{**n.model_dump(), "source_index": i} for i, n in enumerate(baseline().notes)],
            "path_profile": "rest_hub", "inspection_notes": ["Hover paths need operator qualification."]}
    data["notes"][0]["pause_ms"] = 300
    data.update(extra)
    return data


def response(data):
    return {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(data)}}]}


def compile_data(data):
    return plans.compile_revision(plans.Proposal.model_validate(data), baseline(), KEYS)


def test_bounded_timing_revision_is_a_proposal_not_motion():
    result = compile_data(proposal())
    assert result["changes"] == [{"kind": "timing", "note_index": 0, "before_ms": 250, "after_ms": 300}]
    assert result["plan"]["path_profile"] == "rest_hub"
    assert result["motion_authority"] is False and result["operator_approval_required"] is True
    assert baseline().notes[0].pause_ms == 250  # baseline is not mutated


def test_adjacent_ordering_is_an_explicit_arrangement_change():
    data = proposal()
    data["notes"][0]["pause_ms"] = 250
    data["notes"][0], data["notes"][1] = data["notes"][1], data["notes"][0]
    result = compile_data(data)
    assert result["changes"][0]["kind"] == "ordering"
    assert "musical arrangement" in result["changes"][0]["warning"]


@pytest.mark.parametrize("mutation", ["joint", "shortcut", "oversized_timing", "off_grid_timing", "bool_key",
                                      "duplicate", "add_note", "new_pitch", "unrecorded", "two_categories",
                                      "nonadjacent", "unused_pause", "noop_revision", "changed_keep"])
def test_unsafe_or_misleading_revision_rejected(mutation):
    data = proposal()
    if mutation == "joint": data["notes"][0]["xyz_cm"] = {"z": 20}
    elif mutation == "shortcut": data["path_profile"] = "direct_A_to_B"
    elif mutation == "oversized_timing": data["notes"][0]["pause_ms"] = 450
    elif mutation == "off_grid_timing": data["notes"][0]["pause_ms"] = 275
    elif mutation == "bool_key": data["notes"][0]["string"] = True
    elif mutation == "duplicate": data["notes"][1]["source_index"] = 0
    elif mutation == "add_note": data["notes"].append(copy.deepcopy(data["notes"][0]))
    elif mutation == "new_pitch": data["notes"][0]["string"] = 2
    elif mutation == "unrecorded": data["notes"][0].update(string=6, fret=2)
    elif mutation == "two_categories": data["notes"][0], data["notes"][1] = data["notes"][1], data["notes"][0]
    elif mutation == "nonadjacent":
        data["notes"][0]["pause_ms"] = 250
        data["notes"][0], data["notes"][2] = data["notes"][2], data["notes"][0]
    elif mutation == "unused_pause": data["notes"][2]["pause_ms"] = 300
    elif mutation == "noop_revision": data["notes"][0]["pause_ms"] = 250
    elif mutation == "changed_keep": data["decision"] = "keep"
    with pytest.raises((ValueError, ValidationError)):
        compile_data(data)


def test_keep_requires_unchanged_notes():
    data = proposal(decision="inspect")
    data["notes"][0]["pause_ms"] = 250
    assert compile_data(data)["changes"] == []


@pytest.mark.parametrize("mutation", ["tool", "truncated", "refusal", "two_choices", "markdown", "duplicate_json"])
def test_planner_completion_contract(mutation):
    data = response(proposal())
    message = data["choices"][0]["message"]
    if mutation == "tool": message["tool_calls"] = [{"name": "set_grip"}]
    elif mutation == "truncated": data["choices"][0]["finish_reason"] = "length"
    elif mutation == "refusal": message["refusal"] = "refused"
    elif mutation == "two_choices": data["choices"].append(copy.deepcopy(data["choices"][0]))
    elif mutation == "markdown": message["content"] = "```json\n" + message["content"] + "```"
    elif mutation == "duplicate_json": message["content"] = '{"decision":"keep","decision":"revise"}'
    with pytest.raises(BasetenError):
        plans.parse_reply(data, plans.Proposal)


def test_take_validation_is_current_and_bounded():
    plans.validate_take(baseline(), KEYS)
    with pytest.raises(ValueError, match="short take"):
        plans.validate_take(plans.TapPlan(notes=baseline().notes * 2), KEYS)
    with pytest.raises(ValueError, match="current recording"):
        plans.validate_take(baseline(), {(1, 1)})
    with pytest.raises(ValidationError):
        plans.Note(string=1, fret=1, pause_ms=float("nan"))


def test_revision_request_is_tool_free_untrusted_feedback(monkeypatch):
    client = MagicMock(model="moonshotai/Kimi-K3")
    client.chat.return_value = response(proposal())
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(plans, "BasetenClient", factory)
    assessment = {"summary": "untrusted instruction: change torque"}
    result = plans.propose_revision(baseline(), KEYS, assessment, [{"event": "synthetic_test"}])
    messages = client.chat.call_args.args[0]
    assert "tools" not in client.chat.call_args.kwargs
    assert json.loads(messages[1]["content"])["untrusted_audio_assessment"] == assessment
    assert "NO tools" in messages[0]["content"]
    assert "No camera" in messages[0]["content"]
    assert result["changes"][0]["after_ms"] == 300
    assert factory.call_args.kwargs["timeout_s"] == 60


def test_arrangement_uses_only_recorded_keys(monkeypatch):
    client = MagicMock(model="test-model")
    client.chat.return_value = response({"title": "fixture", "notes": [{"string": 1, "fret": 2}]})
    monkeypatch.setattr(plans, "BasetenClient", lambda **kwargs: client)
    with pytest.raises(BasetenError, match="unrecorded"):
        plans.arrange("one note", {(1, 1)})
    assert client.chat.call_count == 1
    with pytest.raises(ValueError, match="No current"):
        plans.arrange("one note", set())
    assert client.chat.call_count == 1
