"""Force stop freezes mid-path with torque held; clean takes park at rest."""
import threading

import fret
import pytest
import webapp
from tap_plans import Note, TapPlan
from path_fixtures import path_registry
from test_tap_web import client  # noqa: F401 - pytest fixture

def test_force_stop_requires_an_executing_take(client):  # noqa: F811
    response = client.post("/api/force-stop", json={})
    assert response.status_code == 409
    assert "No take is executing" in response.json()["detail"]


def test_force_stop_sets_the_active_halt_event(client):  # noqa: F811
    halt = threading.Event()
    webapp._active_halt["event"] = halt
    try:
        response = client.post("/api/force-stop", json={})
        assert response.status_code == 200
        assert response.json()["torque"] == "held"
        assert halt.is_set()
    finally:
        webapp._active_halt["event"] = None


def test_halt_freezes_every_motor_at_present_position():
    class Bus:
        def __init__(self):
            self.goals = []

        def read_pos(self, sid):
            return 1500

        def goto(self, sid, pos, speed=0, acc=0):
            self.goals.append((sid, pos))

    arm = fret.FretArm.__new__(fret.FretArm)
    arm.bus = Bus()
    arm.halt = threading.Event()
    arm.halt.set()
    with pytest.raises(fret.Halted):
        arm._move({sid: 1000 for sid in fret.MOTOR_IDS}, 400)
    assert arm.bus.goals == [(sid, 1500) for sid in fret.MOTOR_IDS]


class FakeArm:
    def __init__(self, *, halt=None, mode="ok", **_kwargs):
        self.halt, self.mode, self.calls = halt, mode, []

    def tap_key(self, string, fret_no, deadline=None):
        self.calls.append(("tap", string, fret_no))
        if self.mode == "fault":
            raise TimeoutError("Encoder arrival timed out; state uncertain")
        if self.mode == "halted":
            self.halt.set()
            raise fret.Halted("force stop: arm frozen mid-path, torque held")
        return {"status": "command_completed"}

    def rest(self, *, deadline=None):
        assert webapp._active_halt["event"] is self.halt
        self.calls.append(("rest",))
        if self.mode == "halted_exit":
            self.halt.set()
            raise fret.Halted("fixture: force stop during final exit")

    def close(self, torque_off=False):
        self.calls.append(("close", torque_off))


def _run(monkeypatch, mode):
    registry = path_registry(keys=((1, 1),))
    monkeypatch.setattr(webapp, "read_registry", lambda: registry)
    arms = []

    def fake_arm(**kwargs):
        arm = FakeArm(mode=mode, **kwargs)
        arms.append(arm)
        return arm

    monkeypatch.setattr(fret, "FretArm", fake_arm)
    plan = TapPlan(notes=[Note(string=1, fret=1)], path_profile="lift_first")
    try:
        completed = webapp.execute_take(plan, registry, threading.Event(), lambda event: None)
    except (TimeoutError, fret.Halted):
        completed = None
    return completed, arms[0]


def test_clean_take_parks_at_rest_before_torque_off(monkeypatch):
    completed, arm = _run(monkeypatch, "ok")
    assert completed is True
    assert arm.calls == [("tap", 1, 1), ("rest",), ("close", False)]  # held at rest


def test_fault_makes_no_recovery_motion_and_releases_torque(monkeypatch):
    # A stalled servo must not keep driving into an obstruction: faults keep
    # the original body-torque-off, no-homing contract.
    completed, arm = _run(monkeypatch, "fault")
    assert completed is None
    assert arm.calls == [("tap", 1, 1), ("close", True)]


def test_force_stop_holds_torque_and_never_moves_again(monkeypatch):
    completed, arm = _run(monkeypatch, "halted")
    assert completed is None
    assert arm.calls == [("tap", 1, 1), ("close", False)]


def test_force_stop_stays_registered_through_final_exit(monkeypatch):
    completed, arm = _run(monkeypatch, "halted_exit")
    assert completed is None
    assert arm.calls == [("tap", 1, 1), ("rest",), ("close", False)]
    assert webapp._active_halt["event"] is None
