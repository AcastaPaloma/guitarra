import copy
import csv
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
import wave

from band.performance.composer import (DERIVATIVE_MAXIMA, EASE, StageEnvelope,
                                       compose, derivative, polynomial, wave_bounds, wave_value)
from band.performance.primitives import JOINTS, Primitive, Wave, scene
from band.rehearsal.runner import PROFILES, SIMULATION_STAGE, build
from band.rehearsal.execute import load_scene


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.stage = StageEnvelope(**json.loads(SIMULATION_STAGE.read_text()))
        self.profile = json.loads((PROFILES / "accented.yaml").read_text())

    def test_easing_boundaries_and_interior_derivative_extrema(self):
        coefficients = EASE
        self.assertEqual(polynomial(coefficients, 0), 0)
        self.assertEqual(polynomial(coefficients, 1), 1)
        for order in range(3):
            coefficients = derivative(coefficients)
            self.assertAlmostEqual(polynomial(coefficients, 0), 0)
            self.assertAlmostEqual(polynomial(coefficients, 1), 0)
            measured = max(abs(polynomial(coefficients, i / 10000)) for i in range(10001))
            self.assertLessEqual(measured, DERIVATIVE_MAXIMA[order] + 1e-8)
            self.assertAlmostEqual(measured, DERIVATIVE_MAXIMA[order], places=4)
        self.assertAlmostEqual(DERIVATIVE_MAXIMA[0], 2.1875)
        self.assertAlmostEqual(DERIVATIVE_MAXIMA[2], 52.5)

    def test_all_five_axes_move_in_both_groove_and_solo(self):
        primitives = scene(self.profile, self.stage.envelope_id, 1, 1)
        compiled = compose(primitives, self.stage)
        self.assertEqual(compiled.duration_seconds, 40)
        self.assertEqual([p["beat"] for p in compiled.landmarks], [0, 4, 8, 12, 28, 32, 36, 52, 56, 60])
        for start, end in ((7.5, 17.5), (22.5, 32.5)):
            for joint in JOINTS:
                values = [pose[joint] for time, pose in compiled.frames if start < time < end]
                self.assertGreater(max(values) - min(values), 0.1, joint)
        for time, pose in compiled.frames:
            for joint in JOINTS:
                lo, hi = self.stage.offset_limits[joint]
                self.assertTrue(lo <= pose[joint] <= hi)
        self.assertEqual(compiled.frames[0][1], compiled.frames[-1][1])

    def test_wave_has_curvature_at_turns_without_rest_knot_pause(self):
        wave_track = Wave(1, 4, fade_beats=4)
        # Beat 5 is a full-amplitude crest inside the steady part of the phrase.
        h = 0.001
        curvature = (wave_value(wave_track, 5+h, 16) - 2*wave_value(wave_track, 5, 16)
                     + wave_value(wave_track, 5-h, 16)) / h**2
        self.assertAlmostEqual(curvature, -(math.pi / 2)**2, places=5)
        for boundary in (0, 16):
            self.assertEqual(wave_value(wave_track, boundary, 16), 0)

    def test_wave_phase_and_waist_elbow_countermotion(self):
        groove = scene(self.profile, self.stage.envelope_id, 1, 1)[3]
        self.assertEqual(set(groove.joint_mask), set(JOINTS))
        self.assertGreater(groove.tracks["base_pitch"].amplitude, 0)
        self.assertLess(groove.tracks["elbow_pitch"].amplitude, 0)
        self.assertNotEqual(groove.tracks["base_pitch"].phase_beats, groove.tracks["elbow_pitch"].phase_beats)

    def test_invalid_tracks_and_stage_are_rejected(self):
        examples = [
            {"base_yaw": ((0, 1), (4, 0))},  # discontinuous entry
            {"base_yaw": ((0, 0), (2, 7), (4, 0))},
            {"base_yaw": ((0, 0), (0, 1), (4, 0))},
            {"base_yaw": ((0, 0), (4, float("nan")))},
            {"unknown": ((0, 0), (4, 0))},
            {"base_yaw": Wave(1, 0)},
            {"base_yaw": Wave(1, 4, fade_beats=0)},
            {"base_yaw": Wave(7, 4, fade_beats=2)},
        ]
        for tracks in examples:
            with self.subTest(tracks=tracks), self.assertRaises(ValueError):
                compose([Primitive("bad", 4, tracks, self.stage.envelope_id)], self.stage)
        with self.assertRaises(ValueError):
            replace(self.stage, partner_sign=True).validate()
        with self.assertRaises(ValueError):
            replace(self.stage, hardware_verified=True).validate()

    def test_tempo_and_derivative_violations_are_rejected_not_retimed(self):
        primitives = scene(self.profile, self.stage.envelope_id, 1, 1)
        with self.assertRaises(ValueError):
            compose(primitives, self.stage, bpm=240)
        dynamics = copy.deepcopy(self.stage.dynamics)
        dynamics["base_yaw"][2] = 0.01
        with self.assertRaises(ValueError):
            compose(primitives, replace(self.stage, dynamics=dynamics))
        # The bound includes ramp derivatives, not just the sinusoid's peak.
        bounds = wave_bounds(Wave(1, 4), 0.625)
        self.assertGreater(bounds[0], 2 * math.pi / 2.5)

    def test_unowned_joint_holds_planned_state(self):
        first = Primitive("look", 8, {"base_yaw": ((0, 0), (8, 2))}, self.stage.envelope_id)
        second = Primitive("hold", 4, {}, self.stage.envelope_id)
        result = compose([first, second], self.stage)
        self.assertTrue(all(pose["base_yaw"] == 2 for time, pose in result.frames if time >= 5))

    def test_csv_strict_times_and_musical_landmarks_at_noninteger_tempo(self):
        result = compose(scene(self.profile, self.stage.envelope_id, 1, 1), self.stage, bpm=97.3)
        rows = list(csv.DictReader(io.StringIO(result.csv_bytes().decode())))
        times = [float(row["timestamp"]) for row in rows]
        self.assertTrue(all(right > left for left, right in zip(times, times[1:])))
        for landmark in result.landmarks:
            self.assertLessEqual(min(abs(t-landmark["seconds"]) for t in times), 0.5e-9)

    def test_one_factor_comparison_and_repeatable_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = build(root / "a", "restrained", SIMULATION_STAGE)
            b = build(root / "b", "restrained", SIMULATION_STAGE)
            c = build(root / "c", "restrained", SIMULATION_STAGE, support_scale=1)
            self.assertEqual(a["trajectory_sha256"], b["trajectory_sha256"])
            self.assertEqual(a["landmarks"], c["landmarks"])
            rows_a = list(csv.DictReader(io.StringIO((root / "a/scene.csv").read_text())))
            rows_c = list(csv.DictReader(io.StringIO((root / "c/scene.csv").read_text())))
            changed = []
            for before, after in zip(rows_a, rows_c):
                if before != after:
                    changed.append(float(before["timestamp"]))
            self.assertTrue(changed)
            self.assertTrue(all(22.5 < t < 32.5 for t in changed))
            with wave.open(str(root / "a/beat.wav")) as audio:
                self.assertEqual(audio.getnframes() / audio.getframerate(), 40)
            self.assertEqual(a["hardware_runs"], 0)
            with self.assertRaisesRegex(ValueError, "Simulation poses"):
                load_scene(root / "a")
            with self.assertRaises(FileExistsError):
                build(root / "a", "restrained", SIMULATION_STAGE)

    def test_execute_loader_rejects_changed_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device_stage = json.loads(SIMULATION_STAGE.read_text())
            device_stage.update(robot_id="fixture", calibration_id="fixture-calibration",
                                hardware_verified=True, verification_runs=["unit-test-fixture-only"])
            stage_path = root / "stage.json"
            stage_path.write_text(json.dumps(device_stage))
            build(root / "trial", "restrained", stage_path)
            manifest, stage, compiled = load_scene(root / "trial")
            self.assertEqual(compiled.duration_seconds, 40)
            (root / "trial/scene.csv").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "content or compiler"):
                load_scene(root / "trial")

    def test_phase_comparison_changes_only_dance_intervals_and_preserves_yaw(self):
        a = copy.deepcopy(self.profile)
        a["head_phase_beats"] = 0
        before = compose(scene(a, self.stage.envelope_id, 1, 1), self.stage)
        after = compose(scene(self.profile, self.stage.envelope_id, 1, 1), self.stage)
        self.assertEqual(before.landmarks, after.landmarks)
        changed = 0
        for (ta, pa), (tb, pb) in zip(before.frames, after.frames):
            self.assertEqual(ta, tb)
            self.assertEqual(pa["base_yaw"], pb["base_yaw"])
            if pa != pb:
                changed += 1
                self.assertTrue(7.5 < ta < 17.5 or 22.5 < ta < 32.5)
        self.assertGreater(changed, 0)


if __name__ == "__main__":
    unittest.main()
