"""Callable motions and base-mode routing; no serial ports or model APIs."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import motions
from robot.arm import Arm, RealArm
from robot.guards import GuardError, JOINTS


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("robot.arm.time.sleep", lambda _: None)
    with motions.connect() as m:
        yield m


def test_default_is_fake_and_lists_saved_map(session):
    assert isinstance(session._arm, motions.FakeArm)
    assert len(session.available()["spots"]) == 54
    assert session.where()["at"] == "rest"


def test_motion_sequence(session):
    session.ready()
    session.hover("A5")
    assert session._arm.pressing is None
    session.touch("A5")
    assert session._arm.pressing == (5, 5)
    session.press("A5", press_mm=1)
    session.release()
    assert session._arm.pressing is None
    session.rest()
    assert session.where()["at"] == "rest"


def test_hover_lifts_before_cross_string_travel(session):
    session.touch("A5")
    sent = []
    original = session._arm._send
    def record(q):
        sent.append(dict(q))
        original(q)
    session._arm._send = record
    session.hover("G3")
    above_old = session._arm.poses["above_s5_f5"]
    above_new = session._arm.poses["above_s3_f3"]
    def reached(p):
        return next(i for i, q in enumerate(sent)
                    if all(q[j] == pytest.approx(p[j]) for j in JOINTS[:-1]))
    assert reached(above_old) < reached(above_new)
    assert session._arm.pressing is None


def test_named_pose_dispatch_preserves_contact_and_exit(session):
    session.move_to("touch_s5_f5")
    assert session._arm.pressing == (5, 5)
    session.move_to("above_s3_f3")
    assert session._arm.pressing is None
    session.move_to("touch_s3_f3")
    session.move_to("rest")
    assert session._arm.pressing is None
    assert session.where()["at"] == "rest"


@pytest.mark.parametrize("depth", [-1, 9, float("nan"), float("inf")])
def test_bad_depth_rejected_before_motion(session, depth):
    session._arm._send = Mock()
    with pytest.raises(ValueError, match="press_mm"):
        session.press("A5", depth)
    session._arm._send.assert_not_called()


@pytest.mark.parametrize("speed", [0, 1.1, float("nan"), float("inf")])
def test_bad_speed_rejected_before_motion(session, speed):
    session._arm._send = Mock()
    with pytest.raises(ValueError, match="speed"):
        session.hover("A5", speed)
    session._arm._send.assert_not_called()


def test_unknown_spots_and_missing_pluck_poses_do_not_move(session):
    session._arm._send = Mock()
    with pytest.raises(ValueError):
        session.hover("A10")
    with pytest.raises(GuardError):
        session.move_to("not-recorded")
    with pytest.raises(GuardError, match="not recorded"):
        session.pluck()
    session._arm._send.assert_not_called()


def test_disconnect_is_idempotent_and_blocks_further_calls(session):
    session._arm.disconnect = Mock()
    session.disconnect()
    session.disconnect()
    session._arm.disconnect.assert_called_once()
    with pytest.raises(RuntimeError, match="disconnected"):
        session.ready()


def test_exception_in_context_disconnects(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(motions, "FakeArm", lambda _: fake)
    with pytest.raises(RuntimeError, match="test failure"):
        with motions.connect():
            raise RuntimeError("test failure")
    fake.disconnect.assert_called_once()
    fake.rest.assert_not_called()


def test_hardware_factory_selects_normal_base_explicitly(monkeypatch):
    ctor = Mock()
    monkeypatch.setattr(motions, "RealArm", ctor)
    m = motions.connect(fake=False)
    ctor.assert_called_once_with(motions.DEFAULT_PORT, "fret_arm", 6, base_mode="position")
    ctor.return_value.connect.assert_called_once()
    m.disconnect()


@pytest.mark.parametrize("mode,includes_base", [("position", True), ("speed", False)])
def test_real_send_routes_base_by_mode(mode, includes_base):
    arm = RealArm.__new__(RealArm)
    arm.base_mode = mode
    arm.robot = Mock()
    arm._send(dict.fromkeys(JOINTS, 0))
    action = arm.robot.send_action.call_args.args[0]
    assert ("shoulder_pan.pos" in action) is includes_base


def test_normal_base_uses_guarded_interpolator(monkeypatch):
    arm = RealArm.__new__(RealArm)
    arm.base_mode = "position"
    arm.base = None
    move = Mock()
    monkeypatch.setattr(Arm, "_move_base", move)
    trajectory = [dict.fromkeys(JOINTS, 0)]
    arm._move_base(trajectory, 0.3)
    move.assert_called_once_with(trajectory, 0.3)


def test_speed_base_retains_legacy_routing():
    arm = RealArm.__new__(RealArm)
    arm.base_mode = "speed"
    arm.base = Mock()
    arm._move_base([{"shoulder_pan": 5}], 0.3)
    arm.base.move_to.assert_called_once_with(5)
    assert arm.base.vmax == 25


def test_calibration_mismatch_does_not_write_or_enable_torque(tmp_path):
    arm = RealArm.__new__(RealArm)
    arm.arm_id = "fret_arm"
    cal = json.loads((Path(__file__).parents[1] / "robot/calibration/fret_arm.json").read_text())
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(cal))
    arm.robot = Mock()
    arm.robot.calibration_fpath = path
    arm.robot.calibration = {j: SimpleNamespace(**c) for j, c in cal.items()}
    arm.robot.bus.motors = {j: SimpleNamespace(id=c["id"]) for j, c in cal.items()}
    arm.robot.is_calibrated = False
    with pytest.raises(GuardError, match="differs"):
        arm.connect()
    arm.robot.bus.write_calibration.assert_not_called()
    arm.robot.bus.sync_write.assert_not_called()
    arm.robot.configure.assert_not_called()
    arm.robot.bus.disconnect.assert_called_once_with(disable_torque=False)


def test_rejected_plan_has_no_gripper_side_effects(session):
    session._arm._before_motion = Mock()
    session._arm.poses["bad"] = dict(session._arm._read(), elbow_flex=999)
    with pytest.raises(GuardError):
        session.move_to("bad")
    session._arm._before_motion.assert_not_called()
