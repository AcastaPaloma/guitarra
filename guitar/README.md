# Guitar — same arms, model-guided rehearsal

Use the existing physical fret/pick arms and defined guitar tools. The current plan is
**rehearsal with fixed pretrained models**: propose an attempt, validate/execute locally,
optionally assess its recording with an audio model, and revise the next approved plan.
This is not weight fine-tuning or unrestricted autonomous motor discovery.

**Camera input is off by default.** The normal planner uses known poses/arm state and
available audio feedback, not images. `--camera` explicitly opts into optional diagnostic
snapshots from a separately started relay. `--no-camera` remains an explicit off switch.
A vision-capable planner is not required.

## Local web app

The operator console is available at **http://127.0.0.1:8787** when the local server is running.
Edit prompts and note sequences, run Baseten, watch fake tool/state traces, pause/resume/stop,
and inspect/download previous runs. **There is no hardware mode.**

```bash
# From the repository root:
(cd guitar && .venv/bin/python -m web --port 8787)
```

See [web/README.md](web/README.md) for startup, controls, logs, and the real-arm commissioning
blockers. A real Baseten workflow through the browser UI has passed; that is not physical qualification.

## Run the current milestone: Baseten + fake tools

Real Kimi K3 inference now drives the existing fretting motion code on a fake arm plus an
explicitly synthetic pick arm. The initial four workflow cases passed live. **No hardware,
camera, microphone, or audio evaluator is used.** Audio integration is parked for now.

```bash
cd guitar
.venv/bin/python -m orchestration --allow-inference
```

See [orchestration/README.md](orchestration/README.md) for scenarios, logs, and the
fake/physical boundary. This is workflow evaluation, not real-time guitar performance.

## Read in this order

1. [Current design](DESIGN.md) — authoritative scope and roles.
2. [Status and remaining gaps](STATUS.md) — source facts, not assumed completion.
3. [Setup](SETUP.md) — offline work and explicit hardware/inference gates.
4. [Rehearsal loop](REHEARSAL_LOOP.md) — feedback, attempt budget, and saved plans.
5. [Callable motions](MOTIONS.md) and [connections](CONNECT.md) — actual interface and operator checks.

Additional details: [motion planning](PLANNING.md), [sensing](sense/README.md),
[agent implementation](agent/README.md), [Baseten integration](model/README.md), and
[deferred fine-tuning](FINETUNING.md).

## What is available now

- `motions.py` exposes saved ready/rest, hover, touch, press, release, and conditional pluck
  operations. **Its default is a fake arm/test double, not a physics simulation.**
- The supplied map has fret targets but no pluck poses; it does not establish a working
  two-arm performance. Saved/interpolated poses are not blanket hardware approval.
- The agent has model adapters, local mic processing, and camera support that stays off unless
  explicitly enabled. Prompts/specs report active inputs; `look()` is state-only by default.
  The pretrained audio-evaluator rehearsal integration is not completed. Baseten's managed Kimi K3
  planner now passes a live synthetic tool-call round trip; see [model setup](model/README.md).
  The [orchestration runner](orchestration/README.md) additionally executes fake tool workflows
  through that planner. Neither result is a dedicated deployment or physical rehearsal validation.
- The current motion API does not always return to global rest between fret changes.

No new app code is copied from the old `astra-guitar` experiment as part of this plan.
Existing Guitarra source is described accurately and changed only through deliberate,
tested implementation work—not by treating documentation as proof that integration works.

## Start offline

From the repository root:

```bash
guitar/.venv/bin/python -m pytest guitar/tests/test_camera_opt_in.py guitar/tests/test_motions.py -q
```

Before any hardware use, follow [../AGENTS.md](../AGENTS.md). The recorded gripper thermal
incident, connection/default mismatch, and sustained-hold limits remain unresolved by docs.
A tiny turn budget does not make autonomous hardware use safe.

The [simulator](sim/README.md) and [transcriber](Note%20Transcriber/README.md) are reference
components only. Lamp/band work elsewhere in the repository is not a requirement for this
guitar-only effort.
