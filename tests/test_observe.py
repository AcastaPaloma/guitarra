from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from band.rehearsal.observe import camera_result, capture_is_fresh


class CaptureTests(unittest.TestCase):
    def test_concurrent_frame_write_does_not_look_like_a_future_timestamp(self):
        clock = [100.0]
        path = Mock()

        def frame_written_during_stat():
            clock[0] += .001
            return SimpleNamespace(st_mtime=clock[0])

        path.stat.side_effect = frame_written_during_stat
        self.assertTrue(capture_is_fresh(path, wall_clock=lambda: clock[0]))

    def test_stale_missing_and_future_capture_still_stop_motion(self):
        path = Mock()
        for modified in (96.9, 100.1):
            path.stat.return_value = SimpleNamespace(st_mtime=modified)
            self.assertFalse(capture_is_fresh(path, wall_clock=lambda: 100))
        path.stat.side_effect = FileNotFoundError
        self.assertFalse(capture_is_fresh(path, wall_clock=lambda: 100))

    def test_exit_zero_with_no_encoded_frames_is_a_failed_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = Path(directory) / "progress"
            self.assertTrue(camera_result(progress, 0)["camera_capture_failed"])
            progress.write_text("frame=0\nprogress=end\n")
            self.assertTrue(camera_result(progress, 0)["camera_capture_failed"])
            progress.write_text("frame=1\nprogress=continue\nframe=360\nprogress=end\n")
            self.assertFalse(camera_result(progress, 0)["camera_capture_failed"])
            self.assertTrue(camera_result(progress, 1)["camera_capture_failed"])
