"""Path invariants over the REAL executor with a synthetic bus; no hardware/API."""
import hashlib
import json
import threading
from unittest.mock import Mock

import fret
import pytest
import webapp
from path_fixtures import Bus, fake_arm, fixture_data, path_registry
from rehearsal import RehearsalError, RehearsalManager
from tap_paths import PROFILE, ClearancePaths, PathUnavailable, contact_name, hover_name
from tap_plans import Note, TapPlan


def take(keys=((1, 1), (1, 2))):
    return TapPlan(notes=[Note(string=s, fret=f) for s, f in keys], path_profile=PROFILE)


def test_contact_only_map_is_not_a_clearance_map():
    snapshot, raw, _ = fixture_data()
    with pytest.raises(PathUnavailable, match="No neutral fallback"):
        ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(), {})


@pytest.mark.parametrize("mutation", ["stale_map", "stale_calibration", "stale_motion", "missing_hover",
                                     "yaw_during_lift", "roll_during_lift", "overlapping_arrival", "rest_alias",
                                     "contact_edge", "bad_id", "bool_position", "missing_exit"])
def test_invalid_review_cannot_enable_motion(mutation):
    snapshot, raw, cal = fixture_data()
    review = cal["qualified_profiles"][PROFILE]
    if mutation == "stale_map": review["keyframes_sha256"] = "0" * 64
    elif mutation == "stale_calibration": cal["new_reference"] = True
    elif mutation == "stale_motion": review["motion_contract"] = "old-motion"
    elif mutation == "missing_hover": del snapshot["hovers"][(1, 1)]
    elif mutation == "yaw_during_lift": snapshot["hovers"][(1, 1)][7] += 1
    elif mutation == "roll_during_lift": snapshot["hovers"][(1, 1)][11] += 1
    elif mutation == "overlapping_arrival": snapshot["hovers"][(1, 1)][8] += 90  # 110 < press 90 + hover 30
    elif mutation == "rest_alias":
        snapshot["rest"] = dict(snapshot["hovers"][(1, 1)])
    elif mutation == "contact_edge": review["transit_edges"][0][1] = contact_name((1, 1))
    elif mutation == "bad_id": snapshot["hovers"][(1, 1)][12] = 1000
    elif mutation == "bool_position": snapshot["hovers"][(1, 1)][9] = True
    elif mutation == "missing_exit": review["transit_edges"] = [e for e in review["transit_edges"] if e[1] != "rest"]
    with pytest.raises(PathUnavailable):
        ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(), cal)


def test_complete_phrase_compiles_no_rest_between_notes_and_repeats_reattack():
    paths = path_registry()["paths"]
    trace = paths.compile([(1, 1), (1, 1), (1, 2)])
    assert trace["neutral_visits_between_notes"] == 0
    assert trace["notes"][1]["stages"] == [
        {"stage": "tap", "pose": "key-r1-c1"}, {"stage": "lift_clear", "pose": "hover-r1-c1"}]
    assert trace["notes"][2]["stages"] == [
        {"stage": "travel", "pose": "hover-r2-c1"}, {"stage": "tap", "pose": "key-r2-c1"},
        {"stage": "lift_clear", "pose": "hover-r2-c1"}]
    assert not any(s["pose"] == "rest" for n in trace["notes"] for s in n["stages"])
    assert trace["exit_route"] == ["rest"]
    assert trace["physical_clearance_verified_by_software"] is False


def test_shortest_reviewed_hover_route_uses_counts_not_llm_coordinates():
    paths = path_registry(keys=((1, 1), (1, 2), (2, 1)))["paths"]
    a, b, c = map(hover_name, [(1, 1), (1, 2), (2, 1)])
    assert paths.route(a, b) == (b,)  # direct beats an unnecessary extra hover
    indirect = ClearancePaths(paths.poses, paths.keys, paths.edges - {(a, b)})
    assert indirect.route(a, b) == (c, b)  # reviewed intermediate, never rest


