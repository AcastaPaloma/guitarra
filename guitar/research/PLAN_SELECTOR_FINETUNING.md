# Deferred research — symbolic plan-selector fine-tuning

> **Not the current implementation path.** Preserve this proposal for a separately approved
> experiment only. The active [design](../DESIGN.md) and [rehearsal loop](../REHEARSAL_LOOP.md)
> use fixed pretrained models and do not require a training job. Do not run the commands
> below as setup, a hackathon prerequisite, or autonomous hardware permission.
> **Guitar camera input is off by default.** This symbolic-plan research also has no
> camera-input requirement; optional `--camera` diagnostics do not change that scope.

No dataset/job or fine-tuned checkpoint is established by this document. The separate
Baseten client/config scaffold is covered by [current status](../STATUS.md), not by this
research proposal. Nothing here imports the other repository's prototype as application code.

**Research scope:** symbolic plan labels, the same arms, and defined guitar tools—not raw
video/audio training or simulated acoustic physics. [PLANNING.md](../PLANNING.md) owns
local motion planning. An optional pretrained audio evaluator in the active rehearsal loop
is compatible with this distinction: assessing sound is inference, not weight training.

## 1. What we accept from the proposed idea

**Good idea:** preserve useful arm state across notes, avoid unnecessary rest excursions,
plan ahead, and base timing on measurements of the actual mechanism.

**Not accepted as established facts:**

| Claim in the pasted proposal | Correct engineering interpretation |
|---|---|
| Fine-tuning makes an LLM a predictive neural physics engine | Only a measured prediction task and held-out evidence establish what was learned |
| State-dependent timing requires an LLM because one fixed delay fails | A transition table, motion model, feedback controller, or small regressor can be state-dependent too |
| The current system already uses IK/spline optimization | Inspected guitar code uses recorded poses, base-first segments, and joint-space interpolation |
| A solver snaps guesses into perfect safe paths | Geometric validity is not contact-force, timing, collision, or acoustic certainty |
| MuJoCo contact can label clean/buzzy guitar sounds accurately | That requires a validated contact/acoustic model; optional assessment of real audio clips does not establish simulator accuracy |
| Fine-tuning predicts exact 5–12 ms adjustments | Current sampling/telemetry does not support that precision; LLM-generated numbers are not measurements |
| Real-robot data collection necessarily breaks the rig, so simulation is mandatory | Small supervised trials within qualified limits can provide useful telemetry; random exploration is not appropriate |
| Randomized physics and a final 100 trials guarantee sim-to-real accuracy | Neither a sample count nor parameter jitter establishes validity on this rig |
| Multi-finger chord optimization matches this hardware | Only physically demonstrated capabilities may be used; two arms do not imply arbitrary chord fingering |

Do not reproduce the suggested sudden 10 cm step test, mass sweeps, or agent-selected
physical RL trials. See the thermal/gripper constraints in [operator instructions](../../AGENTS.md).

## 2. The narrow fine-tuning experiment, if we do one

Fine-tune a small open **text model to propose a symbolic phrase plan** from:

- Current named fret/pick states.
- The upcoming ordered notes, durations, and requested performance constraints.
- A versioned registry of approved transitions/profiles and their mechanical cost bounds.
- Explicit permissions, readiness, and bounded holding/resource constraints.

Output: a list of approved transition IDs, or an explicit infeasible/replan result.
**Not output:** raw joints, invented Cartesian via-points, new press depths, new grip limits,
physical contact claims, or millisecond timing guesses. Local code computes the schedule.

This is **planner imitation/distillation**, not a learned acoustic world model. It can
teach a model to propose stateful tool programs rather than repeatedly issuing a generic
reset sequence. It does not magically improve the underlying motor trajectories.

### Illustrative plan, not a runnable or approved hardware sequence

Suppose the fret arm is already holding A5, the pick is ready, and the next notes are
A5, A5, A7. If the registry explicitly permits a bounded same-fret hold, a teacher plan
could be:

```text
qualified pick cycle
qualified pick cycle
lift fingertip to A5 hover
qualified hover transition to A7
qualified press at A7
qualified pick cycle
```

This does not insert global rest between notes. It also does not skip the required lift
before changing frets or the pick reset contained in each cycle. Actual timings, maximum
hold duration, thermal constraints, resource ordering, and score feasibility remain local.
The supplied fret map has no pluck poses; this example is not a claim that the sequence
can currently run on both arms.

