"""Two-arm generalization: arm-1 lift-first paths, registry gating, strictly
sequential dual-arm execution, fret-6/arm derivation. Offline; no devices."""
import hashlib
import json
import threading
from unittest.mock import MagicMock, Mock

import arm1
import fret
import pytest
import tap_plans
import webapp
from model.baseten import BasetenError
from path_fixtures import Bus, Clock, fixture_data, path_registry
from rehearsal import RehearsalError
from tap_arms import (PRIMARY, SECONDARY, capabilities, enabled_key_map, owner_of_row)
from tap_paths import (PROFILE, SCHEMA, ClearancePaths, PathUnavailable,
                       calibration_digest, hover_name, motion_contract)
from tap_plans import Note, TapPlan, compile_revision, expected_phrase
from test_tap_web import client  # noqa: F401 - offline HTTP fixture

ARM1_IDS = tuple(arm1.BODY_IDS)
ARM1_KEYS = ((6, 7), (6, 8))


def arm1_fixture(keys=ARM1_KEYS, *, hovers=True, review=True):
    """Synthetic arm-1 map/review. NEVER physical qualification data."""
    def positions(pose):
        return {**{str(j): v for j, v in pose.items()}, "3": 1700}  # grip recorded, filtered

    rest = {j: 1000 for j in arm1.BODY_IDS}
    entries = [{"name": "rest", "positions": positions(rest)}]
    for s, f in keys:
        contact = {5: 1400 + 40 * s + 20 * f, 4: 1800 + 30 * f, 6: 2000, 1: 2300, 2: 1200}
        hover = {**contact, 4: contact[4] - 200}  # base yaw 5 / wrist roll 2 unchanged
        entries.append({"name": f"pose-r{f}_{s}", "positions": positions(contact)})
        if hovers:
            entries.append({"name": f"hover-r{f}-c{s}", "positions": positions(hover)})
    raw = json.dumps(entries).encode()
    calibration = {"fixture": "synthetic, NOT hardware review"}
    if review:
        nodes = ["rest"] + [hover_name(k) for k in keys]
        calibration["qualified_profiles"] = {PROFILE: {
            "schema_version": SCHEMA, "keyframes_sha256": hashlib.sha256(raw).hexdigest(),
            "calibration_sha256": calibration_digest(calibration),
            "motion_contract": motion_contract(ARM1_IDS), "qualified_at": "offline-test-only",
            "keys": [list(k) for k in keys],
            "transit_edges": [[a, b] for a in nodes for b in nodes if a != b],
        }}
    return entries, raw, calibration


def arm1_paths(keys=ARM1_KEYS):
    entries, raw, calibration = arm1_fixture(keys)
    snapshot = arm1.load_map(entries=entries)
    paths = ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(), calibration,
                                         body_ids=ARM1_IDS, fret_rows=arm1.FRET_ROWS)
    grid = (snapshot["cells"], snapshot["rest"], snapshot["warns"])
    return grid, paths, snapshot


def two_arm_registry():
    registry = path_registry()  # primary keys (1,1), (1,2)
    grid, paths, snapshot = arm1_paths()
    registry["secondary"] = {"keys": set(snapshot["cells"]), "grid": grid,
                             "hovers": snapshot["hovers"], "paths": paths,
                             "path_blocker": None, "warnings": [], "available": True}
    return registry


def write_rig(tmp_path, monkeypatch, *, arm1_variant="full"):
    """Write primary + arm-1 fixture files and point webapp/fret at them."""
    _, raw, cal = fixture_data()
    (tmp_path / "keyframes.json").write_bytes(raw)
    (tmp_path / "calibration_arm2.json").write_text(json.dumps(cal))
    monkeypatch.setattr(fret, "KEYFRAMES_PATH", tmp_path / "keyframes.json")
    monkeypatch.setattr(webapp, "HERE", tmp_path)
    if arm1_variant == "missing":
        return
    entries, sec_raw, sec_cal = arm1_fixture(hovers=arm1_variant != "no_hovers",
                                             review=arm1_variant == "full")
    (tmp_path / "keyframes_arm1.json").write_bytes(sec_raw)
    if arm1_variant == "full":
        (tmp_path / "calibration_arm1.json").write_text(json.dumps(sec_cal))


