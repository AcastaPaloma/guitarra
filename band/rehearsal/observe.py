"""Read-only telemetry and optional macOS camera capture; never writes motors.

HTTP timestamps bracket requests on the observer's monotonic clock. They are
not encoder capture timestamps. Camera PTS and stderr receipt times are saved
separately: neither establishes photon-to-frame or sound-to-sample latency.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import threading
import time
import urllib.request


def get_json(base: str, path: str) -> dict:
    before = time.monotonic_ns()
    wall = time.time_ns()
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=2) as response:
            payload = json.load(response)
        return {"request_mono_ns": before, "request_wall_ns": wall,
                "received_mono_ns": time.monotonic_ns(), "path": path,
                "response": payload}
    except Exception as exc:
        return {"request_mono_ns": before, "request_wall_ns": wall,
                "received_mono_ns": time.monotonic_ns(), "path": path,
                "error": f"{type(exc).__name__}: {exc}"}


def camera_result(progress: Path, returncode: int) -> dict:
    counts = [int(line.partition("=")[2]) for line in progress.read_text().splitlines()
              if line.startswith("frame=")] if progress.exists() else []
    frames = counts[-1] if counts else 0
    return {"camera_exit_code": returncode, "camera_encoded_frames": frames,
            "camera_capture_failed": returncode != 0 or frames < 2}


def observe(base: str, output: Path, seconds: float, ffmpeg: str | None,
            camera: str = "0:none") -> dict:
    if isinstance(seconds, bool) or not math.isfinite(seconds) or not 1 <= seconds <= 120:
        raise ValueError("Recording duration must be 1–120 seconds")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic_ns()
    manifest = {"schema_version": 1, "started_mono_ns": started,
                "started_wall_ns": time.time_ns(), "duration_requested_s": seconds,
                "clock": "observer time.monotonic_ns", "camera_device": camera,
                "camera_mirrored": None, "mirroring_note": "Verify the selected camera visually for each setup",
                "camera_latency_s": None, "audio_latency_s": None,
                "encoder_capture_time_available": False,
                "motion_commands_sent": 0, "camera_requested": bool(ffmpeg)}
    snapshots = {"before": [get_json(base, p) for p in (
        "/api/animations/status", "/api/motors/positions",
        "/api/audio/output-devices", "/api/perception/status")]}
    process = None
    reader = None
    if ffmpeg:
        command = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-copyts", "-start_at_zero",
                   "-progress", str(output / "camera-progress.txt"), "-f", "avfoundation",
                   "-framerate", "30", "-video_size", "1280x720", "-pixel_format", "uyvy422",
                   "-i", camera, "-t", str(seconds), "-vf", "showinfo",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                   "-pix_fmt", "yuv420p", str(output / "camera.mkv")]
        manifest["camera_process_started_mono_ns"] = time.monotonic_ns()
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, text=True)
        except OSError as error:
            manifest.update(camera_capture_failed=True, camera_start_error=type(error).__name__)

        def read_camera_log():
            with (output / "camera-log.jsonl").open("w") as log:
                for line in process.stderr:
                    log.write(json.dumps({"received_mono_ns": time.monotonic_ns(),
                                          "ffmpeg": line.rstrip()}) + "\n")
        if process:
            reader = threading.Thread(target=read_camera_log)
            reader.start()
    sample_start = time.monotonic()
    samples = 0
    failed = 0
    try:
        with (output / "telemetry.jsonl").open("w") as log:
            while time.monotonic() - sample_start < seconds:
                item = get_json(base, "/api/motors/positions")
                log.write(json.dumps(item) + "\n")
                log.flush()
                samples += 1
                failed += int("error" in item)
                # A missed sample is not replayed in a catch-up burst.
                time.sleep(0.1)
    finally:
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                manifest["camera_terminated_after_timeout"] = True
            reader.join(timeout=3)
            manifest.update(camera_result(output / "camera-progress.txt", process.returncode))
        snapshots["after"] = [get_json(base, p) for p in (
            "/api/animations/status", "/api/motors/positions")]
        manifest.update(ended_mono_ns=time.monotonic_ns(), samples=samples,
                        failed_samples=failed, camera_verified=False)
        (output / "status.json").write_text(json.dumps(snapshots, indent=2) + "\n")
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--camera", default="0:none")
    args = parser.parse_args()
    result = observe(args.base_url, args.output, args.seconds, args.ffmpeg, args.camera)
    print(json.dumps(result, indent=2))
    if result.get("camera_capture_failed") or result["failed_samples"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
