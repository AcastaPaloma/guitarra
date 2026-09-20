"""Offline orchestration regression checks; no API calls or hardware connections."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.backends import Turn  # noqa: E402
from agent.protocol import ToolCall  # noqa: E402
from orchestration.rig import FakeRig, PROFILE  # noqa: E402
from orchestration.runner import run  # noqa: E402
from orchestration.scenarios import SCENARIOS  # noqa: E402


@pytest.fixture
def rig():
    r = FakeRig()
    yield r
    r.close()


def call(rig, name, **args):
    result = rig.run(ToolCall(f"call-{len(rig.events)}", name, args))
    return json.loads(result.text)


def press(rig, string=5, fret=5):
    return call(rig, "press", string=string, fret=fret, profile=PROFILE)


def pluck(rig, string=5):
    return call(rig, "pluck", string=string, profile=PROFILE)


def test_pick_requires_ready_and_real_fake_fret_contact(rig):
    assert pluck(rig)["error_code"] == "pick_not_ready"
    assert call(rig, "ready", arm="pick")["ok"]
    assert pluck(rig)["error_code"] == "fret_not_pressed"
    assert call(rig, "touch", string=5, fret=5)["ok"]
    assert pluck(rig)["error_code"] == "fret_not_pressed"
    assert press(rig)["ok"]
    assert pluck(rig, 3)["error_code"] == "wrong_string"
    assert pluck(rig)["ok"]
    assert rig.pick_at == "ready"
    assert rig.plucks[0]["fret"] == 5


def test_existing_motion_impl_lifts_before_changed_target(rig):
    assert press(rig)["ok"]
    sent = []
    original = rig.arm._send
    def record(q):
        sent.append(dict(q))
        original(q)
    rig.arm._send = record
    assert press(rig, 3, 3)["ok"]
    above_old = rig.arm.poses["above_s5_f5"]
    touch_new = rig.arm.poses["touch_s3_f3"]
    def reached(pose):
        return next(i for i, q in enumerate(sent) if all(q[j] == pytest.approx(pose[j]) for j in pose if j != "gripper"))
    assert reached(above_old) < reached(touch_new)
    assert len({q["gripper"] for q in sent}) == 1


@pytest.mark.parametrize("name,args", [
    ("open_gripper", {}),
    ("press", {"string": 5, "fret": 12, "profile": PROFILE}),
    ("press", {"string": True, "fret": 5, "profile": PROFILE}),
    ("press", {"string": 5, "fret": 5, "profile": "more_torque"}),
    ("press", {"string": 5, "fret": 5, "profile": PROFILE, "press_mm": 999}),
    ("move_to", {"pose": "arbitrary_coordinates"}),
])
def test_invalid_tools_do_not_move(rig, name, args):
    before = rig.state()
    assert not call(rig, name, **args)["ok"]
    assert rig.state() == before


def test_duplicate_call_is_not_replayed(rig):
    c = ToolCall("same", "ready", {"arm": "pick"})
    assert not rig.run(c).is_error
    now = rig.clock.now
    assert rig.run(c).is_error
    assert rig.clock.now == now


def test_done_does_not_hide_held_fret_with_cleanup(rig):
    press(rig)
    assert not call(rig, "done", outcome="completed", reason="wrong")["ok"]
    assert rig.arm.pressing == (5, 5)
    assert call(rig, "release")["ok"]
    assert call(rig, "done", outcome="completed", reason="released")["ok"]
    now = rig.clock.now
    rig.close()
    assert rig.clock.now == now  # no automatic rest on exit


def test_fault_latches_and_motion_is_not_retried():
    r = FakeRig(fail_first_press=True)
    try:
        assert press(r)["error_code"] == "injected_fault"
        before = r.state()
        assert press(r)["error_code"] == "fault_latched"
        assert call(r, "rest", arm="fret")["error_code"] == "fault_latched"
        assert r.state() == before
        assert call(r, "where")["ok"]
        assert call(r, "done", outcome="blocked", reason="uncertain execution")["ok"]
    finally:
        r.close()


class Scripted:
    name = "scripted_test_not_baseten"
    model = "offline_fixture"

    def __init__(self, steps):
        self.steps = iter(steps)
        self.n = 0

    def next(self):
        name, args = next(self.steps)
        self.n += 1
        return Turn("", [ToolCall(f"step-{self.n}", name, args)], stop="tool_use")

    def begin(self, system, tool_specs, text, image_jpeg):
        assert image_jpeg is None
        assert "FAKE" in system
        return self.next()

    def respond(self, results, note=None):
        assert all(r.image_jpeg is None for r in results)
        return self.next()


def complete_steps():
    return [
        ("ready", {"arm": "pick"}),
        ("press", {"string": 5, "fret": 5, "profile": PROFILE}),
        ("pluck", {"string": 5, "profile": PROFILE}),
        ("pluck", {"string": 5, "profile": PROFILE}),
        ("press", {"string": 3, "fret": 3, "profile": PROFILE}),
        ("pluck", {"string": 3, "profile": PROFILE}),
        ("release", {}),
        ("done", {"outcome": "completed", "reason": "fixture completed"}),
    ]


def test_full_workflow_and_real_trace_grading(tmp_path):
    output = tmp_path / "run"
    report = run(SCENARIOS["repeat-and-change"], Scripted(complete_steps()), output_dir=output, verbose=False)
    assert report["evaluation"]["passed"]
    assert report["evaluation"]["redundant_repeat_presses"] == 0
    assert report["evaluation"]["unnecessary_fret_neutral_between_notes"] == []
    assert report["model_requests"] == 8
    assert report["virtual_seconds"] > 0
    assert report["hardware_enabled"] is False
    assert report["provider"] == "scripted_test_not_baseten"
    records = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    assert len([r for r in records if r["type"] == "tool"]) == 8
    assert (output / "tools.json").exists()


def test_returning_to_fret_neutral_between_notes_fails_efficiency_grading(tmp_path):
    plan = [
        ("ready", {"arm": "pick"}),
        ("press", {"string": 5, "fret": 5, "profile": PROFILE}),
        ("pluck", {"string": 5, "profile": PROFILE}),
        ("release", {}),
        ("rest", {"arm": "fret"}),
        ("press", {"string": 3, "fret": 3, "profile": PROFILE}),
        ("pluck", {"string": 3, "profile": PROFILE}),
        ("release", {}),
        ("done", {"outcome": "completed", "reason": "fixture completed"}),
    ]
    # Use a shorter changed-note fixture so the failure is specifically neutral/rest between notes.
    from orchestration.scenarios import Scenario
    report = run(Scenario("two-note-change", ((5, 5), (3, 3))), Scripted(plan),
                 output_dir=tmp_path / "run", verbose=False)
    assert not report["evaluation"]["passed"]
    assert not report["evaluation"]["checks"]["no_unnecessary_fret_neutral_between_notes"]
    assert [e["tool"] for e in report["evaluation"]["unnecessary_fret_neutral_between_notes"]] == ["release", "rest"]


def test_alternative_valid_approach_is_not_marked_wrong(tmp_path):
    plan = complete_steps()
    plan.insert(1, ("hover", {"string": 5, "fret": 5}))
    plan.insert(2, ("touch", {"string": 5, "fret": 5}))
    report = run(SCENARIOS["repeat-and-change"], Scripted(plan), output_dir=tmp_path / "run", verbose=False)
    assert report["evaluation"]["passed"]


def test_model_claim_does_not_count_as_task_completion(tmp_path):
    report = run(SCENARIOS["single-note"], Scripted([("done", {"outcome": "completed", "reason": "I played it"})]),
                 output_dir=tmp_path / "run", verbose=False)
    assert not report["evaluation"]["passed"]
    assert not report["evaluation"]["checks"]["note_sequence_matches"]


def test_call_budget_checked_before_next_request(tmp_path):
    report = run(SCENARIOS["single-note"], Scripted(complete_steps()),
                 output_dir=tmp_path / "run", max_calls=1, verbose=False)
    assert report["stop_reason"] == "tool_budget_exhausted"
    assert report["model_requests"] == 1
    assert report["evaluation"]["tool_calls"] == 1
    assert not report["evaluation"]["passed"]


def test_expired_response_not_dispatched(tmp_path):
    class Slow(Scripted):
        def begin(self, *args, **kw):
            wall[0] += 2
            return self.next()
    wall = [0.0]
    report = run(SCENARIOS["single-note"], Slow(complete_steps()), output_dir=tmp_path / "run",
                 seconds=1, wall_clock=lambda: wall[0], verbose=False)
    assert report["stop_reason"] == "expired_model_response"
    assert report["evaluation"]["tool_calls"] == 0


def test_expected_fault_is_distinguished_from_bad_model_workflow(tmp_path):
    plan = [("press", {"string": 5, "fret": 5, "profile": PROFILE}),
            ("done", {"outcome": "blocked", "reason": "Fault requires review"})]
    report = run(SCENARIOS["fret-failure"], Scripted(plan), output_dir=tmp_path / "run", verbose=False)
    assert report["evaluation"]["passed"]
    assert report["evaluation"]["rejections"] == 1
    assert report["evaluation"]["unexpected_rejections"] == 0


def test_no_retry_after_fault_is_part_of_grading(tmp_path):
    plan = [("press", {"string": 5, "fret": 5, "profile": PROFILE})] * 2
    plan.append(("done", {"outcome": "blocked", "reason": "Fault requires review"}))
    report = run(SCENARIOS["fret-failure"], Scripted(plan), output_dir=tmp_path / "run", verbose=False)
    assert not report["evaluation"]["passed"]
    assert not report["evaluation"]["checks"]["no_motion_attempt_after_fault"]


def test_provider_quota_error_is_incomplete_not_a_coordination_failure(tmp_path):
    from model.baseten import BasetenRequestError
    class Limited(Scripted):
        def begin(self, *args, **kwargs):
            raise BasetenRequestError("Baseten HTTP 429", status_code=429)
    report = run(SCENARIOS["single-note"], Limited([]), output_dir=tmp_path / "run", verbose=False)
    assert report["evaluation"]["status"] == "incomplete"
    assert report["evaluation"]["tool_calls"] == 0
    assert report["model_requests"] == 1


def test_pacer_spaces_requests_and_respects_deadline():
    from orchestration.runner import RequestPacer
    wall = [0.0]
    def sleep(seconds):
        wall[0] += seconds
    pacer = RequestPacer(6, clock=lambda: wall[0], sleep=sleep)
    assert pacer.wait(20)
    assert wall[0] == 0
    assert pacer.wait(20)
    assert wall[0] == 6
    assert not pacer.wait(10)
    assert wall[0] == 6


def test_runner_and_native_backend_do_not_import_device_libraries():
    source = """
import orchestration.runner
import agent.backends.baseten
import sys
assert not any(m in sys.modules for m in ['serial','sounddevice','cv2','lerobot_robot_astra','sense.mic','sense.camera'])
"""
    subprocess.run([sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[1], check=True)
