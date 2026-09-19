"""No hardware, no API: guards, interpolation, tools and the full loop on a FakeArm."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools import ToolCall, Toolbox  # noqa: E402
from robot import poses as pose_store  # noqa: E402
from robot.arm import MAX_DEG_PER_S, FakeArm, interpolate  # noqa: E402
from robot.guards import (JOINTS, GuardError, Limits, calibrated_box, calibration_problems, check_at,  # noqa: E402
                          check_trajectory, workspace_box)

REST = dict(zip(JOINTS, [0, -90, 90, 60, 0, 10]))
ABOVE = dict(zip(JOINTS, [20, -40, 40, 30, 0, 10]))
START = dict(zip(JOINTS, [18, -35, 38, 35, 0, 10]))
END = dict(zip(JOINTS, [26, -35, 38, 35, 0, 10]))


@pytest.fixture
def arm(tmp_path, monkeypatch):
    monkeypatch.setattr(pose_store, "POSE_DIR", tmp_path)
    for name, q in {"rest": REST, "above_string": ABOVE, "pluck_start": START, "pluck_end": END}.items():
        pose_store.save_pose("t", name, q)
    a = FakeArm("t")
    a.connect()
    return a


def test_calibrated_box_degrees():
    cal = {j: {"range_min": 1000, "range_max": 3000} for j in JOINTS}
    box = calibrated_box(cal)
    assert box["elbow_flex"] == pytest.approx((-87.9, 87.9), abs=0.1)
    assert box["gripper"] == (0.0, 100.0)


def test_trajectory_outside_workspace_is_rejected_not_clamped():
    ws = workspace_box({"a": REST, "b": ABOVE}, margin_deg=5)
    lim = Limits(hard={j: (-180, 180) for j in JOINTS}, workspace=ws, max_deg_per_s=120)
    bad = dict(ABOVE, shoulder_pan=60)
    with pytest.raises(GuardError, match="workspace"):
        check_trajectory([ABOVE, bad], lim, dt=1)


def test_speed_cap():
    lim = Limits(hard={j: (-180, 180) for j in JOINTS}, workspace={j: (-180, 180) for j in JOINTS}, max_deg_per_s=100)
    with pytest.raises(GuardError, match="deg/s"):
        check_trajectory([REST, dict(REST, shoulder_pan=5)], lim, dt=0.02)   # 250 deg/s


def test_interpolation_respects_cap():
    traj = interpolate(REST, ABOVE, MAX_DEG_PER_S)
    steps = [REST] + traj
    worst = max(abs(b[j] - a[j]) for a, b in zip(steps, steps[1:]) for j in JOINTS if j != "gripper")
    assert worst * 50 <= MAX_DEG_PER_S + 1e-6
    assert traj[-1] == pytest.approx(ABOVE)


def test_check_at_detects_drift():
    with pytest.raises(GuardError, match="elbow_flex"):
        check_at(REST, dict(REST, elbow_flex=REST["elbow_flex"] + 20), tol_deg=6)


def test_pluck_and_state(arm):
    arm.move_to("above_string", speed=1.0)
    assert arm.state()["at"] == "above_string"
    arm.pluck(depth_mm=5, speed=1.0)
    assert arm.state()["at"] == "above_string"


def test_arm_pushed_by_hand_blocks_motion(arm):
    arm.q["shoulder_lift"] += 30
    with pytest.raises(GuardError, match="not where expected"):
        arm.move_to("above_string")


def test_tool_out_of_range_is_error(arm):
    tools = Toolbox(arm, mic=None, use_camera=False)
    r = tools.run(ToolCall("1", "pluck", {"depth_mm": 40, "speed": 0.5}))
    assert r.is_error and "depth_mm" in json.loads(r.text)["rejected_by_guard"]
    r = tools.run(ToolCall("2", "pluck", {"depth_mm": 3, "speed": 1.0}))
    assert not r.is_error and json.loads(r.text)["arm"]["at"] == "above_string"


def test_full_loop_scripted(arm, monkeypatch, tmp_path):
    from agent import loop

    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["loop", "--role", "pluck", "--backend", "scripted", "--fake-arm",
                                      "--id", "t", "--no-mic", "--no-camera"])
    loop.main()
    run = next((tmp_path / "runs").iterdir())
    recs = [json.loads(line) for line in (run / "decisions.jsonl").read_text().splitlines()]
    tools_run = [r for r in recs if r["event"] == "tool"]
    assert [r["tool"] for r in tools_run] == ["look", "move_to", "pluck", "pluck", "pluck", "move_to", "done"]
    assert "rejected" in tools_run[3]            # the depth_mm=40 pluck


def _karplus(hz: float, seconds: float = 1.3, sr: int = 44100, start_s: float = 0.1):
    import numpy as np
    rng = np.random.default_rng(0)
    n = int(sr / hz)
    buf = rng.uniform(-1, 1, n)
    out = np.zeros(int(seconds * sr))
    s0 = int(start_s * sr)
    for i in range(s0, len(out)):
        out[i] = buf[(i - s0) % n]
        buf[(i - s0) % n] = 0.996 * 0.5 * (buf[(i - s0) % n] + buf[(i - s0 + 1) % n])
    return (out * 0.3 + rng.normal(0, 0.002, len(out))).astype("float32")


def test_scorer_on_synthetic_pluck():
    from sense.mic import note_name, onsets, pitch

    x = _karplus(110.0)
    assert note_name(pitch(x)) == "A2"
    ons = onsets(x)
    assert len(ons) == 1 and abs(ons[0] - 0.1) < 0.03
    assert note_name(pitch(_karplus(146.83))) == "D3"


def _true_pose(string: int, fret: float, kind: str) -> dict:
    """A smooth, nonlinear stand-in for the real arm's joint angles over the fretboard."""
    from robot.fretmap import fret_pos
    d, y = fret_pos(fret), (6 - string) / 5
    lift = 6.0 if kind == "above" else 0.0
    return {"shoulder_pan": 40 * d + 15 * y + 8 * d * d, "shoulder_lift": -30 + 25 * d - lift,
            "elbow_flex": 50 - 30 * d + 5 * y + lift, "wrist_flex": 10 + 12 * d * d - 0.5 * lift,
            "wrist_roll": 3 * y, "gripper": 0.0}


