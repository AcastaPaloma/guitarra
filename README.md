# Guitarra — current guitar work

**Same physical guitar arms. Defined guitar tools. Model-guided rehearsal before training.**
The planner proposes a supported attempt, local code validates and executes it, and optional
pretrained audio-model feedback helps the planner revise the next attempt. The changing
thing is the performance plan/context, **not the model weights**.

## Start here

1. [Current design and requirements](guitar/DESIGN.md) — the source of truth for guitar scope.
2. [Implementation status and gaps](guitar/STATUS.md) — what exists versus what still needs code.
3. [Setup](guitar/SETUP.md) — offline checks and distinct external-action gates.
4. [Closed-loop rehearsal](guitar/REHEARSAL_LOOP.md) — the intended no-fine-tuning feedback loop.
5. [Operator instructions](AGENTS.md) — authoritative gripper and thermal rules.

## Decisions that are settled

- Use the same two arms: one frets, one picks. No new performers or simulated band.
- Use qualified pluck/fret/release capabilities, not zero-shot discovery of arbitrary motion.
- Let the model propose music and approved adjustments; local code owns trajectories,
  precise timing, resource coordination, and stop/fault handling.
- Camera observations and optional recorded-audio evaluation inform rehearsal. A planner
  without audio support can consume a separate evaluator's assessment.
- Begin with fixed pretrained models and a small attempt budget. H100 training, LoRA,
  learned physics, and physical RL are **not requirements or current prerequisites**.
- Baseten is the intended product inference stack. Astra/Claude are explicit alternatives,
  not names for a model secretly served by Baseten. Verify actual endpoint capabilities.
- Prior repository material is reference/inspiration, not a requirement to preserve its
  software APIs, simulator, transcriber, or old Baseten experiment.

## Current status

Named-pose motion code, a fake arm, a single-role agent loop, local microphone heuristics,
camera snapshots, and a Baseten client/config scaffold exist. A qualified two-arm phrase
executor, bounded audio-evaluator rehearsal loop, and demonstrated Baseten deployment are
**not established by those pieces**. A Baseten server adapter was added during this review;
client/server code and configuration now exist, but live deployment/compatibility remain
unverified. See [status](guitar/STATUS.md) and [model integration](guitar/model/README.md).

The gripper thermal/configuration issue in `AGENTS.md` remains a hardware gate. Passing
software tests does not clear it. This documentation cleanup changes no runtime behavior.

## Offline motion checks

From this repository root, using the existing environment:

```bash
guitar/.venv/bin/python -m pytest guitar/tests/test_motions.py -q
```

This targeted suite uses fakes/mocks. Do not run hardware utilities, camera capture, live
model calls, or GPU deployment commands as ordinary setup tests.

## Detailed references

- [Callable motions](guitar/MOTIONS.md) and [hardware connections](guitar/CONNECT.md)
- [Local motion/timing planning](guitar/PLANNING.md)
- [Current agent behavior](guitar/agent/README.md)
- [Camera, capture, and audio evaluation](guitar/sense/README.md)
- [Fine-tuning: deferred, optional research](guitar/FINETUNING.md)

## Separate workstreams and historical material

The root [lamp/band architecture](ARCHITECTURE.md), [lamp brief](BILL_BRIEF.md), and
lamp teaching/dancing/rehearsal documents are preserved as a **separate workstream**.
They are not guitar requirements or instructions to introduce another performer.
The [simulator](guitar/sim/README.md) and [transcriber](guitar/Note%20Transcriber/README.md)
are reference tools, not active dependencies. Vendored asset/license documentation is
unchanged. Use the current guitar design and operator instructions when older text differs.
