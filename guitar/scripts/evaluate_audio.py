#!/usr/bin/env python3
"""Inspect or explicitly upload ONE WAV for assessment. No devices or robot tools.

From repo root:
  guitar/.venv/bin/python guitar/scripts/evaluate_audio.py --wav clip.wav --inspect
  guitar/.venv/bin/python guitar/scripts/evaluate_audio.py --wav clip.wav \
    --attempt-id take-001 --expected 'Three A2 notes, one second apart' --allow-upload
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.audio import evaluate_file, prepare_clip  # noqa: E402
from model.baseten import BasetenError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, required=True, help="a selected PCM16 WAV, at most 60 seconds")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true", help="local validation/metadata only; no key or network")
    mode.add_argument("--allow-upload", action="store_true", help="consent to upload this clip and consume Baseten credits")
    parser.add_argument("--attempt-id", help="unique identifier for this recording, e.g. take-001")
    parser.add_argument("--expected", help="intended phrase/notes and timing, if known")
    parser.add_argument("--source", choices=["operator_recording", "synthetic_fixture"], default="operator_recording")
    parser.add_argument("--output", type=Path, help="new JSON report path; default: ignored guitar/runs/audio/<attempt-id>.json")
    args = parser.parse_args()
    if args.allow_upload and (not args.attempt_id or not args.expected):
        parser.error("--allow-upload also requires --attempt-id and --expected")
    try:
        if args.inspect:
            clip = prepare_clip(args.wav)
            print(json.dumps({"mode": "local_inspection", "uploaded": False, "clip": clip.metadata}, indent=2, allow_nan=False))
            return
        # Check ID before it can become part of a file path or request.
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.attempt_id):
            raise ValueError("Use a 1-64 character attempt ID: letters/digits/dots/underscores/hyphens")
        output = args.output or ROOT / "runs" / "audio" / f"{args.attempt_id}.json"
        if output.exists():
            raise ValueError("Output already exists; choose a new attempt ID or output path (no silent overwrite/retry)")
        output.parent.mkdir(parents=True, exist_ok=True)
        report = evaluate_file(args.wav, expected_phrase=args.expected, attempt_id=args.attempt_id,
                               source=args.source, allow_upload=True)
        with output.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps(report, indent=2, allow_nan=False))
        print(f"Report: {output}", file=sys.stderr)
        if report["status"] != "assessed":
            parser.exit(1, "Audio assessment unavailable; no score or motion was inferred.\n")
    except (ValueError, OSError, BasetenError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