# ---- generalized paths for arm-1 body IDs --------------------------------

def test_arm1_load_map_parses_all_hover_name_variants():
    entries, _, _ = arm1_fixture(keys=())
    entries += [{"name": name, "positions": {str(j): 1500 for j in [5, 4, 6, 1, 2, 3]}}
                for name in ("hover-r7_1", "hover_r8_5", "hover-r9-c3")]
    m = arm1.load_map(entries=entries)
    assert set(m["hovers"]) == {(1, 7), (5, 8), (3, 9)}
    assert m["warns"] == []
    assert all(set(pose) == set(arm1.BODY_IDS) for pose in m["hovers"].values())


def test_arm1_hover_out_of_row_or_duplicate_is_rejected_not_warned():
    entries, _, _ = arm1_fixture(keys=())
    bad = entries + [{"name": "hover-r5-c1", "positions": {str(j): 1500 for j in arm1.BODY_IDS}}]
    with pytest.raises(ValueError, match="hover"):
        arm1.load_map(entries=bad)
    dupe = entries + [{"name": "hover-r7_1", "positions": {str(j): 1500 for j in arm1.BODY_IDS}},
                      {"name": "hover_r7_1", "positions": {str(j): 1400 for j in arm1.BODY_IDS}}]
    with pytest.raises(ValueError, match="duplicate"):
        arm1.load_map(entries=dupe)


def test_motion_contract_is_arm_specific_and_primary_hash_is_unchanged():
    assert motion_contract() == motion_contract((7, 8, 9, 10, 11))
    assert motion_contract() != motion_contract(ARM1_IDS)


def test_arm1_review_compiles_against_its_own_ids_only():
    _, paths, _ = arm1_paths()
    assert set(paths.pose("rest")) == set(ARM1_IDS)
    trace = paths.compile([(6, 7), (6, 8), (6, 7)])
    assert trace["neutral_visits_between_notes"] == 0
    assert trace["exit_route"] == ["rest"]
    # A review recorded under the PRIMARY arm's motion contract can never
    # enable this arm: the contract hash includes the body IDs.
    entries, raw, calibration = arm1_fixture()
    calibration["qualified_profiles"][PROFILE]["motion_contract"] = motion_contract()
    with pytest.raises(PathUnavailable, match="stale"):
        ClearancePaths.from_snapshot(arm1.load_map(entries=entries),
                                     hashlib.sha256(raw).hexdigest(), calibration,
                                     body_ids=ARM1_IDS, fret_rows=arm1.FRET_ROWS)


def test_fret_rows_are_per_arm_and_row_6_has_no_paths_anywhere():
    _, paths, _ = arm1_paths()
    for keys in ([(1, 1)], [(6, 6)]):  # primary row and unowned row 6
        with pytest.raises(PathUnavailable, match="rows"):
            paths.compile(keys)
    primary = path_registry()["paths"]
    for keys in ([(6, 7)], [(6, 6)]):
        with pytest.raises(PathUnavailable, match="rows"):
            primary.compile(keys)
    entries, raw, calibration = arm1_fixture()
    calibration["qualified_profiles"][PROFILE]["keys"] = [[1, 1]]
    with pytest.raises(PathUnavailable):
        ClearancePaths.from_snapshot(arm1.load_map(entries=entries),
                                     hashlib.sha256(raw).hexdigest(), calibration,
                                     body_ids=ARM1_IDS, fret_rows=arm1.FRET_ROWS)


