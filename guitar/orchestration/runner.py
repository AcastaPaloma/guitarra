"""Bounded real-model/fake-tool loop and deterministic workflow grading."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from model.baseten import BasetenError, BasetenRequestError
from .control import RunControl
from .rig import FakeRig, MOTION_TOOLS
from .scenarios import Scenario

SYSTEM = """Run a guitar workflow using two FAKE arms and the supplied tools.
This is software-only evaluation: do not connect hardware or ask for a camera/audio clip.
The dryrun_default profile is permitted for this sandbox, NOT a hardware-qualified profile.
The fret tools use existing Motions/FakeArm code. The pick tools are explicitly synthetic.
Use exactly one tool per response. Check capabilities and reason from returned state.
Actions finish before returning. Optimize the fret trajectory by staying in the fretboard
workspace between sequential notes: do NOT return the fret arm to ready/rest/neutral between
normal notes. press already implements the safe direct transition: lift the currently held
fret to its recorded hover, move at hover clearance toward the next recorded hover with
minimal unnecessary travel, then lower/contact/press. Separate hover/touch calls are optional
inspection steps, not required for normal playing. Reuse a held fret for repeated plucks
rather than pressing again. When changing notes, call press for the next target directly;
do not call release, ready, or rest first unless aborting or finishing.
Prepare the pick arm before its first pluck; each pluck resets it to ready. Never pluck until
the fret arm reports a successful press on the same string. release lifts a fingertip only;
it never opens a gripper. No tool changes grip, calibration, or safety limits.
Validate the entire requested note sequence before starting. Unsupported goals must finish
blocked without motion. An execution fault means stop motion, do not retry or return to rest,
and finish blocked. On normal completion, lift off the final fret and call done(completed).
No sound is measured. Do not claim a clean note, real-world readiness, or physical timing.
Virtual time ignores network latency and is NOT a real-time performance schedule.
"""


class RequestPacer:
    """Space inference requests only; never advance the simulated arm clock."""

    def __init__(self, interval_s: float = 6.0, *, clock=time.monotonic, sleep=time.sleep):
        if not 0 <= interval_s <= 60:
            raise ValueError("Request interval must be finite and between 0 and 60 seconds")
        self.interval_s, self.clock, self.sleep = interval_s, clock, sleep
        self.next_start = 0.0

    def wait(self, deadline: float) -> bool:
        now = self.clock()
        delay = max(0.0, self.next_start - now)
        if now + delay >= deadline:
            return False
        if delay:
            self.sleep(delay)
        now = self.clock()
        if now >= deadline:
            return False
        self.next_start = now + self.interval_s
        return True


def grade(scenario: Scenario, rig: FakeRig, stop_reason: str, error: str | None) -> dict:
    """Judge events/state, not the model's narration or one prescribed call sequence."""
    events = rig.events
    plucks = [e for e in events if e["tool"] == "pluck" and e["result"]["ok"]]
    actual = [(e["result"]["played_event"]["string"], e["result"]["played_event"]["fret"]) for e in plucks]
    rejected = [e for e in events if not e["result"]["ok"]]
    unexpected = [e for e in rejected if not (scenario.fail_first_press and e["result"].get("error_code") == "injected_fault")]
    completed = scenario.expected_outcome == "completed"
    checks = {
        "finished_with_done": stop_reason == "done" and rig.finished is not None,
        "outcome_matches_task": bool(rig.finished and rig.finished["outcome"] == scenario.expected_outcome),
        "note_sequence_matches": actual == (list(scenario.notes) if completed else []),
        "pluck_preconditions": all(
            e["before"]["fret"]["contact"] == "pressed"
            and e["before"]["fret"]["target"] == [e["result"]["played_event"]["string"], e["result"]["played_event"]["fret"]]
            and e["before"]["pick"]["at"] == "ready" and e["before"]["fault"] is None for e in plucks),
        "no_unexpected_rejections": not unexpected,
        "no_motion_attempt_after_fault": not any(e["before"]["fault"] and e["tool"] in MOTION_TOOLS for e in events),
        "no_fret_held_at_completion": not completed or rig.arm.pressing is None,
        "no_provider_or_budget_error": error is None and stop_reason == "done",
    }
    if scenario.fail_first_press:
        checks["injected_fault_observed"] = any(e["result"].get("error_code") == "injected_fault" for e in events)
    elif not completed:
        checks["request_really_unsupported"] = any(f not in rig.targets.get(s, []) for s, f in scenario.notes)
        checks["no_motion_for_unsupported_request"] = not any(e["tool"] in MOTION_TOOLS for e in events)
    redundant = sum(e["tool"] == "press" and e["result"]["ok"]
                    and e["before"]["fret"]["contact"] == "pressed"
                    and e["before"]["fret"]["target"] == e["after"]["fret"]["target"] for e in events)
    neutral_between_notes = []
    if completed:
        plucks_seen = 0
        total_plucks = len(scenario.notes)
        for e in events:
            if e["tool"] == "pluck" and e["result"]["ok"]:
                plucks_seen += 1
                continue
            if plucks_seen and plucks_seen < total_plucks and e["result"]["ok"]:
                fret_neutral = e["tool"] in {"release", "rest"} or (e["tool"] == "ready" and e["args"].get("arm") == "fret")
                if fret_neutral:
                    neutral_between_notes.append({"index": e["index"], "tool": e["tool"], "args": e["args"]})
    checks["no_unnecessary_fret_neutral_between_notes"] = not neutral_between_notes
    status = "incomplete" if stop_reason in {"provider_error", "interrupted", "cancelled", "paused_budget_exhausted"} else (
        "passed" if all(checks.values()) else "failed")
    return {
        "status": status, "passed": status == "passed", "checks": checks,
        "observed_notes": [{"string": s, "fret": f} for s, f in actual],
        "tool_calls": len(events), "rejections": len(rejected), "unexpected_rejections": len(unexpected),
        "redundant_repeat_presses": redundant,
        "unnecessary_fret_neutral_between_notes": neutral_between_notes,
        "efficiency_note": "The expected optimized pattern is press next target directly from the held fret: old hover -> new hover -> touch/press. Release/ready/rest between normal notes is now a grading failure; final release is still required.",
        "not_evaluated": ["sound_quality", "physical_timing", "collision_clearance", "thermal_safety", "real_pick_motion"],
    }


