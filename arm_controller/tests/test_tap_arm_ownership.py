"""Two TAP-arm ownership contract, with the returning arm explicitly unavailable."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import fret
import pytest
import tap_plans
import webapp
from model.baseten import BasetenError
from path_fixtures import path_registry
from pydantic import ValidationError
from tap_arms import PRIMARY, SECONDARY, assign, capabilities
from tap_plans import Note, TapPlan
from test_tap_web import client  # noqa: F401 - offline HTTP fixture


def test_planned_secondary_rows_strings_and_unavailability_are_explicit():
    primary, secondary = capabilities({(1, 1), (6, 4), (1, 5)}, primary_ready=False)
    assert primary["rows"] == [1, 2, 3, 4, 5]
    assert secondary["rows"] == [7, 8, 9, 10, 11]
    assert secondary["planned_strings"] == [1, 2, 3, 4, 5, 6]
    assert "rightmost" in secondary["string_order"]
    assert secondary["recorded_keys"] == []
    assert secondary["available_for_planning"] is False and secondary["paths_reviewed"] is False


@pytest.mark.parametrize("arm,row", [(PRIMARY, 7), (PRIMARY, 11), (SECONDARY, 1),
                                    (SECONDARY, 5), (PRIMARY, 6), (SECONDARY, 6)])
def test_arm_cannot_claim_another_arm_or_unassigned_row(arm, row):
    with pytest.raises(ValueError, match="does not own"):
        assign([Note(arm=arm, string=1, fret=row)], {PRIMARY: {(1, row)}, SECONDARY: {(1, row)}})


def test_secondary_assignment_rejected_until_explicitly_enabled_and_recorded():
    note = Note(arm=SECONDARY, string=6, fret=11)
    with pytest.raises(ValueError, match="not available"):
        assign([note], {PRIMARY: {(6, 11)}})  # cannot silently borrow primary
    with pytest.raises(ValueError, match="no current recording"):
        assign([note], {SECONDARY: {(1, 7)}})
    assert assign([note], {SECONDARY: {(6, 11)}})[0]["arm"] == SECONDARY


def test_future_dual_arm_assignments_preserve_order_and_serialize_workspace():
    notes = [Note(arm=PRIMARY, string=1, fret=1), Note(arm=SECONDARY, string=6, fret=7),
             Note(arm=PRIMARY, string=1, fret=1)]
    schedule = assign(notes, {PRIMARY: {(1, 1)}, SECONDARY: {(6, 7)}})
    assert [event["arm"] for event in schedule] == [PRIMARY, SECONDARY, PRIMARY]
    assert [event["wait_for_event"] for event in schedule] == [None, 0, 1]
    assert not any(event["overlap_authorized"] for event in schedule)
    assert {event["shared_workspace"] for event in schedule} == {"guitar"}


def test_native_primary_tool_schemas_require_an_explicit_owner():
    assert not {"hold_fret", "fret_rest", "rest", "ready"} & {t["name"] for t in fret.TOOLS}
    for tool in fret.TOOLS:
        schema = tool["parameters"]
        assert "arm" in schema["required"]
        assert schema["properties"]["arm"]["enum"] == [PRIMARY]
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("args", [
    {"string": 1, "fret": 1},  # missing owner
    {"arm": SECONDARY, "string": 1, "fret": 7},
    {"arm": PRIMARY, "string": 1, "fret": 7},  # do not borrow the other arm's rows
    {"arm": PRIMARY, "string": 1, "fret": 1, "joint_targets": [1, 2, 3]},
])
def test_native_dispatch_rejects_missing_wrong_owner_and_raw_targets(args):
    arm = SimpleNamespace(arm_id=PRIMARY, tap_key=Mock())
    with pytest.raises(ValueError):
        fret.dispatch(arm, "tap_key", args)
    arm.tap_key.assert_not_called()


def test_live_take_cannot_dispatch_secondary_or_raw_motor_fields():
    plan = TapPlan(notes=[Note(arm=SECONDARY, string=1, fret=7)], path_profile="lift_first")
    with pytest.raises(ValueError, match="not available"):
        webapp.admit_motion(plan, path_registry())
    with pytest.raises(ValidationError):
        Note(arm=SECONDARY, string=1, fret=7, joint_angles=[0] * 5)
    with pytest.raises(ValidationError):
        Note(arm="either", string=1, fret=1)


def test_kimi_arrangement_gets_motion_costs_and_enabled_arm_contract(monkeypatch):
    paths = path_registry()["paths"]
    client = Mock(model="moonshotai/Kimi-K3")
    client.chat.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"title": "fixture", "notes": [
            {"arm": PRIMARY, "string": 1, "fret": 1}]})}}]}
    factory = Mock(return_value=client)
    monkeypatch.setattr(tap_plans, "BasetenClient", factory)
    result = tap_plans.arrange("one note", paths.keys, motion_context=paths.model_context())
    prompt = client.chat.call_args.args[0][0]["content"]
    assert "lift FIRST" in prompt and "hover_transition_costs" in prompt
    assert "tap_secondary" in prompt and "7–11" in prompt and "NOT connected" in prompt
    assert "joint angles" in prompt
    assert "tools" not in client.chat.call_args.kwargs
    assert factory.call_args.kwargs["effort"] == "high"
    assert result["path_profile"] == "lift_first" and result["notes"][0]["arm"] == PRIMARY
    client.chat.return_value["choices"][0]["message"]["content"] = json.dumps({
        "title": "invalid", "notes": [{"arm": SECONDARY, "string": 1, "fret": 7}]})
    with pytest.raises(BasetenError, match="unavailable arm"):
        tap_plans.arrange("one note", paths.keys)


def test_trajectory_preview_exposes_local_stages_without_capture_or_inference(client, monkeypatch):
    monkeypatch.setattr(webapp, "read_registry", path_registry)
    plan = TapPlan(notes=[Note(string=1, fret=1), Note(string=1, fret=2)], path_profile="lift_first")
    result = client.post("/api/trajectory", json={"plan": plan.model_dump()})
    assert result.status_code == 200 and result.json()["executable"] is True
    trace = result.json()["trajectory"]
    assert trace["neutral_visits_between_notes"] == 0
    assert all(a["arm"] == PRIMARY for a in trace["assignments"])
    assert not webapp.manager.execute.called and not webapp.manager.evaluate.called
    plan.path_profile = "rest_hub"
    result = client.post("/api/trajectory", json={"plan": plan.model_dump()})
    assert result.status_code == 200 and result.json()["executable"] is False
    assert "Hub-only" in result.json()["blockers"][0]