def test_arm1_lift_first_executor_refuses_without_reviewed_paths(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(fret, "FeetechBus", factory)
    grid, _, _ = arm1_paths()
    with pytest.raises(PathUnavailable):
        arm1.Arm1LiftFirst(grid=grid, paths=None)
    factory.assert_not_called()


def test_arm1_load_lift_first_names_the_missing_hover_data(tmp_path):
    entries, raw, _ = arm1_fixture(hovers=False, review=False)
    keyframes = tmp_path / "keyframes_arm1.json"
    keyframes.write_bytes(raw)
    with pytest.raises(PathUnavailable, match="no hover poses recorded"):
        arm1.load_lift_first(keyframes, tmp_path / "calibration_arm1.json")
    entries, raw, _ = arm1_fixture(review=False)
    keyframes.write_bytes(raw)
    with pytest.raises(PathUnavailable, match="calibration_arm1.json is missing"):
        arm1.load_lift_first(keyframes, tmp_path / "calibration_arm1.json")


def test_arm1_executor_runs_real_lift_first_semantics_and_never_grip3(monkeypatch):
    grid, paths, _ = arm1_paths()
    clock, bus = Clock(), Bus(grid[1])
    monkeypatch.setattr(fret, "time", clock)
    monkeypatch.setattr(fret, "FeetechBus", lambda *args, **kwargs: bus)
    arm = arm1.Arm1LiftFirst(grid=grid, paths=paths)
    assert arm.arm_id == SECONDARY and arm.motor_ids == list(ARM1_IDS)
    bus.goals.clear()
    first = arm.tap_key(6, 7)
    second = arm.tap_key(6, 8)
    assert first["arm"] == SECONDARY
    assert first["stages"][-1]["pose"] == "hover-r7-c6"  # tap ends at ITS OWN hover
    assert second["stages"][0]["pose"] == "hover-r8-c6"  # hover-to-hover travel only
    commanded = {sid for sid, _ in bus.goals} | {sid for sid, _ in bus.torques}
    assert arm1.GRIP_ID not in commanded and commanded <= set(ARM1_IDS)
    arm.rest()
    arm.close(torque_off=True)
    assert bus.torques[-5:] == [(sid, False) for sid in ARM1_IDS]


# ---- registry gating of the secondary arm --------------------------------

def test_registry_without_arm1_hovers_reports_exact_reason(tmp_path, monkeypatch):
    write_rig(tmp_path, monkeypatch, arm1_variant="no_hovers")
    registry = webapp.read_registry()
    secondary = registry["secondary"]
    assert secondary["available"] is False and secondary["paths"] is None
    assert "no hover poses recorded" in secondary["path_blocker"]
    assert secondary["keys"] == set(ARM1_KEYS)  # planning data exists, motion does not
    caps = {c["arm"]: c for c in registry["capabilities"]}
    assert caps[SECONDARY]["available_for_planning"] is False
    assert "no hover poses recorded" in caps[SECONDARY]["unavailable_reason"]
    assert enabled_key_map(registry) == {PRIMARY: registry["keys"]}
    plan = TapPlan(notes=[Note(arm=SECONDARY, string=6, fret=7)], path_profile=PROFILE)
    with pytest.raises(RehearsalError, match="not available"):
        webapp.admit_motion(plan, registry)


def test_registry_missing_arm1_files_disable_secondary_only(tmp_path, monkeypatch):
    write_rig(tmp_path, monkeypatch, arm1_variant="missing")
    registry = webapp.read_registry()
    assert registry["paths"] is not None  # primary is unaffected
    assert registry["secondary"]["available"] is False
    assert "keyframes_arm1.json is missing" in registry["secondary"]["path_blocker"]
    write_rig(tmp_path, monkeypatch, arm1_variant="no_calibration")
    registry = webapp.read_registry()
    assert registry["secondary"]["available"] is False
    assert "paths not compiled" in registry["secondary"]["path_blocker"]
    assert "calibration_arm1.json" in registry["secondary"]["path_blocker"]


def test_registry_with_reviewed_arm1_is_available_and_fingerprinted(tmp_path, monkeypatch):
    write_rig(tmp_path, monkeypatch)
    registry = webapp.read_registry()
    secondary = registry["secondary"]
    assert secondary["available"] is True and secondary["path_blocker"] is None
    assert secondary["keys"] == set(ARM1_KEYS)
    caps = {c["arm"]: c for c in registry["capabilities"]}
    assert caps[SECONDARY]["available_for_planning"] is True
    assert caps[SECONDARY]["paths_reviewed"] is True
    assert caps[SECONDARY]["recorded_keys"] == [{"string": 6, "fret": 7}, {"string": 6, "fret": 8}]
    assert "unavailable_reason" not in caps[SECONDARY]
    assert enabled_key_map(registry)[SECONDARY] == set(ARM1_KEYS)
    # Any arm-1 byte change is covered by the fingerprint AND re-gates motion.
    keyframes = tmp_path / "keyframes_arm1.json"
    keyframes.write_bytes(keyframes.read_bytes() + b"\n")
    stale = webapp.read_registry()
    assert stale["fingerprint"] != registry["fingerprint"]
    assert stale["secondary"]["available"] is False
    assert "paths not compiled" in stale["secondary"]["path_blocker"]
    (tmp_path / "calibration_arm1.json").unlink()
    assert webapp.read_registry()["fingerprint"] not in {registry["fingerprint"], stale["fingerprint"]}


def test_mixed_plan_admission_compiles_each_arm_against_its_own_registry():
    registry = two_arm_registry()
    plan = TapPlan(notes=[Note(string=1, fret=1), Note(arm=SECONDARY, string=6, fret=7),
                          Note(string=1, fret=2)], path_profile=PROFILE)
    compiled = webapp.admit_motion(plan, registry)
    assert [a["arm"] for a in compiled["assignments"]] == [PRIMARY, SECONDARY, PRIMARY]
    assert [a["wait_for_event"] for a in compiled["assignments"]] == [None, 0, 1]
    assert compiled["neutral_visits_between_notes"] == 0
    assert compiled["notes"][1]["arm"] == SECONDARY
    assert compiled["notes"][1]["stages"][-1]["pose"] == "hover-r7-c6"
    assert set(compiled["exit_routes"]) == {PRIMARY, SECONDARY}
    assert not any(a["overlap_authorized"] for a in compiled["assignments"])
    # a primary-only plan keeps the unchanged single-arm trajectory shape
    single = webapp.admit_motion(TapPlan(notes=[Note(string=1, fret=1)], path_profile=PROFILE),
                                 registry)
    assert "exit_route" in single and "exit_routes" not in single


# ---- sequential two-arm execution ----------------------------------------

class SeqArm:
    def __init__(self, arm_id, log, *, halt=None, fail=None, **kwargs):
        self.arm_id, self.log, self.halt, self.fail = arm_id, log, halt, fail
        self.kwargs = kwargs

    def tap_key(self, string, fret_no, deadline=None, depth_counts=0):
        self.log.append((self.arm_id, "tap", string, fret_no))
        if self.fail == "fault":
            raise TimeoutError("Encoder arrival timed out; state uncertain")
        if self.fail == "halted":
            self.halt.set()
            raise fret.Halted("force stop: arm frozen mid-path, torque held")
        return {"status": "command_completed"}

    def rest(self, *, deadline=None):
        self.log.append((self.arm_id, "rest"))
        if self.fail == "park_fault":
            raise TimeoutError("exit failed")

    def close(self, torque_off=False):
        self.log.append((self.arm_id, "close", torque_off))


def dual_run(monkeypatch, *, primary_fail=None, secondary_fail=None,
             notes=(Note(string=1, fret=1), Note(arm=SECONDARY, string=6, fret=7),
                    Note(string=1, fret=2))):
    registry = two_arm_registry()
    monkeypatch.setattr(webapp, "read_registry", lambda: registry)
    log, made = [], {}

    def factory(arm_id, fail):
        def build(**kwargs):
            made[arm_id] = SeqArm(arm_id, log, fail=fail, **kwargs)
            return made[arm_id]
        return build

    monkeypatch.setattr(fret, "FretArm", factory(PRIMARY, primary_fail))
    monkeypatch.setattr(arm1, "Arm1LiftFirst", factory(SECONDARY, secondary_fail))
    plan = TapPlan(notes=list(notes), path_profile=PROFILE)
    try:
        completed = webapp.execute_take(plan, registry, threading.Event(), lambda event: None)
    except (TimeoutError, fret.Halted):
        completed = None
    return completed, log, made, registry


def test_clean_two_arm_take_is_strictly_sequential_then_parks_each_arm(monkeypatch):
    completed, log, made, registry = dual_run(monkeypatch)
    assert completed is True
    assert log == [(PRIMARY, "tap", 1, 1), (SECONDARY, "tap", 6, 7), (PRIMARY, "tap", 1, 2),
                   (PRIMARY, "rest"), (PRIMARY, "close", False),
                   (SECONDARY, "rest"), (SECONDARY, "close", False)]
    # both arms share ONE halt event (force stop freezes both) and each arm
    # received ITS OWN grid/paths, never the other arm's registry
    assert made[PRIMARY].halt is made[SECONDARY].halt
    assert made[PRIMARY].kwargs["paths"] is registry["paths"]
    assert made[SECONDARY].kwargs["paths"] is registry["secondary"]["paths"]
    assert made[SECONDARY].kwargs["grid"] is registry["secondary"]["grid"]
    assert webapp._active_halt["event"] is None


def test_primary_only_plan_never_opens_the_secondary_arm(monkeypatch):
    completed, log, made, _ = dual_run(monkeypatch, notes=(Note(string=1, fret=1),))
    assert completed is True
    assert SECONDARY not in made
    assert log == [(PRIMARY, "tap", 1, 1), (PRIMARY, "rest"), (PRIMARY, "close", False)]


def test_fault_on_one_arm_releases_both_with_no_recovery_motion(monkeypatch):
    completed, log, made, _ = dual_run(monkeypatch, secondary_fail="fault")
    assert completed is None
    assert log == [(PRIMARY, "tap", 1, 1), (SECONDARY, "tap", 6, 7),
                   (PRIMARY, "close", True), (SECONDARY, "close", True)]
    assert not any(step[1] == "rest" for step in log)


def test_force_stop_freezes_both_arms_with_torque_held(monkeypatch):
    completed, log, made, _ = dual_run(monkeypatch, secondary_fail="halted")
    assert completed is None
    assert log == [(PRIMARY, "tap", 1, 1), (SECONDARY, "tap", 6, 7),
                   (PRIMARY, "close", False), (SECONDARY, "close", False)]
    assert made[PRIMARY].halt.is_set()


def test_failed_primary_exit_stops_the_secondary_from_parking_too(monkeypatch):
    completed, log, _, _ = dual_run(monkeypatch, primary_fail="park_fault")
    assert completed is None  # failed exit is a fault, not a completed take
    assert log == [(PRIMARY, "tap", 1, 1), (SECONDARY, "tap", 6, 7), (PRIMARY, "tap", 1, 2),
                   (PRIMARY, "rest"), (PRIMARY, "close", True), (SECONDARY, "close", True)]


# ---- fret 6 rejection and arm derivation ---------------------------------

def test_row_6_has_no_owner_anywhere():
    assert owner_of_row(5) == PRIMARY and owner_of_row(7) == SECONDARY
    with pytest.raises(ValueError, match="no owner"):
        owner_of_row(6)
    with pytest.raises(ValueError, match="no owner"):
        tap_plans.key_context({(1, 6)})
    note = Note(string=1, fret=6)  # schema allows it; ownership checks reject it
    with pytest.raises(RehearsalError, match="does not own"):
        webapp.admit_motion(TapPlan(notes=[note], path_profile=PROFILE), two_arm_registry())


def test_key_context_and_expected_phrase_name_both_arms():
    context = tap_plans.key_context({(1, 1), (6, 9)})
    assert context[0]["arm"] == PRIMARY and context[1]["arm"] == SECONDARY
    phrase = expected_phrase(TapPlan(notes=[Note(string=1, fret=1)]))
    assert "two tap-only arms (lower rows 1-5, upper rows 7-11)" in phrase
    assert "two tap-only arms (lower rows 1-5, upper rows 7-11)" in tap_plans.REVISION_SYSTEM


def arrange_client(reply_notes):
    stub = Mock(model="moonshotai/Kimi-K3")
    stub.chat.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"title": "fixture", "notes": reply_notes})}}]}
    return stub


