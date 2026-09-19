# Run Baseten inference against the guitar tools — fake arms only

**Working now:** Kimi K3 on Baseten chooses tools, receives their results, and continues a
stateful workflow. The four built-in cases passed in one live, paced batch. See
[evidence/baseten-workflows.json](evidence/baseten-workflows.json).

This is execution of software motion logic, not a model describing what it would do.
The fretting tools call the existing `motions.Motions` methods over `robot.arm.FakeArm`,
using the supplied map, interpolation, and guards. The pick side is explicitly a synthetic
state fixture because no calibrated pick map is supplied. No sound or physical motion is claimed.

## Web interface

Use the same runner through the [local operator console](../web/README.md):

```bash
# From guitar/:
.venv/bin/python -m web --port 8787
```

Open http://127.0.0.1:8787. Prompts, custom expected notes, presets, budgets, live state/traces,
cooperative pause/stop, and history/downloads are available. Hardware remains locked out.
Operator prompts are recorded as task context without replacing the fixed tool/safety policy.

## Run it

Your existing ignored `.env` supplies `BASETEN_API_KEY` and
`BASETEN_MODEL=moonshotai/Kimi-K3`. No new key, model deployment, or training is needed.

```bash
# From the repository root:
cd guitar

# No API call: list the supplied workflow cases.
.venv/bin/python -m orchestration --list

# Billed Baseten inference + fake tools; default case is repeat-and-change.
.venv/bin/python -m orchestration --allow-inference

# All four cases, with independent conversation and fake state for each.
.venv/bin/python -m orchestration --scenario all --allow-inference
```

**There is no hardware/port option.** Camera, microphone, and audio evaluator are not used
or imported. Do not use the legacy `agent.loop` hardware defaults for this milestone.
`--allow-inference` permits API spend only; it cannot enable a robot connection.

## Tools the LLM sees

| Tool | Execution |
|---|---|
| `available()` | Lists both arms' sandbox capabilities and the profile |
| `where()` | Returns both fake states and any latched fault |
| `ready(arm)` / `rest(arm)` | Existing fret `Motions` method; synthetic state transition for pick |
| `hover(string, fret)` | Calls `Motions.hover` using an internal spot-name conversion |
| `touch(string, fret)` | Calls `Motions.touch`; contact alone is not enough to pluck in this fixture |
| `press(string, fret, profile)` | Calls `Motions.press`; includes necessary lift/approach |
| `release()` | Calls `Motions.release`; lifts the fingertip, never opens a gripper |
| `move_to(pose)` | Calls `Motions.move_to` for an allowlisted saved fret pose |
| `pluck(string, profile)` | Synthetic pick cycle; requires pick-ready and a successful press on that string |
| `done(outcome, reason)` | Ends without unrequested motion/cleanup; normal completion requires the fret lifted |

The profile is `dryrun_default` (speed 0.3, press depth 1.0 in the fake map). Those values
are **sandbox parameters, not physically qualified settings**. The model cannot supply
arbitrary coordinates, speed/depth changes, grip settings, shell code, connections, or calibration.
There is no single tool per string: targets are structured `string`/`fret` fields.

## What the checks mean

| Case | Verified behavior in the recorded live batch |
|---|---|
| `single-note` | Prepare, press s5f5, pluck once, release, finish |
| `repeat-and-change` | Pluck s5f5 twice while reusing the held fret; change to s3f3; pluck; release |
| `unsupported-target` | Reject requested fret 12 without attempting motion |
| `fret-failure` | After injected uncertain press execution, stop without plucking/retrying/homing |

The checker compares actual synthetic pick events and arm state with the requested sequence.
It checks preconditions, unsupported actions, fault handling, completion and final release.
It does not trust the model saying “done” or require one exact sequence of approach calls.
Redundant same-target presses are reported separately from correctness.

Results are **passed**, **failed**, or **incomplete**. Provider access/rate-limit/connection
failures are incomplete, not evidence of poor model coordination. A malformed model tool
response, wrong sequence, unsafe attempted workflow, or exhausted tool budget is not a pass.

This first batch establishes these four workflows, not a general coordination success rate.
It does not evaluate acoustic quality, a real pick, collision clearance, force, thermal
behavior, physical settling, or precise musical timing.

## Timing, budgets, and rate limits

The virtual clock runs the existing fake command-grid/settling waits without sleeping in
real time. Pick preparation/rest each use an assumed 0.2 s; a mock stroke/reset uses 0.25 s.
**These are not measured servo or acoustic times.** Network waits do not advance fake-arm time.
This step-by-step cloud loop is for workflow evaluation, not a real-time performance scheduler.

The observed Baseten account quota for Kimi K3 was 15 requests/minute and 100,000 tokens/minute.
An initial unpaced batch hit HTTP 429. The runner now spaces request starts by 6 seconds
(across case boundaries) and uses a 4,096-token output/reasoning budget with high reasoning.
Other clients sharing the key can still consume the quota. On a provider failure the batch
stops without retries; wait/fix access before starting a fresh fake session.

Options include `--max-calls` (default 20), `--seconds` (default 120 per case),
`--request-interval`, `--max-output-tokens`, `--model`, and `--effort`. Budgets are checked
before requesting/dispatching; expired or multi-call responses are not executed. The HTTP
socket timeout is bounded by the remaining budget, but this is not a hard process watchdog.

## Records and implementation

Every run gets a new ignored folder under `guitar/runs/orchestration/`:

- `tools.json`: exact schemas supplied to the model.
- `events.jsonl`: task/capabilities, model text and calls, before/after state, acceptance/rejection.
- `summary.json`: deterministic checks, observed notes, usage, model, and separate wall/virtual time.

No keys, media, or private reasoning are written into these records. The versioned evidence
is a snapshot of the last complete live batch; the earlier rate-limited traces remain in `runs/`.

Runtime code lives here—not in a test folder:

- `rig.py`: tool registry, existing-motion adapter, fake pick state, virtual clock.
- `runner.py`: bounded inference loop, request pacing, trace logging and grading.
- `scenarios.py`: four initial tasks/fault fixtures.
- `__main__.py`: fake-only CLI.
- `control.py`: optional cooperative pause/cancel gates; never a hardware emergency stop.

`agent/protocol.py` now holds lightweight tool-message dataclasses, so the Baseten adapter
need not import microphone/camera/controller executors. `FakeArm` accepts an optional clock;
real arms still use the wall clock, with no connection/grip/protection setting changes.
Offline regression checks are in `guitar/tests/test_orchestration.py`.

**Audio work is parked.** The next useful extension is more user-selected phrase/state cases
or a locally scheduled whole-phrase plan—not enabling hardware via a flag on this runner.
Physical integration remains separate and subject to [AGENTS.md](../../AGENTS.md).
