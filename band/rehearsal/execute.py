"""Execute a device-specific compiled scene through the authenticated SDK.

For supervised trials only: establish the stage envelope, clear the workspace,
coordinate exclusive control, and start the external recorder first. This
does not synchronize music, suppress other controllers, or certify tracking.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from band.adapters.lamp.client import LampClient
from band.performance.composer import StageEnvelope, compose
from band.performance.primitives import scene
from band.rehearsal.observe import capture_is_fresh


def load_scene(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported rehearsal manifest")
    stage = StageEnvelope(**manifest["stage"])
    stage.validate()
    if stage.robot_id == "simulation" or stage.calibration_id == "not-a-device-calibration":
        raise ValueError("Simulation poses cannot be executed on hardware; commission a device-specific stage first")
    if not stage.hardware_verified:
        raise ValueError("A full rehearsal requires a stage envelope verified by prior small physical trials")
    compiled = compose(scene(manifest["preset"], stage.envelope_id, stage.partner_sign, stage.bow_sign),
                       stage, manifest["bpm"])
    stored = (directory / "scene.csv").read_bytes()
    if compiled.csv_bytes() != stored or hashlib.sha256(stored).hexdigest() != manifest["trajectory_sha256"]:
        raise ValueError("Scene content or compiler version changed; rebuild and review before executing")
    return manifest, stage, compiled


def execute(directory, output, base_url, token, camera_reference):
    manifest, stage, compiled = load_scene(directory)
    if not camera_reference.is_file():
        raise ValueError("Supply the live recorder's camera-log.jsonl for this trial")
    # Receipt logs are appended during capture; this checks recorder liveness,
    # not physical clearance, field of view, or capture latency.
    if not capture_is_fresh(camera_reference):
        raise ValueError("External camera log is stale; start the recorder and inspect its live view")
    output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    result = {"run_id": run_id, "started_wall_ns": time.time_ns(), "started_mono_ns": time.monotonic_ns(),
              "camera_reference": str(camera_reference.resolve()), "source_manifest": manifest,
              "status": "preflight", "musical_zero_measured": False,
              "audio_playback": "none; synchronization pending", "hardware_verified": False}
    client = LampClient(base_url, token, output / "requests.sqlite")
    identifier = None
    try:
        with (output / "events.jsonl").open("w", buffering=1) as log:
            def event(kind, data):
                log.write(json.dumps({"mono_ns": time.monotonic_ns(), "wall_ns": time.time_ns(),
                                      "type": kind, "data": data}, allow_nan=False) + "\n")

            client.connect()
            before = client.observe()
            event("before", asdict(before))
            clip = client.upload_scene(compiled, stage)
            event("clip_validated", clip)
            action = client.play_clip(clip, client.observe(), idempotency_key=run_id)
            identifier = action["action_id"]
            result["action_id"] = action["action_id"]
            event("submitted", action)

            def update(timestamp, current):
                if not capture_is_fresh(camera_reference):
                    raise RuntimeError("External camera recorder stopped updating")
                event("action", current)
                event("telemetry", asdict(client.observe()))

            result["action"] = client.wait(action["action_id"], timeout=min(660, compiled.duration_seconds + 60),
                                           on_update=update)
            result["status"] = "executor_completed; external visual and tracking review required"
    except BaseException as error:
        result["status"] = "fault; no automatic movement restart"
        result["error_type"] = type(error).__name__
        if identifier:
            try:
                result["cancellation_terminal_state"] = client.cancel(identifier)["state"]
            except Exception:
                result["cancellation_terminal_state"] = "unknown; inspect runtime and hold"
        raise
    finally:
        client.close()
        result["ended_mono_ns"] = time.monotonic_ns()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--camera-log", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("LELAMP_SDK_TOKEN", "")
    if not token:
        parser.error("Set LELAMP_SDK_TOKEN securely in the environment; never pass it in a command argument")
    result = execute(args.scene, args.output, args.base_url, token, args.camera_log)
    print(json.dumps({key: result[key] for key in ("run_id", "status", "hardware_verified")}, indent=2))


if __name__ == "__main__":
    main()
