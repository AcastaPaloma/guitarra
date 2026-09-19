from pathlib import Path
import tempfile
import unittest

from band.rehearsal.observe import camera_result


class CaptureTests(unittest.TestCase):
    def test_exit_zero_with_no_encoded_frames_is_a_failed_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = Path(directory) / "progress"
            self.assertTrue(camera_result(progress, 0)["camera_capture_failed"])
            progress.write_text("frame=0\nprogress=end\n")
            self.assertTrue(camera_result(progress, 0)["camera_capture_failed"])
            progress.write_text("frame=1\nprogress=continue\nframe=360\nprogress=end\n")
            self.assertFalse(camera_result(progress, 0)["camera_capture_failed"])
            self.assertTrue(camera_result(progress, 1)["camera_capture_failed"])