def test_arrange_with_available_secondary_offers_both_arms_and_derives_owner(monkeypatch):
    registry = two_arm_registry()
    stub = arrange_client([{"string": 6, "fret": 7}, {"arm": PRIMARY, "string": 1, "fret": 1}])
    monkeypatch.setattr(tap_plans, "BasetenClient", Mock(return_value=stub))
    result = tap_plans.arrange("both arms", registry["paths"].keys,
                               motion_context=registry["paths"].model_context(),
                               secondary_keys=registry["secondary"]["paths"].keys,
                               secondary_motion_context=registry["secondary"]["paths"].model_context())
    prompt = stub.chat.call_args.args[0][0]["content"]
    assert "BOTH tap arms are enabled" in prompt
    assert '"arm": "tap_secondary", "string": 6, "fret": 7' in prompt  # recorded key with owner
    assert "Secondary-arm reviewed motion graph" in prompt
    # the model omitted the arm; it is DERIVED from the fret row, never guessed
    assert result["notes"][0]["arm"] == SECONDARY and result["notes"][1]["arm"] == PRIMARY


def test_arrange_rejects_fret_6_and_unavailable_secondary(monkeypatch):
    registry = two_arm_registry()
    monkeypatch.setattr(tap_plans, "BasetenClient",
                        Mock(return_value=arrange_client([{"string": 1, "fret": 6}])))
    with pytest.raises(BasetenError, match="no plan accepted"):
        tap_plans.arrange("row six", registry["paths"].keys,
                          secondary_keys=registry["secondary"]["paths"].keys)
    monkeypatch.setattr(tap_plans, "BasetenClient",
                        Mock(return_value=arrange_client([{"string": 6, "fret": 7}])))
    with pytest.raises(BasetenError, match="unavailable arm"):
        tap_plans.arrange("upper note", registry["paths"].keys)  # secondary NOT offered


