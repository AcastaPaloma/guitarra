"""Keep the external recorder alive through one supervised SDK probe.

Inspect the workspace immediately before invoking this command. A fresh frame
proves capture liveness, not clearance. Large media stays in the chosen folder.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from band.performance.primitives import JOINTS
from band.performance.composer import StageEnvelope
from band.rehearsal.commission import build_probe, run_probe
from band.rehearsal.observe import capture_is_fresh


def recorded_probe(stage, kind, output, base_url, token, ffmpeg, camera="0:none", joint=None, entry_mode="measured"):
    planned = build_probe(StageEnvelope(**json.loads(stage.read_text())), kind, joint)
    seconds = planned.duration_seconds + 20
    if seconds > 120:
        raise ValueError("Probe exceeds recorder duration limit")
    output.mkdir(parents=True, exist_ok=False)
    recording = output / "recording"
    with (output / "recorder.stdout").open("w") as log:
        process = subprocess.Popen([
            sys.executable, "-m", "band.rehearsal.observe", "--base-url", base_url,
            "--output", str(recording), "--seconds", str(seconds), "--ffmpeg", ffmpeg,
            "--camera", camera,
        ], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 12
            live = recording / "live.jpg"
            while not (live.is_file() and live.stat().st_size > 0
                       and capture_is_fresh(live, 2)):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("No fresh external camera frame; no motion submitted")
                time.sleep(.1)
            result = run_probe(stage, kind, output / "probe", base_url, token,
                               recording / "camera-log.jsonl", joint=joint, entry_mode=entry_mode)
        finally:
            # Never orphan the recorder: process cleanup by an invoking terminal
            # would otherwise truncate evidence while the robot keeps moving.
            try:
                process.wait(timeout=seconds + 10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if process.returncode:
            raise RuntimeError("Recorder failed; inspect saved motion result and capture logs")
        manifest = json.loads((recording / "manifest.json").read_text())
        if manifest.get("camera_capture_failed") or manifest.get("camera_encoded_frames", 0) < 2:
            raise RuntimeError("External recording is incomplete")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--kind", choices=("small", "envelope", "joint", "showcase", "dance"), required=True)
    parser.add_argument("--joint", choices=JOINTS)
    parser.add_argument("--entry-mode", choices=("measured", "held"), default="measured")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--camera", default="0:none")
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    args = parser.parse_args()
    token = os.environ.get("LELAMP_SDK_TOKEN", "")
    if not token:
        parser.error("LELAMP_SDK_TOKEN is required")
    result = recorded_probe(args.stage, args.kind, args.output, args.base_url, token,
                            args.ffmpeg, args.camera, args.joint, args.entry_mode)
    print(json.dumps({k: result[k] for k in ("run_id", "status")}))


if __name__ == "__main__":
    main()