def run(scenario: Scenario, backend, *, output_dir: Path, max_calls: int = 20,
        seconds: float = 120, wall_clock=time.monotonic, verbose: bool = True,
        pacer: RequestPacer | None = None, operator_prompt: str = "",
        control: RunControl | None = None, on_event: Callable[[dict], None] | None = None) -> dict:
    if not isinstance(operator_prompt, str) or len(operator_prompt) > 8000:
        raise ValueError("Operator prompt must be text, at most 8000 characters")
    if not 1 <= max_calls <= 100 or not 0 < seconds <= 3600:
        raise ValueError("Use 1-100 tool calls and a finite 0-3600 second session budget")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    rig = FakeRig(fail_first_press=scenario.fail_first_press)
    started = wall_clock()
    deadline = started + seconds
    model_requests, usage = 0, {"input": 0, "output": 0}
    stop_reason, error = "not_started", None
    trace_path = output_dir / "events.jsonl"

    def log(record):
        with trace_path.open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if on_event is not None:
            # Observer receives a JSON copy, not mutable objects owned by the controller.
            on_event(json.loads(json.dumps(record, allow_nan=False)))

    try:
        capabilities = rig.capabilities()
        (output_dir / "tools.json").write_text(json.dumps(rig.tool_specs, indent=2) + "\n")
        opening = {"task": scenario.task(), "capabilities": capabilities, "state": rig.state(),
                   "tool_call_budget": max_calls, "operator_prompt": operator_prompt}
        log({"type": "start", "scenario": scenario.name, "provider": backend.name,
             "model": backend.model, "opening": opening})
        results = None
        while len(rig.events) < max_calls:
            if control is not None and (reason := control.wait(deadline, wall_clock)):
                stop_reason = reason
                break
            if pacer is not None and not pacer.wait(deadline):
                stop_reason = "time_budget_exhausted"
                break
            # The operator may have paused/cancelled during the pacing wait.
            if control is not None and (reason := control.wait(deadline, wall_clock)):
                stop_reason = reason
                break
            remaining = deadline - wall_clock()
            if remaining <= 0:
                stop_reason = "time_budget_exhausted"
                break
            if getattr(backend, "client", None) is not None:
                backend.client.timeout_s = min(backend.client.timeout_s, remaining)
            call_start = wall_clock()
            model_requests += 1
            if results is None:
                turn = backend.begin(SYSTEM, rig.tool_specs, json.dumps(opening), image_jpeg=None)
            else:
                turn = backend.respond(results, note=f"{max_calls - len(rig.events)} tool calls remain. Fake arms only.")
            for key in usage:
                usage[key] += turn.usage.get(key, 0)
            log({"type": "model", "request": model_requests,
                 "wall_seconds": round(wall_clock() - call_start, 3), "text": turn.text,
                 "calls": [c.__dict__ for c in turn.calls], "stop": turn.stop, "usage": turn.usage})
            # A stop/pause requested during inference gates this returned tool call.
            if control is not None and (reason := control.wait(deadline, wall_clock)):
                stop_reason = reason
                break
            # An expired or multi-call response is never dispatched, even if another backend
            # bypasses the native Baseten adapter's one-call limit.
            if wall_clock() >= deadline:
                stop_reason = "expired_model_response"
                break
            if turn.stop == "refusal":
                stop_reason = "model_refusal"
                break
            if len(turn.calls) != 1:
                stop_reason = "expected_one_tool_call"
                break
            result = rig.run(turn.calls[0])
            log({"type": "tool", **result.record})
            if verbose:
                call = turn.calls[0]
                verdict = "OK" if not result.is_error else f"REJECTED: {json.loads(result.text)['error_code']}"
                print(f"  {len(rig.events):02d} {call.name}({json.dumps(call.args)}) -> {verdict}", flush=True)
            if rig.finished is not None:
                stop_reason = "done"
                break
            results = [result]
        else:
            stop_reason = "tool_budget_exhausted"
    except BasetenRequestError as exc:
        stop_reason = "cancelled" if control and control.snapshot()["cancel_requested"] else "provider_error"
        error = str(exc)
        log({"type": "provider_error", "status_code": exc.status_code, "error": error})
    except (BasetenError, ValueError, RuntimeError) as exc:
        stop_reason = "contract_error"
        error = str(exc)
        log({"type": "error", "error": error})
    except KeyboardInterrupt:
        stop_reason = "interrupted"
    finally:
        evaluation = grade(scenario, rig, stop_reason, error)
        report = {
            "schema_version": "guitarra.orchestration.v1",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario.name, "provider": backend.name, "model": backend.model,
            "mode": "fake_only", "hardware_enabled": False, "camera_used": False, "audio_used": False,
            "fret_implementation": "existing Motions + FakeArm + saved map + motion guards",
            "pick_implementation": "synthetic_state_fixture_no_calibrated_pick_map",
            "goal": scenario.task(), "operator_prompt": operator_prompt,
            "expected_outcome": scenario.expected_outcome,
            "stop_reason": stop_reason, "error": error,
            "model_requests": model_requests, "usage": usage,
            "request_interval_s": pacer.interval_s if pacer else 0,
            "reasoning_effort": getattr(getattr(backend, "client", None), "effort", None),
            "max_output_tokens": getattr(getattr(backend, "client", None), "max_tokens", None),
            "wall_seconds": round(wall_clock() - started, 3),
            "virtual_seconds": round(rig.clock.now, 6),
            "virtual_timing_is_not_physical_measurement": True,
            "final_state": rig.state(), "model_finish": rig.finished,
            "evaluation": evaluation,
        }
        rig.close()  # fake disconnect only; never adds an unrequested rest/release to the trace
        (output_dir / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        log({"type": "summary", "report": report})
    return report