def test_disconnected_hover_graph_never_falls_back_to_rest_before_next_key():
    a, b = map(hover_name, [(1, 1), (1, 2)])
    reg = path_registry(edges=[["rest", a], [a, "rest"], ["rest", b], [b, "rest"]])
    reg["paths"].compile([(1, 1)])  # entry/exit are individually reviewed
    with pytest.raises(PathUnavailable, match="will not detour through neutral"):
        reg["paths"].compile([(1, 1), (1, 2)])


@pytest.mark.parametrize("next_key", [(1, 2), (2, 1)])  # changed fret AND neighboring string
def test_actual_taps_lift_current_key_then_travel_then_lower_no_neutral(monkeypatch, next_key):
    arm, bus, moves, clock = fake_arm(monkeypatch, registry=path_registry(keys=((1, 1), next_key)))
    first = arm.tap_key(1, 1)
    second = arm.tap_key(*next_key)
    names = ["hover-r1-c1", "key-r1-c1", "hover-r1-c1",
             hover_name(next_key), contact_name(next_key), hover_name(next_key)]
    assert moves == [arm.paths.pose(n) for n in names]
    assert all(p != arm.rest_pose for p in moves)
    assert moves[1][7] == moves[2][7]  # yaw not retargeted until AFTER own-hover lift
    assert first["stages"][-1]["pose"] == "hover-r1-c1"
    assert second["stages"][0]["pose"] == hover_name(next_key)
    assert clock.now >= 4 * fret.CLEARANCE_DWELL_S
    assert 12 not in {j for j, _ in bus.goals + bus.torques}
    arm.rest()
    assert moves[-1] == arm.rest_pose  # explicit final exit only
    arm.close(torque_off=True)
    assert bus.torques[-5:] == [(j, False) for j in fret.MOTOR_IDS]


def test_clearance_wait_requires_consecutive_sampled_arrival(monkeypatch):
    arm, bus, _, clock = fake_arm(monkeypatch)
    target = arm.paths.pose("hover-r1-c1")
    original = bus.read_pos
    start = clock.now

    def noisy(sid):
        # The third sample leaves tolerance; the dwell must restart, rather
        # than accepting one early sample and beginning sideways travel.
        if sid == 8 and 0.05 < clock.now - start < 0.07:
            return target[8] + fret.SETTLE_TOL + 1
        return original(sid)

    bus.read_pos = noisy
    arm._move(target, fret.TRAVEL_SPEED, settle_s=fret.CLEARANCE_DWELL_S)
    assert clock.now - start >= 0.18


def test_repeated_key_reuses_hover_but_never_skips_the_tap_lift(monkeypatch):
    arm, _, moves, _ = fake_arm(monkeypatch)
    arm.tap_key(1, 1)
    moves.clear()
    arm.tap_key(1, 1)
    assert moves == [arm.paths.pose("key-r1-c1"), arm.paths.pose("hover-r1-c1")]


def test_lift_timeout_latches_and_never_travels_or_recovers(monkeypatch):
    arm, bus, moves, _ = fake_arm(monkeypatch)
    original = arm._move
    def block_lift(pose, *args, **kwargs):
        if arm.holding is not None:
            bus.block = True
        return original(pose, *args, **kwargs)
    arm._move = block_lift
    with pytest.raises(TimeoutError):
        arm.tap_key(1, 1)
    before = list(bus.goals)
    with pytest.raises(PathUnavailable, match="latched"):
        arm.tap_key(1, 2)
    with pytest.raises(PathUnavailable, match="latched"):
        arm.rest()
    assert bus.goals == before
    assert arm.paths.pose("hover-r2-c1") not in moves
    assert arm.location == "key-r1-c1"  # a failed lift was not recorded as complete


def test_held_key_is_lifted_before_any_retargeting(monkeypatch):
    arm, _, moves, _ = fake_arm(monkeypatch)
    arm.hold_fret(1, 1)
    moves.clear()
    arm.tap_key(1, 2)
    assert moves[:2] == [arm.paths.pose("hover-r1-c1"), arm.paths.pose("hover-r2-c1")]