def test_tab_transcription_uses_union_of_available_keys_and_derives_arm(client, monkeypatch):  # noqa: F811
    import songsterr
    registry = two_arm_registry()
    monkeypatch.setattr(webapp, "read_registry", lambda: registry)
    tab = {"song": "S", "artist": "A", "track_name": "T", "track_index": 0,
           "tuning": songsterr.STANDARD_TUNING, "standard_tuning": True,
           "tempo_bpm": 90,
           "notes": [{"measure": 1, "string": 1, "fret": 1},
                     {"measure": 1, "string": 6, "fret": 7}], "total_notes": 2}
    monkeypatch.setattr(webapp.songsterr, "fetch_track_notes", lambda song_id, track=None: tab)
    monkeypatch.setattr(webapp, "arrange",
                        Mock(side_effect=AssertionError("tab mode must not call the model")))
    response = client.post("/api/plan", json={"prompt": "play S", "allow_inference": True,
                                              "songsterr_song_id": 7})
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == [{"arm": PRIMARY, "string": 1, "fret": 1, "beats": 1.0, "pause_ms": 0},
                                        {"arm": SECONDARY, "string": 6, "fret": 7, "beats": 1.0, "pause_ms": 0}]
    assert response.json()["transcription"]["exact"] == 2


def test_bootstrap_exposes_union_keys_and_secondary_availability(client, monkeypatch):  # noqa: F811
    registry = two_arm_registry()
    registry["warnings"] = []
    monkeypatch.setattr(webapp, "read_registry", lambda: registry)
    data = client.get("/api/bootstrap").json()
    owners = {(k["string"], k["fret"]): k["arm"] for k in data["keys"]}
    assert owners[(1, 1)] == PRIMARY and owners[(6, 7)] == SECONDARY
    assert data["secondary_available"] is True
    assert "one arm moves at a time" in data["coordination"]
    caps = {c["arm"]: c for c in data["arm_capabilities"]}
    assert caps[SECONDARY]["available_for_planning"] is True


