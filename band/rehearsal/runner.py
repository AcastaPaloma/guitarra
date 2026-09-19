"""Reproducible offline scene compiler. This command cannot command hardware.

The beat track starts at musical zero. Existing SDK clip.play adds a runtime
entry BEFORE that zero. No synchronized hardware/audio start is implemented.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import struct
import wave

from band.performance.composer import StageEnvelope, compose
from band.performance.primitives import continuous_dance, scene

PROFILES = Path(__file__).parents[1] / "performance" / "profiles"
SIMULATION_STAGE = Path(__file__).parent / "stages" / "simulation.json"


def beat_track(path, beats, bpm):
    """A low-level deterministic tick; playback is an explicit operator step."""
    rate = 24000
    samples = bytearray(round(beats * 60 / bpm * rate) * 2)
    for beat in range(beats):
        start = round(beat * 60 / bpm * rate)
        frequency = 880 if beat % 4 == 0 else 440
        for i in range(round(rate * 0.04)):
            if (start + i) * 2 >= len(samples):
                break
            amplitude = 0.12 * (1 - i / (rate * 0.04))
            value = round(32767 * amplitude * math.sin(2 * math.pi * frequency * i / rate))
            struct.pack_into("<h", samples, (start + i) * 2, value)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(samples)


def build(output: Path, preset: str, stage_path: Path, bpm=96.0, support_scale=None, head_phase_beats=None):
    if preset not in ("restrained", "accented", "continuous"):
        raise ValueError("Unknown rehearsal preset")
    # JSON is the YAML 1.2 subset used for these profiles; no unsafe loader.
    profile = json.loads((PROFILES / f"{preset}.yaml").read_text())
    if preset == "continuous" and (support_scale is not None or head_phase_beats is not None):
        raise ValueError("Continuous dance uses its explicit five-axis profile")
    if support_scale is not None:
        profile["support_scale"] = support_scale
    if head_phase_beats is not None:
        profile["head_phase_beats"] = head_phase_beats
    stage = StageEnvelope(**json.loads(stage_path.read_text()))
    primitives = (continuous_dance(profile, stage.envelope_id) if preset == "continuous"
                  else scene(profile, stage.envelope_id, stage.partner_sign, stage.bow_sign))
    compiled = compose(primitives, stage, bpm)
    output.mkdir(parents=True, exist_ok=False)
    csv_data = compiled.csv_bytes()
    (output / "scene.csv").write_bytes(csv_data)
    beat_track(output / "beat.wav", 64, bpm)
    manifest = {"schema_version": 1, "status": "offline candidate; physical verification pending",
                "preset": profile, "stage": asdict(stage), "bpm": bpm,
                "frames": len(compiled.frames), "duration_seconds": compiled.duration_seconds,
                "trajectory_sha256": hashlib.sha256(csv_data).hexdigest(),
                "camera_reference": None, "hardware_runs": 0,
                "musical_zero": "after runtime entry; actual start must be measured",
                "landmarks": compiled.landmarks,
                "guitar_cues": [{"seconds": 20, "type": "guitar.prepare_solo", "simulated": True},
                                {"seconds": 22.5, "type": "guitar.solo_start", "simulated": True},
                                {"seconds": 32.5, "type": "guitar.solo_end", "simulated": True}],
                "singing": "not implemented", "audience_detection": "simulated"}
    # Cues follow the tempo, rather than assuming the default 96 BPM.
    for cue, beat in zip(manifest["guitar_cues"], (32, 36, 52)):
        cue["seconds"] = beat * 60 / bpm
    if preset == "continuous":
        manifest["guitar_cues"] = []
        manifest["phrase_markers"] = [
            {"beat": beat, "seconds": beat * 60 / bpm, "motion_reset": False}
            for beat in range(8, 64, 8)
        ]
        manifest["required_entry_mode"] = "held"
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("restrained", "accented", "continuous"), required=True)
    parser.add_argument("--stage", type=Path, default=SIMULATION_STAGE)
    parser.add_argument("--bpm", type=float, default=96)
    parser.add_argument("--support-scale", type=float,
                        help="One-factor comparison: change only the solo support amplitude")
    parser.add_argument("--head-phase-beats", type=float,
                        help="One-factor comparison: change only the body/head phase parameter")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output, args.preset, args.stage, args.bpm, args.support_scale, args.head_phase_beats)
    print(json.dumps({key: result[key] for key in ("status", "frames", "duration_seconds", "trajectory_sha256")}, indent=2))


if __name__ == "__main__":
    main()