def _anchors(strings=(6, 5, 4, 3, 2, 1), frets=(1, 5, 9)):
    return {f"s{s}f{f}": {k: _true_pose(s, f, k) for k in ("above", "touch")} for s in strings for f in frets}


def test_fretmap_follows_fret_spacing():
    from robot import fretmap
    poses = fretmap.build(_anchors())
    assert len(poses) == 6 * 9 * 2
    worst = max(abs(poses[fretmap.name(k, s, f)][j] - _true_pose(s, f, k)[j])
                for s in range(1, 7) for f in range(1, 10) for k in ("above", "touch") for j in JOINTS)
    assert worst < 0.05   # quadratic in fret position reproduces the curve through the anchors


def test_fretmap_interpolates_missing_strings_and_skips_partial():
    from robot import fretmap
    anchors = _anchors(strings=(6, 1))
    anchors["s3f1"] = {k: _true_pose(3, 1, k) for k in ("above", "touch")}   # partial: ignored
    poses = fretmap.build(anchors)
    assert sorted(fretmap.available(poses)) == [1, 2, 3, 4, 5, 6]
    mid = poses[fretmap.name("touch", 3, 5)]["shoulder_pan"]
    assert abs(mid - _true_pose(3, 5, "touch")["shoulder_pan"]) < 0.5   # linear across strings


def test_press_goes_past_touch_along_approach():
    from robot import fretmap
    a, t = _true_pose(4, 3, "above"), _true_pose(4, 3, "touch")
    p = fretmap.press_pose(a, t, fretmap.HOVER_MM / 2)
    assert p["shoulder_lift"] == pytest.approx(t["shoulder_lift"] + 0.5 * (t["shoulder_lift"] - a["shoulder_lift"]))


@pytest.fixture
def fret_arm(tmp_path, monkeypatch):
    from robot import fretmap
    monkeypatch.setattr(pose_store, "POSE_DIR", tmp_path)
    pose_store.save_pose("f", "rest", dict(_true_pose(3, 5, "above"), shoulder_lift=-20))
    data = json.loads(pose_store.path_for("f").read_text())
    data["poses"].update(fretmap.build(_anchors()))
    pose_store.path_for("f").write_text(json.dumps(data))
    data = json.loads(pose_store.path_for("f").read_text())
    data["poses"]["ready"] = dict(data["poses"]["above_s3_f5"], shoulder_lift=data["poses"]["above_s3_f5"]["shoulder_lift"] - 4)
    pose_store.path_for("f").write_text(json.dumps(data))
    a = FakeArm("f")
    a.connect()
    return a