# ---- revisions across two arms -------------------------------------------

def secondary_plan():
    return TapPlan(notes=[Note(arm=SECONDARY, string=6, fret=7),
                          Note(arm=SECONDARY, string=6, fret=8)], path_profile=PROFILE)


def secondary_proposal(**overrides):
    notes = [{**n.model_dump(), "source_index": i} for i, n in enumerate(secondary_plan().notes)]
    data = {"decision": "revise", "rationale": "Bounded timing tweak.", "notes": notes,
            "path_profile": PROFILE, "inspection_notes": []}
    data.update(overrides)
    return tap_plans.Proposal.model_validate(data)


def test_revision_validates_secondary_notes_against_their_own_arm():
    enabled = {PRIMARY: {(1, 1)}, SECONDARY: set(ARM1_KEYS)}
    proposal = secondary_proposal()
    proposal.notes[0].pause_ms = 300
    result = compile_revision(proposal, secondary_plan(), {(1, 1)},
                              (PROFILE,), enabled_arm_keys=enabled)
    assert result["changes"] == [{"kind": "timing", "note_index": 0,
                                  "before_ms": 250, "after_ms": 300}]
    # without the secondary enabled, the same plan is rejected, never remapped
    with pytest.raises(ValueError):
        compile_revision(proposal, secondary_plan(), {(1, 1)}, (PROFILE,))


