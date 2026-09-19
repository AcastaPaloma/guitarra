from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from band.performance.composer import StageEnvelope
from band.performance.primitives import JOINTS
from band.rehearsal.commission import build_probe, require_held_runtime
from band.rehearsal.runner import SIMULATION_STAGE


class CommissionTests(unittest.TestCase):
    def test_probe_requires_no_active_or_resumable_idle_motion(self):
        held = {"playing": False, "idle_playing": False, "current_idle": None}
        with patch("band.rehearsal.commission.get_json", return_value={"response": held}):
            require_held_runtime("http://localhost")
        for response in ({}, {**held, "playing": True}, {**held, "idle_playing": True},
                         {**held, "current_idle": "idle"}):
            with patch("band.rehearsal.commission.get_json", return_value={"response": response}):
                with self.assertRaises(ValueError):
                    require_held_runtime("http://localhost")

    def setUp(self):
        self.stage = replace(StageEnvelope(**json.loads(SIMULATION_STAGE.read_text())),
                             robot_id="fixture", calibration_id="fixture-only",
                             offset_limits={j: [-4, 4] for j in JOINTS})

    def test_probe_covers_each_axis_returns_to_fixed_baseline_and_respects_bounds(self):
        for kind, duration, limit in (("small", 15, .6), ("envelope", 25, 4)):
            result = build_probe(self.stage, kind)
            self.assertEqual(result.duration_seconds, duration)
            self.assertEqual(result.frames[0][1], self.stage.baseline)
            self.assertEqual(result.frames[-1][1], self.stage.baseline)
            for joint in JOINTS:
                values = [p[joint] for _, p in result.frames]
                self.assertGreater(max(values), .3)
                self.assertLess(min(values), -.3)
                self.assertTrue(all(-limit <= value <= limit for value in values))

    def test_initial_protocol_rejects_simulation_and_unreviewed_expansion(self):
        for stage in (replace(self.stage, robot_id="simulation"),
                      replace(self.stage, offset_limits={j: [-10, 10] for j in JOINTS})):
            with self.assertRaises(ValueError):
                build_probe(stage, "small")

    def test_isolated_probe_holds_other_axes_and_dwells_in_both_directions(self):
        for joint in JOINTS:
            result = build_probe(self.stage, "joint", joint)
            self.assertEqual(result.duration_seconds, 25)
            for timestamp, pose in result.frames:
                self.assertTrue(all(pose[j] == self.stage.baseline[j] for j in JOINTS if j != joint))
                if 5 <= timestamp <= 7.5:
                    self.assertAlmostEqual(pose[joint], 4)
                if 15 <= timestamp <= 17.5:
                    self.assertAlmostEqual(pose[joint], -4)
            self.assertEqual(result.frames[-1][1], self.stage.baseline)

    def test_joint_selection_is_required_and_cannot_change_coordinated_probes(self):
        for kind, joint in (("joint", None), ("joint", "servo6"), ("small", "base_yaw")):
            with self.assertRaises(ValueError):
                build_probe(self.stage, kind, joint)

    def test_showcase_demonstrates_each_axis_before_bounded_combined_wiggle(self):
        result = build_probe(self.stage, "showcase")
        self.assertEqual(result.duration_seconds, 57.5)
        for i, joint in enumerate(JOINTS):
            start = 2.5 + 7.5 * i
            frames = [pose for timestamp, pose in result.frames if start <= timestamp <= start + 7.5]
            self.assertGreater(max(p[joint] for p in frames), 2.9)
            self.assertLess(min(p[joint] for p in frames), -2.9)
            self.assertTrue(all(p[j] == 0 for p in frames for j in JOINTS if j != joint))
        self.assertEqual(result.frames[-1][1], self.stage.baseline)


if __name__ == "__main__":
    unittest.main()