### Why training may not be worthwhile

For a small fixed graph, the deterministic planner can already return the best plan quickly.
A model trained on its answers cannot be claimed to outperform an exact optimum for that
same objective. It may also be slower, less reliable, and more expensive.

Use this only as a bounded experiment if model-based plan generation is useful to the
application. Compare against the deterministic planner, not just a deliberately poor
always-rest script. If code wins, use code. A Baseten training demonstration without a
measured task benefit must be labeled as such, not sold as better robotic intelligence.

## 3. Generate labels without building a guitar simulator

1. Define the finite transition graph and hard constraints with a local validator.
2. Make a deterministic planner solve short symbolic note sequences from different start
   states. Exhaustive search/dynamic programming may be sufficient at this scale.
3. Generate input/target pairs: state + score + permitted transitions → valid optimized plan.
4. Include infeasible scores, unavailable targets, exceeded hold limits, stale versions, and
   fault/disarmed states. Their correct label is rejection/replanning, not speculative motion.
5. Tag records as `synthetic_symbolic`; graph-cost estimates are not physical measurements.
6. If measured durations are available, record their provenance and uncertainty. Unknown
   or unqualified transitions remain unavailable regardless of generated training volume.

This is software constraint checking, not MuJoCo string physics or a simulated performer.
Generating more symbolic examples does not create additional physical evidence.

Keep the training prompt/schema identical to the intended inference interface. Prefer
ordinary JSON and the model's existing tokenizer; custom physical token vocabularies are
unnecessary for a first small experiment. Train on the target decision/program tokens,
not on invented explanations or hidden reasoning traces.

### Dataset record requirements

- Example ID, source (`synthetic_symbolic` or reviewed real episode), generator version.
- Rig/calibration/registry/cost-model versions and data split.
- Initial symbolic state, score/lookahead, available capabilities, and constraints.
- Teacher plan, deterministic validation result, and objective values with units.
- Explicit assumptions/uncertainty; no fictitious force or acoustic-success label.

For real episodes, inputs contain only facts available before planning. Later outcomes
may help evaluate/label the example but must not leak into its input.

Split by complete phrase/transition family and start state, with a frozen held-out set.
Do not put duplicates or neighboring slices from one run into both training and testing.
Retain tie-equivalent valid plans: textual equality is not the only measure of correctness.

## 4. Baseten training path

A small LoRA supervised fine-tune is the initial experiment; no RL/GRPO or raw video/audio
training. Baseten's documented Training Jobs quickstart uses **Qwen3-4B on one H100**.
That makes it a candidate starting recipe, not a guarantee of availability or improvement.

Planned files (none exists yet):

```text
guitar/planning/                # contracts, capability graph, validator, compiler, telemetry
guitar/training/build_dataset.py
guitar/training/train_lora.py
guitar/training/evaluate.py
guitar/training/config.py       # Baseten TrainingProject/TrainingJob + checkpointing
guitar/deploy/plan_selector/    # reviewed deployment config, after training succeeds
```

Sequence:

1. Confirm booth/workspace training access, credit coverage, and an explicit GPU-spend cap.
2. Finish the deterministic teacher/validator and freeze evaluation cases first.
3. Pick a compatible, license-reviewed small open checkpoint; pin data/model/runtime versions.
4. Run a tiny data-loader/schema smoke test before provisioning a full experiment.
5. Launch one capped H100 Training Job or use the approved workstation to debug the same code.
6. Keep most base weights frozen and train LoRA adapters using a supported trainer. Use
   short contexts/small batches and profile memory; do not inherit giant-context defaults.
7. Save under `$BT_CHECKPOINT_DIR` with checkpointing enabled. Verify sync completion before
   deleting/rotating local checkpoints; keep dataset/tokenizer/adapter metadata together.
8. Evaluate the selected checkpoint on frozen cases before any physical admission.
9. Generate/review the serving config, then deploy only with approved inference spend.
10. Stop idle training/serving resources; the H100 offer is not proof of free ongoing serving.

Commands documented by Baseten, **for use only after the planned files/access exist**:

```bash
# From guitarra/; this configuration file is not implemented yet.
baseten train push --config guitar/training/config.py
baseten train job logs --job-id <JOB_ID> --tail
baseten train checkpoint deploy --job-id <JOB_ID> --dry-run
```

