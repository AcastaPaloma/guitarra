import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from band.adapters.lamp.client import LampClient, LampError
from band.performance.primitives import JOINTS
from band.rehearsal.commission import HeldJointGuard


class FakeRuntime:
    """SDK HTTP shapes inspected at runtime source fe874862; no hardware."""
    def __init__(self):
        self.now = 100.0
        self.calls = []
        self.states = ["accepted", "running", "succeeded"]
        self.available = True
        self.fail_submit = False
        self.cancel_state = "canceled"
        self.completed = True
        self.session = "s1"
        self.telemetry = {"robot_id": "fixture", "calibration_id": "c1", "units": "normalized_m100_100",
                          "self_collision_check": True, "positions": dict.fromkeys(JOINTS, 0)}

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def action(self, state):
        return {"action_id": "a1", "state": state, "expired": False,
                "result": {"completed": self.completed, "collision_checked": True}}

    def transport(self, method, path, body, content_type):
        self.calls.append((method, path, body, content_type))
        if path == "/capabilities":
            return {"ok": True, "protocol_version": "lelamp.sdk.v1",
                    "capabilities": [{"name": "clip.play", "available": self.available}],
                    "resources": {key: {"available": True} for key in ("joints", "clips")}}
        if path == "/sessions":
            return {"ok": True, "session": {"session_id": self.session}}
        if path == "/joints":
            return {"ok": True, **copy.deepcopy(self.telemetry)}
        if path == "/actions":
            if self.fail_submit:
                raise OSError("lost response")
            return {"ok": True, "action": self.action("accepted")}
        if path.endswith("/cancel"):
            return {"ok": True, "action": self.action(self.cancel_state)}
        if path == "/actions/a1":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return {"ok": True, "action": self.action(state)}
        raise AssertionError((method, path))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = FakeRuntime()
        self.ledger = Path(self.directory.name) / "ledger.sqlite"
        self.client = self.make_client()
        self.client.connect()
        self.clip = {"id": "clip1", "robot_id": "fixture", "calibration_id": "c1"}

    def make_client(self):
        client = LampClient("http://127.0.0.1:18081", "test-only-token", self.ledger,
                            transport=self.runtime.transport, clock=self.runtime.clock, sleep=self.runtime.sleep)
        self.addCleanup(client.close)
        return client

    def play(self, key="trial1", clip=None, observation=None):
        return self.client.play_clip(clip or self.clip, observation or self.client.observe(), idempotency_key=key)

    def test_accepted_is_not_done_and_callback_preserves_states(self):
        self.assertEqual(self.play()["state"], "accepted")
        events = []
        result = self.client.wait("a1", on_update=lambda t, a: events.append((t, a["state"])))
        self.assertEqual([s for t, s in events], ["accepted", "running", "succeeded"])
        self.assertEqual(result["state"], "succeeded")
        submitted = json.loads(next(c[2] for c in self.runtime.calls if c[:2] == ("POST", "/actions")))
        self.assertEqual(submitted["payload"], {"clip_id": "clip1"})
        self.assertFalse(any(c[1].endswith("/cancel") for c in self.runtime.calls))

    def test_stale_delayed_wrong_identity_and_simulation_rejected(self):
        observation = self.client.observe()
        cases = [replace(observation, received_monotonic=97),
                 replace(observation, round_trip_seconds=1.1),
                 replace(observation, data={**observation.data, "calibration_id": "different"}),
                 replace(observation, data={**observation.data, "self_collision_check": False})]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(LampError):
                self.play(observation=value)
        with self.assertRaises(LampError):
            self.play(clip={**self.clip, "robot_id": "simulation"})
        self.assertFalse(any(c[:2] == ("POST", "/actions") for c in self.runtime.calls))

    def test_duplicate_same_payload_does_not_resubmit(self):
        self.play()
        self.play()
        self.assertEqual(sum(c[:2] == ("POST", "/actions") for c in self.runtime.calls), 1)
        with self.assertRaises(LampError):
            self.play(clip={**self.clip, "id": "different"})

    def test_key_cannot_replay_after_new_session(self):
        self.play()
        self.runtime.session = "s2"
        new_client = self.make_client()
        new_client.connect()
        with self.assertRaises(LampError):
            new_client.play_clip(self.clip, new_client.observe(), idempotency_key="trial1")

    def test_uncertain_submission_blocks_other_trials_but_same_key_can_retry(self):
        self.runtime.fail_submit = True
        with self.assertRaises(OSError):
            self.play()
        self.runtime.fail_submit = False
        with self.assertRaises(LampError):
            self.play(key="trial2")
        self.assertEqual(self.play()["state"], "accepted")

    def test_timeout_cancels_and_confirms_terminal_state(self):
        self.runtime.states = ["running"]
        self.play()
        with self.assertRaises(TimeoutError):
            self.client.wait("a1", timeout=0.25)
        self.assertIsNone(self.client._active)
        self.assertTrue(any(c[1].endswith("/cancel") for c in self.runtime.calls))
        self.assertFalse(any(b"system.stop" in (c[2] or b"") for c in self.runtime.calls))

    def test_held_joint_drift_cancels_through_sdk_without_torque_release(self):
        self.runtime.states = ["running"]
        guard = HeldJointGuard(self.runtime.telemetry["positions"])
        self.play()

        def observe_drift(timestamp, action):
            self.runtime.telemetry["positions"]["elbow_pitch"] += .4
            guard.check(self.client.observe().data["positions"])

        with self.assertRaisesRegex(RuntimeError, "Held elbow_pitch drift"):
            self.client.wait("a1", on_update=observe_drift)
        self.assertIsNone(self.client._active)
        self.assertEqual(sum(c[1].endswith("/cancel") for c in self.runtime.calls), 1)
        self.assertFalse(any(b"system.stop" in (c[2] or b"") for c in self.runtime.calls))

    def test_unconfirmed_cancellation_is_explicit_fault(self):
        self.runtime.states = ["running"]
        self.runtime.cancel_state = "running"
        self.play()
        with self.assertRaisesRegex(LampError, "could not be confirmed"):
            self.client.wait("a1", timeout=0.1)

    def test_terminal_failure_does_not_trigger_idle_or_torque_actions(self):
        for state in ("failed", "canceled", "rejected"):
            self.runtime.states = [state]
            with self.subTest(state=state), self.assertRaisesRegex(LampError, state):
                self.client.wait("a1")
        self.assertFalse(any(c[0] == "POST" and c[1] != "/sessions" for c in self.runtime.calls))

    def test_missing_completion_evidence_is_not_success(self):
        self.runtime.states = ["succeeded"]
        self.runtime.completed = False
        with self.assertRaisesRegex(LampError, "lacks"):
            self.client.wait("a1")

    def test_capability_and_telemetry_fail_closed(self):
        self.runtime.available = False
        new_client = self.make_client()
        with self.assertRaisesRegex(LampError, "unavailable"):
            new_client.connect()
        self.runtime.telemetry["positions"]["base_yaw"] = float("nan")
        with self.assertRaises(LampError):
            self.client.observe()

    def test_empty_token_and_nonlocal_cleartext_rejected(self):
        for url, token in (("http://127.0.0.1", ""), ("http://robot.local", "token")):
            with self.assertRaises(ValueError):
                LampClient(url, token, self.ledger)


if __name__ == "__main__":
    unittest.main()