def test_positioning_revision_cannot_borrow_the_other_arms_key():
    # (1, 4) on the primary and (2, 9) on the secondary sound the same pitch
    assert tap_plans.pitch(1, 4) == tap_plans.pitch(2, 9)
    plan = TapPlan(notes=[Note(string=1, fret=4)], path_profile=PROFILE)
    enabled = {PRIMARY: {(1, 4)}, SECONDARY: {(2, 9)}}
    data = {"decision": "revise", "rationale": "same pitch elsewhere",
            "notes": [{"arm": PRIMARY, "string": 2, "fret": 9, "pause_ms": 250, "source_index": 0}],
            "path_profile": PROFILE, "inspection_notes": []}
    with pytest.raises(ValueError, match="does not own|unrecorded"):
        compile_revision(tap_plans.Proposal.model_validate(data), plan, {(1, 4)},
                         (PROFILE,), enabled_arm_keys=enabled)


def test_manager_admits_secondary_take_only_when_available(tmp_path):
    from rehearsal import RehearsalManager
    registry = two_arm_registry()
    execute = MagicMock()
    manager = RehearsalManager(tmp_path, registry=lambda: registry, execute=execute,
                               admit=webapp.admit_motion)
    record = manager.create(secondary_plan())
    assert record["phase"] == "ready"
    assert [a["arm"] for a in record["trajectory"]["assignments"]] == [SECONDARY, SECONDARY]
    manager.stop(record["attempt_id"])
    registry["secondary"]["available"] = False
    registry["secondary"]["paths"] = None
    registry["secondary"]["path_blocker"] = "no hover poses recorded"
    with pytest.raises(RehearsalError, match="not available"):
        manager.create(secondary_plan())
    execute.assert_not_called()