def test_refuses_fretboard_entry_without_ready(fret_arm):
    del fret_arm.poses["ready"]
    fret_arm.move_to("rest")
    with pytest.raises(GuardError, match="ready"):
        fret_arm.fret(5, 3, press_mm=0)


def test_fret_lifts_before_travel(fret_arm):
    from robot import fretmap
    fret_arm.fret(5, 7, press_mm=8)                        # deepest press must pass the guards
    assert fret_arm.state()["at"] == "pressing string 5 fret 7"
    sent = []
    orig = fret_arm._send
    fret_arm._send = lambda q: (sent.append(q), orig(q))
    fret_arm.fret(2, 3, press_mm=2)
    lift = next(i for i, q in enumerate(sent) if q == pytest.approx(fret_arm.poses[fretmap.name("above", 5, 7)]))
    travel = next(i for i, q in enumerate(sent) if q == pytest.approx(fret_arm.poses[fretmap.name("above", 2, 3)]))
    assert lift < travel                                   # lifted off before moving across the neck
    with pytest.raises(GuardError, match="release"):
        fret_arm.move_to("rest")
    fret_arm.release()
    fret_arm.move_to("rest")


def test_full_loop_scripted_fret(fret_arm, monkeypatch, tmp_path):
    from agent import loop

    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["loop", "--role", "fret", "--backend", "scripted", "--fake-arm",
                                      "--id", "f", "--no-mic", "--no-camera"])
    loop.main()
    run = next((tmp_path / "runs").iterdir())
    tools_run = [json.loads(line) for line in (run / "decisions.jsonl").read_text().splitlines()]
    tools_run = [r for r in tools_run if r["event"] == "tool"]
    assert [r["tool"] for r in tools_run] == ["look", "fret", "fret", "move_to", "release", "fret", "move_to", "done"]
    assert "release first" in tools_run[3]["rejected"]      # move_to while holding a fret
    assert "press_mm" in tools_run[5]["rejected"]           # 12 mm > 8 mm cap
    assert tools_run[1]["result"]["expected"] == "E3"       # string 5 (A2) fret 7
    assert tools_run[2]["result"]["expected"] == "A3"       # string 3 (G3) fret 2


def test_wrapped_calibration_is_flagged():
    cal = {j: {"range_min": 900, "range_max": 3200} for j in JOINTS}
    cal["wrist_roll"] = {"range_min": 0, "range_max": 4095}      # full turn by design: fine
    assert calibration_problems(cal) == []
    cal["elbow_flex"] = {"range_min": 6, "range_max": 4090}      # the real fret_arm file, 2026-09-19
    assert [p.split(":")[0] for p in calibration_problems(cal)] == ["elbow_flex"]


def test_anchor_warnings_catch_recording_mistakes():
    from robot import fretmap
    a = _anchors()
    assert fretmap.anchor_warnings(a) == []
    a["s6f9"]["touch"] = dict(a["s6f9"]["touch"], wrist_roll=a["s6f9"]["above"]["wrist_roll"] + 21.6)
    a["s3f9"]["above"] = {j: v + 0.15 * (a["s3f9"]["above"][j] - v) for j, v in a["s3f9"]["touch"].items()}
    assert [w.split(":")[0] for w in fretmap.anchor_warnings(a)] == ["s3f9", "s6f9"]


def test_elbow_flip_is_rejected_real_poses():
    """The move that swung the fret arm on 2026-09-19: rest (elbow -66) -> string 6 fret 1 (elbow +65)."""
    from robot.guards import check_segments
    rest = {"shoulder_pan": -52.4, "shoulder_lift": -2.5, "elbow_flex": -66.5, "wrist_flex": -8.4, "wrist_roll": 13.5, "gripper": 0}
    s6f1 = {"shoulder_pan": -47.0, "shoulder_lift": -47.0, "elbow_flex": 65.4, "wrist_flex": 88.0, "wrist_roll": 7.3, "gripper": 0}
    with pytest.raises(GuardError, match="elbow_flex"):
        check_segments([rest, s6f1])


def test_collision_stops_motion(fret_arm):
    """A joint that stops following its command (arm hit something) halts the move and holds."""
    fret_arm.move_to("rest")
    orig = fret_arm._send

    blocked_at = fret_arm.poses["rest"]["shoulder_pan"] - 8                     # obstacle shoves pan back

    def stuck_pan(q):
        orig(dict(q, shoulder_pan=blocked_at))
    fret_arm._send = stuck_pan
    with pytest.raises(GuardError, match="shoulder_pan .* behind"):
        fret_arm.fret(1, 9, press_mm=0, speed=1.0)
    assert fret_arm.last_cmd["shoulder_pan"] == pytest.approx(blocked_at)     # holds where it stopped


