#!/usr/bin/env python3
"""Managed Baseten Model API setup. No devices or tool execution, even in smoke.

Run from the repository root or guitar/: status, models, smoke --yes.
The earlier custom Qwen Truss deployment is no longer the active path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.baseten import (  # noqa: E402
    BasetenError, DEFAULT_MODEL, INFERENCE_URL, api_key, load_env, request_json,
)


def status(_: argparse.Namespace) -> None:
    load_env()
    print("Baseten managed Model API (not a dedicated Truss deployment)")
    print(f"  api_key: {'present' if os.environ.get('BASETEN_API_KEY') or os.environ.get('BASETEN') else 'missing'}")
    print(f"  model: {os.environ.get('BASETEN_MODEL') or DEFAULT_MODEL}")
    print(f"  endpoint: {INFERENCE_URL}/chat/completions")
    print(f"  reasoning_effort: {os.environ.get('BASETEN_REASONING_EFFORT') or 'high'}")
    print("  deployment_id: not needed (model is already hosted by Baseten)")
    print("  camera: off by default; audio capture: not started")


def models(args: argparse.Namespace) -> None:
    data = request_json(f"{INFERENCE_URL}/models", key=api_key(), timeout_s=30)
    needle = args.filter.lower()
    for model in data.get("data", []):
        if needle in model.get("id", "").lower():
            print(json.dumps({k: model.get(k) for k in (
                "id", "name", "context_length", "max_completion_tokens", "supported_features",
                "input_modalities", "output_modalities", "pricing",
            )}, indent=2))


def smoke(args: argparse.Namespace) -> None:
    if not args.yes:
        raise ValueError("Use --yes to allow two billed synthetic inference requests (no devices)")
    from agent.backends.baseten import BasetenBackend
    from agent.protocol import ToolResult

    backend = BasetenBackend(model=args.model)
    specs = [{
        "name": "look",
        "description": "Read synthetic state only. No camera and no motion.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    }, {
        "name": "done", "description": "End this synthetic connection check.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string", "minLength": 1}},
                       "required": ["reason"], "additionalProperties": False},
    }]
    started = time.monotonic()
    first = backend.begin(
        "Synthetic connection check. No robot, camera, microphone, or real audio is connected. "
        "First call look exactly once. After its result, call done with a short reason. "
        "No physical action can or should be executed.", specs,
        "Check the supplied synthetic state, then finish. Do not infer sound quality.", None,
    )
    if len(first.calls) != 1 or first.calls[0].name != "look":
        raise BasetenError("Connection check expected look as the first tool call")
    # This is fabricated SOFTWARE state, not a hardware observation or dispatched tool.
    second = backend.respond([ToolResult(first.calls[0].id, json.dumps({
        "source": "synthetic_fixture", "arm": {"at": "ready", "connected": False},
        "audio": "unavailable", "camera": "disabled",
    }))], note="Synthetic state received; finish with done. No acoustic evidence is available.")
    if len(second.calls) != 1 or second.calls[0].name != "done":
        raise BasetenError("Connection check expected done after the synthetic result")
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "baseten", "model": backend.model,
        "endpoint": f"{INFERENCE_URL}/chat/completions",
        "kind": "synthetic_tool_round_trip", "ok": True,
        "tool_names": [first.calls[0].name, second.calls[0].name],
        "tool_arguments": [first.calls[0].args, second.calls[0].args],
        "elapsed_s": round(time.monotonic() - started, 2),
        "usage": [first.usage, second.usage],
        "hardware_connected": False, "camera_used": False, "audio_uploaded": False,
        "tool_dispatch": False,
    }
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)
    sub.add_parser("status", help="Show local configuration without credentials").set_defaults(func=status)
    listing = sub.add_parser("models", help="List Baseten's managed catalog, not private deployments")
    listing.add_argument("--filter", default="Kimi-K3")
    listing.set_defaults(func=models)
    check = sub.add_parser("smoke", help="Synthetic tool-call round trip; no robot or capture")
    check.add_argument("--yes", action="store_true", help="allow billed requests")
    check.add_argument("--model", help="Baseten managed model slug override")
    check.add_argument("--record", type=Path, help="save the non-secret connection-check result")
    check.set_defaults(func=smoke)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, BasetenError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
