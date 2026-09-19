# Guitar — same arms, model-guided rehearsal

Use the existing physical fret/pick arms and defined guitar tools. The current plan is
**rehearsal with fixed pretrained models**: propose an attempt, validate/execute locally,
optionally assess its recording with an audio model, and revise the next approved plan.
This is not weight fine-tuning or unrestricted autonomous motor discovery.

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
- The agent has model adapters and local camera/mic processing, but no completed pretrained
  audio-evaluator rehearsal integration. Baseten client/server/config code exists but
  still requires end-to-end deployment/inference validation.
- The current motion API does not always return to global rest between fret changes.

No new app code is copied from the old `astra-guitar` experiment as part of this plan.
Existing Guitarra source is described accurately and changed only through deliberate,
tested implementation work—not by treating documentation as proof that integration works.

## Start offline

From the repository root:

```bash
guitar/.venv/bin/python -m pytest guitar/tests/test_motions.py -q
```

Before any hardware use, follow [../AGENTS.md](../AGENTS.md). The recorded gripper thermal
incident, connection/default mismatch, and sustained-hold limits remain unresolved by docs.
A tiny turn budget does not make autonomous hardware use safe.

The [simulator](sim/README.md) and [transcriber](Note%20Transcriber/README.md) are reference
components only. Lamp/band work elsewhere in the repository is not a requirement for this
guitar-only effort.
