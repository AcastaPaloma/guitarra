"""Run Baseten inference against fake guitar tools. There is NO hardware mode.

From guitar/: .venv/bin/python -m orchestration --allow-inference
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="repeat-and-change")
    parser.add_argument("--list", action="store_true", help="show workflow fixtures; no API requests")
    parser.add_argument("--allow-inference", action="store_true", help="allow billed Baseten calls; tools STILL fake only")
    parser.add_argument("--model", help="override Baseten managed model slug; otherwise use .env/Kimi K3")
    parser.add_argument("--effort", choices=["none", "low", "high", "max"], help="reasoning override; default .env/high")
    parser.add_argument("--max-calls", type=int, default=20, help="strict per-scenario tool-call cap")
    parser.add_argument("--request-interval", type=float, default=6, help="seconds between request starts; default pacing for observed 15 RPM quota")
    parser.add_argument("--max-output-tokens", type=int, default=4096, help="output/reasoning budget for each short tool decision")
    parser.add_argument("--seconds", type=float, default=120, help="per-scenario wall budget; no expired response is dispatched")
    parser.add_argument("--output-root", type=Path, default=ROOT / "runs" / "orchestration")
    args = parser.parse_args()
    if args.list:
        for name, scenario in SCENARIOS.items():
            print(f"{name}: requested string/fret pairs {list(scenario.notes)}")
        return
    if not args.allow_inference:
        parser.error("Pass --allow-inference to use Baseten credits. There is no hardware option.")
    if (not 1 <= args.max_calls <= 100 or not 0 < args.seconds <= 3600
            or not 0 <= args.request_interval <= 60 or not 1 <= args.max_output_tokens <= 32768):
        parser.error("Use 1-100 calls, 0 < seconds <= 3600, 0-60 second pacing, and 1-32768 output tokens")

    from agent.backends.baseten import BasetenBackend
    from .runner import RequestPacer, run

    selected = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    passed = attempted = 0
    pacer = RequestPacer(args.request_interval)  # shared across cases; don't burst at case boundaries
    for name in selected:
        backend = BasetenBackend(model=args.model, effort=args.effort, max_tokens=args.max_output_tokens)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output = args.output_root / f"{timestamp}-{name}-{uuid4().hex[:6]}"
        print(f"\nBaseten {backend.model} | {name} | FAKE ARMS ONLY", flush=True)
        report = run(SCENARIOS[name], backend, output_dir=output,
                     max_calls=args.max_calls, seconds=args.seconds, pacer=pacer)
        ok = report["evaluation"]["passed"]
        passed += int(ok)
        attempted += 1
        print(f"{report['evaluation']['status'].upper()}: {report['evaluation']['tool_calls']} tool calls; "
              f"{report['wall_seconds']}s wall / {report['virtual_seconds']}s virtual")
        if not ok:
            if report["evaluation"]["status"] == "failed":
                print("Failed checks: " + ", ".join(k for k, v in report["evaluation"]["checks"].items() if not v))
            if report["error"]:
                print(report["error"])
        print(f"Trace: {output / 'events.jsonl'}\nReport: {output / 'summary.json'}", flush=True)
        if report["evaluation"]["status"] == "incomplete":
            print("Stopping this batch without retries. Resolve the provider issue or wait for quota before a fresh run.")
            break
    print(f"\n{passed}/{attempted} executed cases passed; {len(selected) - attempted} not started. "
          "Physical playing/timing were NOT evaluated.")
    if passed != len(selected):
        parser.exit(1)


if __name__ == "__main__":
    main()
