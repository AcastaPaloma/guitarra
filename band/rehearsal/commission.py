"""Small, supervised commissioning probes through the collision-checked SDK.

Unlike full-scene execution, a probe accepts an unverified device stage. It
never changes its planned baseline from feedback or widens completion limits.
Keep idle off and inspect a live clear view before explicitly running a probe.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import uuid

from band.adapters.lamp.client import LampClient
from band.performance.composer import StageEnvelope, compose
from band.performance.primitives import JOINTS, Primitive, Wave
from band.rehearsal.observe import capture_is_fresh, get_json


def require_held_runtime(base_url):
    """Read-only preflight; never stop another operator's motion implicitly."""
    snapshot = get_json(base_url, "/api/animations/status")
    state = snapshot.get("response", {})
    if ("error" in snapshot or state.get("playing") is not False
            or state.get("idle_playing") is not False or "current_idle" not in state
            or state["current_idle"] is not None):
        raise ValueError("Commissioning requires an idle-free held runtime; coordinate control first")
    return snapshot


def build_probe(stage, kind, joint=None):
    stage.validate()
    if stage.robot_id == "simulation":
        raise ValueError("Commissioning requires a device-specific stage")
    if kind not in ("small", "envelope", "joint", "showcase"):
        raise ValueError("Unknown commissioning probe")
    # This initial protocol is deliberately local to a pose. Larger envelopes
    # require a separately reviewed protocol, not an accidental file edit.
    if any(max(abs(v) for v in bounds) > 4 for bounds in stage.offset_limits.values()):
        raise ValueError("Initial commissioning probes are limited to four normalized units per axis")
    if kind == "showcase":
        if joint is not None:
            raise ValueError("Showcase uses all five calibrated joints")
        amplitudes = {j: min(-stage.offset_limits[j][0], stage.offset_limits[j][1], 3) for j in JOINTS}
        if any(a <= 0 for a in amplitudes.values()):
            raise ValueError("Showcase requires positive and negative offsets on every axis")
        primitives = [Primitive("settled_start", 4, {}, stage.envelope_id)]
        for name in JOINTS:
            a = amplitudes[name]
            primitives.append(Primitive(f"show_{name}", 12, {name: (
                (0, 0), (4, a), (8, -a), (12, 0),
            )}, stage.envelope_id))
        primitives.append(Primitive("gentle_wiggle", 24, {
            j: Wave(min(amplitudes[j], 2) * (-1 if j == "elbow_pitch" else 1),
                    8, phase, fade_beats=4)
            for j, phase in zip(JOINTS, (0, .5, 1, 1, .5))
        }, stage.envelope_id))
        primitives.append(Primitive("settled_end", 4, {}, stage.envelope_id))
        return compose(primitives, stage)
    if kind == "joint":
        if joint not in JOINTS:
            raise ValueError("Select one calibrated joint for an isolated probe")
        lo, hi = stage.offset_limits[joint]
        amplitude = min(-lo, hi)
        if amplitude <= 0:
            raise ValueError("Probe requires positive and negative offsets")
        # Slow rest-to-rest moves with 2.5-second plateaus in each direction.
        # All other authored targets stay at the original planned baseline.
        return compose([Primitive(f"joint_{joint}", 40, {joint: (
            (0, 0), (4, 0), (8, amplitude), (12, amplitude),
            (16, 0), (20, 0), (24, -amplitude), (28, -amplitude),
            (32, 0), (40, 0),
        )}, stage.envelope_id)], stage)
    if joint is not None:
        raise ValueError("Joint selection applies only to isolated probes")
    beats = 16 if kind == "small" else 32
    tracks = {}
    for joint, phase in zip(JOINTS, (0, .5, 1, 1, .5)):
        lo, hi = stage.offset_limits[joint]
        amplitude = min(-lo, hi, .6) if kind == "small" else min(-lo, hi)
        if amplitude <= 0:
            raise ValueError("Probe requires positive and negative offsets on every axis")
        if joint == "elbow_pitch":
            amplitude = -amplitude
        tracks[joint] = Wave(amplitude, 8, phase, fade_beats=4 if kind == "small" else 8)
    return compose([
        Primitive("settled_start", 4, {}, stage.envelope_id),
        Primitive(f"probe_{kind}", beats, tracks, stage.envelope_id),
        Primitive("settled_end", 4, {}, stage.envelope_id),
    ], stage)


def run_probe(stage_path, kind, output, base_url, token, camera_log, *, joint=None):
    stage = StageEnvelope(**json.loads(stage_path.read_text()))
    compiled = build_probe(stage, kind, joint)
    if not camera_log.is_file() or not capture_is_fresh(camera_log):
        raise ValueError("Start the external recorder and inspect its live view first")
    runtime_before = require_held_runtime(base_url)
    output.mkdir(parents=True, exist_ok=False)
    (output / "scene.csv").write_bytes(compiled.csv_bytes())
    (output / "stage.json").write_text(json.dumps(asdict(stage), indent=2) + "\n")
    result = {"kind": kind, "joint": joint, "planned_seconds": compiled.duration_seconds, "camera_log": str(camera_log),
              "started_wall_ns": time.time_ns(), "started_mono_ns": time.monotonic_ns(),
              "status": "preflight", "hardware_verified": False, "run_id": uuid.uuid4().hex}
    client = LampClient(base_url, token, output / "requests.sqlite")
    identifier = None
    try:
        with (output / "events.jsonl").open("w", buffering=1) as log:
            def record(kind, data):
                log.write(json.dumps({"mono_ns": time.monotonic_ns(), "wall_ns": time.time_ns(),
                                      "type": kind, "data": data}, allow_nan=False) + "\n")
            client.connect()
            record("runtime_before", runtime_before)
            record("before", asdict(client.observe()))
            clip = client.upload_scene(compiled, stage)
            record("validated", clip)
            action = client.play_clip(clip, client.observe(), idempotency_key=result["run_id"])
            identifier = action["action_id"]
            record("submitted", action)

            def update(timestamp, action):
                if not capture_is_fresh(camera_log):
                    raise RuntimeError("External recorder stopped updating")
                record("action", action)
                record("telemetry", asdict(client.observe()))

            result["action"] = client.wait(identifier, timeout=compiled.duration_seconds + 30, on_update=update)
            result["final_observation"] = asdict(client.observe())
            result["status"] = "executor_completed; camera and tracking review required"
    except BaseException as error:
        result.update(status="fault; hold and inspect", error_type=type(error).__name__)
        if identifier:
            try:
                result["cancellation_terminal_state"] = client.cancel(identifier)["state"]
            except Exception:
                result["cancellation_terminal_state"] = "unknown"
        raise
    finally:
        client.close()
        result["ended_mono_ns"] = time.monotonic_ns()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--kind", choices=("small", "envelope", "joint", "showcase"), required=True)
    parser.add_argument("--joint", choices=JOINTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--camera-log", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    args = parser.parse_args()
    token = os.environ.get("LELAMP_SDK_TOKEN", "")
    if not token:
        parser.error("LELAMP_SDK_TOKEN is required")
    result = run_probe(args.stage, args.kind, args.output, args.base_url, token, args.camera_log, joint=args.joint)
    print(json.dumps({key: result[key] for key in ("run_id", "status")}, indent=2))


if __name__ == "__main__":
    main()