The dry run writes a configuration for review; it is not a successful inference deployment.
The checkpoint-deployment shortcut applies to supported Hugging Face-compatible LLMs.
A separate numeric timing regressor would need its own small Truss serving implementation,
not vLLM pretending to serve a dynamics model.

Keep credentials in the shell/secret manager, not prompts or committed files. A trained
planner can be called directly with HTTPX; an OpenAI client is not required. Using Astra
as a teacher is optional and requires suitable model access/terms; deterministic labels
avoid needing proprietary teacher calls or claiming access to Astra weights.

## 5. Runtime boundary

```text
Score + current state + approved registry/cost bounds
                |
                v
Baseten-hosted plan selector (optional)
                |
                | untrusted symbolic plan
                v
Local schema/state/path/hold/resource/expiry validation
                |
                v
Local deterministic schedule and fully checked trajectory
                |
                v
Same physical arms -> motor telemetry only
```

Request whole phrases ahead of time. Model latency is outside the motor loop. The local
compiler supplies numeric timing and refuses infeasible schedules; a model cannot move
onsets to hide lateness. Check calibration/registry identity again before dispatch.

Invalid/late/unsupported output causes no new motion. Replanning may use the deterministic
planner only through the same fresh-state checks; an exception must not silently launch
a new phrase. Emergency/thermal/fault behavior remains independent of model/network/UI.

## 6. If the real problem is uncertain mechanical delays

That is a separate **system-identification** task, usually better served by a small numeric
model than an LLM. Inputs might be verified start/target joint positions or named states,
arm/base mode, approved speed profile, and available health/context measurements. Target:
observed mechanical settle-time interval or a residual over the deterministic estimate.

Start with a measured transition table and conservative margins. Test a small regression/
quantile model only if the table/general motion model has a demonstrated gap. Evaluate
underprediction, interval coverage, and changed-condition behavior on held-out sessions.
A point estimate is not a guarantee; local readiness and limits still apply.

Do not train it from fake-arm timing, the current rounded/partial `duration_s`, imaginary
12 ms latency labels, or unvalidated simulator contacts. Without physical telemetry there
is no empirical dynamics target. H100 compute is likely unnecessary for a small table/regressor;
do not inflate that task into a large-model fine-tune just to use a GPU.

## 7. Evaluation and stop conditions

Run the same frozen cases against:

| Baseline/candidate | Why it is included |
|---|---|
| Current controller routing | Already avoids global rest on ordinary fret-to-fret travel |
| New deterministic phrase planner | Strong baseline for stateful reuse and scheduling |
| Untuned open model with the same contract | Establish whether fine-tuning changes behavior |
| LoRA plan selector, if trained | Test improvement in valid/useful plan proposals, not claimed physics |

Report valid-plan rate, unsupported transitions, feasibility/hold/resource violations,
objective gap versus the teacher, rejection rate, full model latency, total validated-plan
latency, and cost. Then, only after operator qualification, report measured mechanical
execution against the same plan. Joint travel is a proxy, not energy; command time is not
acoustic onset. Symbolic/telemetry tests cannot support acoustic-quality claims. Any optional
rehearsal audio assessments must be reported separately with their uncertainty.

Stop or defer the training experiment if the deterministic planner is already sufficient,
the dataset only repeats a few templates, the GPU/serving setup exceeds its approved time/
spend budget, or held-out results show no useful gain. No reward may trade a safety/thermal
violation for a shorter path. Do not run online RL on the arms.

## 8. Sources and evidence limits

- [Local motion/timing audit and plan](../PLANNING.md), [motion API](../MOTIONS.md),
  [operator rules](../../AGENTS.md): actual repo interfaces and physical restrictions.
- [Baseten Training Jobs quickstart](https://docs.baseten.co/training/getting-started):
  single-H100 Qwen3-4B LoRA example; not a robotics result.
- [Train on your data](https://docs.baseten.co/training/your-own-data): custom dataset/job workflow.
- [Checkpoint persistence](https://docs.baseten.co/training/concepts/checkpoints):
  `$BT_CHECKPOINT_DIR`, sync, retention, and job-deletion cautions.
- [Serve checkpoints](https://docs.baseten.co/training/deployment): supported LLM deployment
  and configuration review; not proof a custom dynamics model is automatically supported.
- [Workstations](https://docs.baseten.co/reference/cli/baseten/train-workstation): interactive
  training access, subject to account entitlement and approval.

No timing measurements, dataset size, model accuracy, latency improvement, training result,
or physical safety qualification is claimed by this document.
