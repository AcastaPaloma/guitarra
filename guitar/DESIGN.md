# Current guitar design — pretrained agents, bounded rehearsal

**This document owns the current guitar requirements.** [STATUS.md](STATUS.md) records
implementation evidence; [../AGENTS.md](../AGENTS.md) owns operator/gripper instructions.
Historical painting, single-arm open-G, π0.5, and lamp/band designs are not this build plan.

## 1. The product

Use the **same physical two-arm guitar rig** with defined, qualified fret/press, release,
and pluck tools. The agent chooses musical actions and revises its next attempt from
observations. It does not discover unrestricted motor control from scratch.

```text
Goal + supported capabilities + current state + attempt history
                            |
                            v
                 Pretrained planner on a verified endpoint
                            |
                            v
             Local validation + motion/timing compilation
                            |
                            v
                  Same fret arm + same pick arm
                            |
                 +----------+----------+
                 |                     |
           Motor telemetry      Optional consented recording
                 |                     |
                 |              Pretrained audio evaluator
                 |                     |
                 +------> next planner observation
```

Start with a short playable phrase and pauses between attempts. Do not require arbitrary
chords, all frets, a full song, or a new robot policy before one qualified note/phrase works.
The model may construct a sequence from available notes; it need not be restricted to a
menu of prewritten songs. Local code rejects physically infeasible arrangements.

## 2. What “self-tuning” means

The planner can change an approved phrase, choose a qualified playing/timing profile,
request inspection, or pause. Include previous outcomes in the next request and save a
best validated plan explicitly if it should persist across sessions.

This is **closed-loop rehearsal / in-context adaptation**, not neural-weight fine-tuning.
A pretrained evaluator can assess recordings without a new classifier-training project.
No H100 training job, LoRA adapter, simulated acoustic reward, or physical RL is needed
for this loop. [FINETUNING.md](FINETUNING.md) is deferred research only.

Do not promise every attempt improves. Use a consistent evaluation rubric, preserve
uncertainty, and report actual comparisons and interventions. An audio model's explanation
is not a definitive mechanical diagnosis or exact millisecond measurement.

## 3. Roles and authority

| Role | Owns | Does not own |
|---|---|---|
| Planner | Proposed note/phrase choices and permitted adjustments | Motor angles, arbitrary via-points, calibration, grip settings, safety limits |
| Audio evaluator | Assessment of a real clip against the intended phrase, with uncertainty | Tool execution or physical fault diagnosis as certainty |
| Local compiler/scheduler | Feasibility, approved paths/profiles, numeric timing, arm resource ordering | Invented acoustic success or silent tempo changes |
| Local controller/operator | Execution, current readiness, stop/thermal behavior, physical qualification | Waiting on a model before respecting a fault/protection condition |

The evaluator may share a model with the planner only if that exact endpoint supports and
passes the required combined-input tests. Otherwise use a separate audio-capable endpoint.
The current Qwen2.5-VL deployment scaffold is image/text, not a raw-audio evaluator.

## 4. Baseten and other providers

Baseten is the intended product inference platform. Use actual Baseten request/deployment
evidence for that claim. Existing Astra/Claude clients are alternative backends; their
requests do not demonstrate Baseten inference. No Baseten-hosted Astra endpoint is assumed.

A dedicated pretrained deployment or hosted Model API can implement a model role. Choose
by capability, measured behavior, access, and budget—not because an old default exists.
Dedicated inference may use a GPU without any fine-tuning. The current Baseten client is
direct HTTP; the presence of OpenAI/Anthropic packages for other backends is not provider routing.
See [model/README.md](model/README.md) for the actual scaffold and unresolved server contract.

## 5. Local execution rules

- Use the same verified hardware mapping; do not reset IDs, change wiring, or replace arms
  to fit an old example. Existing poses and interpolated targets still need qualification.
- Keep the grippers clamped during normal operation; `release()` lifts the fingertip.
  Thermal/electrical emergencies override grip retention. Follow `AGENTS.md` exactly.
- Keep numerical scheduling off the cloud path. Compile a whole phrase with fret preparation
  before picking; reject infeasible timing or ask for an explicitly approved slowdown.
- Avoid unnecessary rest/re-press actions, but preserve necessary lift/clearance/pick reset
  and bounded holding time. The present fret code already avoids mandatory global rest.
- Validate current state/calibration, action availability, path constraints, request expiry,
  duplicates, and recovery/attempt budgets locally. These are requirements, not all currently
  implemented protections; consult `STATUS.md`.
- Await models only from a qualified quiescent state; do not leave a press or hazardous hold
  active indefinitely while a network request runs. Do not equate that with automatic homing.
- Never silently replay motion after a fault or uncertain execution. Stop behavior is local
  and independent; generic “Ctrl-C → rest” is not an emergency-stop design.

## 6. Inputs, observations, and evidence

Camera snapshots/short clips and optional audio capture require consent and fresh timestamps.
Current code sends snapshots and a local acoustic summary, not continuous audio/video to
an omni model. Adding an external audio evaluator is a separate integration task, not a
fine-tune. Bad/missing capture should produce uncertainty, not an assumed missed pluck.

Keep mechanical telemetry, local audio estimates, model assessments, and operator judgments
separate. Fake-arm behavior and rendered audio are not physical latency/note-quality labels.
Detailed requirements are in [sensing](sense/README.md) and [rehearsal](REHEARSAL_LOOP.md).

## 7. Immediate implementation priorities

1. Resolve the current hardware configuration/protection blockers with the operator; do not
   run unattended attempts. Offline software work can proceed in parallel.
2. Finish/test the model endpoint contract with non-motion requests, then fake tool execution.
3. Qualify the missing physical pick/fret/transition subset and implement local coordination.
4. Add bounded attempt recording, one verified audio-evaluation path if enabled, history,
   and reviewed plan revision. No training pipeline is required.
5. Improve state reuse and timing using real telemetry and deterministic planning.
6. Only reconsider weight training after a measured failure/benefit hypothesis and an
   explicitly approved separate experiment.

No source-code or hardware behavior changes are implied by a documentation update.