def test_enters_and_leaves_fretboard_via_ready(fret_arm):
    ready = fret_arm.poses["ready"]
    fret_arm.move_to("rest")
    sent = []
    orig = fret_arm._send
    fret_arm._send = lambda q: (sent.append(dict(q)), orig(q))
    fret_arm.fret(6, 1, press_mm=0)
    assert any(q == pytest.approx(ready) for q in sent)           # went through ready on the way in
    sent.clear()
    fret_arm.rest()
    assert any(q == pytest.approx(ready) for q in sent)           # and on the way out


def test_parse_spot():
    from robot.fretmap import parse_spot, spot_name
    assert parse_spot("A5") == (5, 5)
    assert parse_spot("e1") == (6, 1) and parse_spot("E9") == (1, 9)     # low e vs high E
    assert parse_spot("g3") == (3, 3) and parse_spot(" b2 ") == (2, 2)   # A D G B any case
    for bad in ("X3", "A0", "A10", "A", "5A"):
        with pytest.raises(ValueError):
            parse_spot(bad)
    assert spot_name(6, 1) == "e1" and spot_name(1, 9) == "E9"


class _SpeedServoSim:
    """Bus stand-in for the base servo: raw ticks, homing offset, and speed mode reporting the
    encoder WITHOUT the offset (as measured on the real servo)."""
    MID, OFFSET = 2510.5, 1740

    def __init__(self, pos_deg=0.0, sign=1):
        from types import SimpleNamespace
        self.p, self.v, self.t, self.sign = pos_deg, 0.0, None, sign
        self.regs = {"Operating_Mode": 0, "Homing_Offset": self.OFFSET}
        self.calibration = {"shoulder_pan": SimpleNamespace(range_min=1652, range_max=3369)}

    def _tick(self):
        import time as _t
        now = _t.monotonic()
        if self.t is not None and self.regs["Operating_Mode"] == 1:
            self.p += self.sign * self.v * (now - self.t)
        self.t = now

    def read(self, reg, motor, normalize=True):
        self._tick()
        if reg == "Present_Position":
            raw = self.MID + self.p * 4095 / 360
            return int(round(raw + self.OFFSET)) % 4096 if self.regs["Operating_Mode"] == 1 else int(round(raw))
        return self.regs.get(reg, 0)

    def write(self, reg, motor, val, normalize=True):
        self._tick()
        if reg == "Goal_Velocity":
            from robot.base_speed import STEPS_PER_DEG
            self.v = val / STEPS_PER_DEG
        self.regs[reg] = val


def test_speed_base_reaches_targets_both_ways():
    from robot.base_speed import SpeedBase
    sim = _SpeedServoSim(pos_deg=75.0)                  # the real failing case: near the top end
    base = SpeedBase(sim, hz=200)
    start = base.pos()
    assert abs(start - 75.0) < 0.2
    for target in (70.0, 65.0, 75.0 - 0.5):
        err = base.move_to(target, timeout_s=5)
        assert abs(err) <= base.tol and abs(sim.p - target) < 1.0
    assert sim.v == 0


def test_speed_base_aborts_when_servo_turns_wrong_way():
    from robot.base_speed import SpeedBase
    sim = _SpeedServoSim(pos_deg=0.0, sign=-1)          # a servo that runs backwards
    base = SpeedBase(sim, hz=200)
    with pytest.raises(GuardError, match="wrong way"):
        base.move_to(5.0, timeout_s=5)
    assert sim.v == 0                                  # left stopped


def test_moves_run_base_first_then_other_joints(fret_arm):
    from robot import fretmap
    fret_arm.move_to("ready")
    sent = []
    orig = fret_arm._send
    fret_arm._send = lambda q: (sent.append(dict(q)), orig(q))
    target = fret_arm.poses[fretmap.name("above", 1, 9)]
    fret_arm.move_to(fretmap.name("above", 1, 9))
    ready = fret_arm.poses["ready"]
    first_other = next(i for i, q in enumerate(sent) if abs(q["elbow_flex"] - ready["elbow_flex"]) > 1e-6)
    assert sent[first_other - 1]["shoulder_pan"] == pytest.approx(target["shoulder_pan"])   # base done first
    assert all(q["shoulder_pan"] == pytest.approx(target["shoulder_pan"]) for q in sent[first_other:])
