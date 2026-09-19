import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from band.rehearsal.recorded import recorded_probe


class RecordedProbeTests(unittest.TestCase):
    def setUp(self):
        self.stage = patch("band.rehearsal.recorded.StageEnvelope")
        self.build = patch("band.rehearsal.recorded.build_probe", return_value=Mock(duration_seconds=25))
        # Preserve real manifest reads; only the stage path is synthetic.
        self.stage.start()
        self.build.start()
        self.addCleanup(self.stage.stop)
        self.addCleanup(self.build.stop)

    def test_recorder_is_reaped_after_motion_success_or_fault(self):
        for fault in (None, RuntimeError("motion fault")):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                stage = Path(directory) / "stage.json"
                stage.write_text("{}")
                process = Mock(returncode=0)

                def start(*args, **kwargs):
                    recording = output / "recording"
                    recording.mkdir()
                    (recording / "live.jpg").write_bytes(b"frame")
                    (recording / "manifest.json").write_text(json.dumps({
                        "camera_capture_failed": False, "camera_encoded_frames": 1350,
                    }))
                    return process

                with patch("band.rehearsal.recorded.subprocess.Popen", side_effect=start), \
                     patch("band.rehearsal.recorded.run_probe", side_effect=fault, return_value={"status": "done"}):
                    if fault:
                        with self.assertRaisesRegex(RuntimeError, "motion fault"):
                            recorded_probe(stage, "small", output, "http://localhost", "fixture", "ffmpeg")
                    else:
                        result = recorded_probe(stage, "small", output, "http://localhost", "fixture", "ffmpeg")
                        self.assertEqual(result["status"], "done")
                process.wait.assert_called_once_with(timeout=55)

    def test_camera_start_failure_never_submits_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "stage.json"
            stage.write_text("{}")
            process = Mock(returncode=1)
            process.poll.return_value = 1
            with patch("band.rehearsal.recorded.subprocess.Popen", return_value=process), \
                 patch("band.rehearsal.recorded.run_probe") as probe:
                with self.assertRaisesRegex(RuntimeError, "No fresh external camera"):
                    recorded_probe(stage, "small", Path(directory) / "run", "http://localhost", "fixture", "ffmpeg")
                probe.assert_not_called()
                process.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