def test_encoder_drift_at_hover_prevents_lateral_command(monkeypatch):
    arm, bus, _, _ = fake_arm(monkeypatch)
    arm.tap_key(1, 1)
    bus.q[8] += fret.SETTLE_TOL + 1
    before = list(bus.goals)
    with pytest.raises(PathUnavailable, match="expected hover"):
        arm.tap_key(1, 2)
    assert bus.goals == before


def test_unknown_start_is_rejected_before_goals_or_torque(monkeypatch):
    reg = path_registry()
    bus = Bus({j: 0 for j in fret.MOTOR_IDS})
    monkeypatch.setattr(fret, "FeetechBus", lambda *args: bus)
    with pytest.raises(PathUnavailable, match="expected rest"):
        fret.FretArm(grid=reg["grid"], paths=reg["paths"])
    assert bus.goals == [] and bus.torques == [] and bus.closed


def test_no_paths_or_legacy_profile_rejected_before_opening_port(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(fret, "FeetechBus", factory)
    with pytest.raises(PathUnavailable):
        fret.FretArm(grid=path_registry()["grid"])
    with pytest.raises(PathUnavailable, match="Hub-only"):
        fret.FretArm(path_profile="rest_hub")
    factory.assert_not_called()


def test_web_preflights_later_transition_before_any_connection(monkeypatch):
    a, b = map(hover_name, [(1, 1), (1, 2)])
    reg = path_registry(edges=[["rest", a], [a, "rest"], ["rest", b], [b, "rest"]])
    monkeypatch.setattr(webapp, "read_registry", lambda: reg)
    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(fret, "FretArm", factory)
    with pytest.raises(RehearsalError, match="No reviewed hover route"):
        webapp.execute_take(take(), reg, threading.Event(), lambda e: None)
    factory.assert_not_called()


def test_real_manager_rejects_before_reservation_capture_or_execute(tmp_path):
    reg = {**path_registry(), "paths": None, "path_blocker": "record the missing hover"}
    execute = Mock()
    manager = RehearsalManager(tmp_path, registry=lambda: reg, execute=execute, admit=webapp.admit_motion)
    with pytest.raises(RehearsalError, match="missing hover"):
        manager.create(take())
    assert manager.active() is None and not list(tmp_path.iterdir())
    execute.assert_not_called()


def test_failed_final_exit_is_not_reported_as_completed(monkeypatch):
    reg = path_registry()
    monkeypatch.setattr(webapp, "read_registry", lambda: reg)
    arm = Mock()
    arm.rest.side_effect = TimeoutError("exit failed")
    monkeypatch.setattr(fret, "FretArm", lambda **kwargs: arm)
    with pytest.raises(TimeoutError, match="exit failed"):
        webapp.execute_take(take(), reg, threading.Event(), lambda event: None)
    assert arm.rest.call_count == 1
    arm.close.assert_called_once_with(torque_off=True)


def test_registry_qualifies_only_the_versioned_current_lift_contract(tmp_path, monkeypatch):
    snapshot, raw, cal = fixture_data()
    keypath, calpath = tmp_path / "keys.json", tmp_path / "calibration_arm2.json"
    keypath.write_bytes(raw); calpath.write_text(json.dumps(cal))
    monkeypatch.setattr(fret, "KEYFRAMES_PATH", keypath)
    monkeypatch.setattr(webapp, "HERE", tmp_path)
    current = webapp.read_registry()
    assert current["path_profiles"] == (PROFILE,)
    assert webapp.admit_motion(take(), current)["neutral_visits_between_notes"] == 0
    keypath.write_bytes(raw + b"\n")
    stale = webapp.read_registry()
    assert stale["path_profiles"] == () and stale["paths"] is None
    assert "stale" in stale["path_blocker"]
    assert stale["keys"] == current["keys"]  # planning still possible, motion is not
    assert stale["fingerprint"] != current["fingerprint"]
