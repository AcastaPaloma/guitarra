import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from band.performance.composer import StageEnvelope, compose
from band.performance.primitives import JOINTS, continuous_dance
from band.rehearsal.execute import load_scene
from band.rehearsal.runner import PROFILES, SIMULATION_STAGE, build


class ContinuousDanceTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((PROFILES / "continuous.yaml").read_text())
        self.stage = StageEnvelope(**json.loads(SIMULATION_STAGE.read_text()))

    def test_all_five_axes_move_with_no_internal_whole_body_stops(self):
        compiled = compose(continuous_dance(self.profile, self.stage.envelope_id), self.stage)
        self.assertEqual(compiled.duration_seconds, 40)
        self.assertEqual(len(compiled.landmarks), 1)
        self.assertEqual(compiled.frames[0][1], self.stage.baseline)
        self.assertEqual(compiled.frames[-1][1], self.stage.baseline)
        for joint in JOINTS:
            values = [p[joint] - self.stage.baseline[joint] for _, p in compiled.frames]
            amplitude = self.profile["axes"][joint]["amplitude"]
            self.assertGreater(max(values), amplitude * .99)
            self.assertLess(min(values), -amplitude * .99)
        # This is a no-pause regression, not a sampled safety-bound proof.
        # Analytic continuous bounds remain enforced by compose().
        for (t0, a), (t1, b) in zip(compiled.frames, compiled.frames[1:]):
            if 5 <= t0 < t1 <= 35:
                speed = math.sqrt(sum(((b[j] - a[j]) / (t1 - t0)) ** 2 for j in JOINTS))
                self.assertGreater(speed, 1.)

    def test_amplitude_expansion_still_rejected_by_stage_bounds(self):
        profile = copy.deepcopy(self.profile)
        profile["axes"]["base_yaw"]["amplitude"] = 100
        with self.assertRaises(ValueError):
            compose(continuous_dance(profile, self.stage.envelope_id), self.stage)

    def test_offline_scene_is_repeatable_and_cannot_execute_without_commissioning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = build(root / "a", "continuous", SIMULATION_STAGE)
            b = build(root / "b", "continuous", SIMULATION_STAGE)
            self.assertEqual(a["trajectory_sha256"], b["trajectory_sha256"])
            self.assertEqual(a["required_entry_mode"], "held")
            self.assertEqual(a["guitar_cues"], [])
            self.assertTrue(all(not marker["motion_reset"] for marker in a["phrase_markers"]))
            with self.assertRaises(ValueError):
                load_scene(root / "a")

    def test_verified_fixture_recomposes_and_rejects_missing_entry_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = json.loads(SIMULATION_STAGE.read_text())
            data.update(robot_id="fixture-only", calibration_id="fixture-only", hardware_verified=True,
                        verification_runs=["unit-fixture-not-hardware"])
            stage = root / "stage.json"
            stage.write_text(json.dumps(data))
            build(root / "scene", "continuous", stage)
            load_scene(root / "scene")
            path = root / "scene" / "manifest.json"
            manifest = json.loads(path.read_text())
            del manifest["required_entry_mode"]
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "held-entry"):
                load_scene(root / "scene")

    def test_missing_joint_and_nonfinite_profile_rejected(self):
        for fault in ("missing", "nan"):
            profile = copy.deepcopy(self.profile)
            if fault == "missing": del profile["axes"]["elbow_pitch"]
            else: profile["axes"]["elbow_pitch"]["amplitude"] = float("nan")
            with self.assertRaises(ValueError):
                continuous_dance(profile, self.stage.envelope_id)
