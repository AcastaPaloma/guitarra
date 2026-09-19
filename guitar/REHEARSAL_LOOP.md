# Closed-loop guitar rehearsal — improve attempts without fine-tuning

**Primary target design; not implemented or physically qualified by this documentation.**
[DESIGN.md](DESIGN.md) owns scope and [STATUS.md](STATUS.md) owns current implementation facts.
Same physical guitar arms. Default press/release/pluck capabilities stay locally guarded.
A planner revises a performance over a few attempts using optional pretrained audio-model
assessment and telemetry. **No model-weight training is required.**

**Camera input is off by default and is not a rehearsal input requirement.** The planner
uses the goal/score, known capabilities, arm state, and previous audio assessments. `look()`
is state-only. `--camera` is an explicit optional diagnostic; `--no-camera` keeps the default.
No vision-capable planner or background camera relay is required for the normal loop.

## 1. What changes between attempts

```text
Goal + intended phrase + current state + previous attempts
                        |
                        v
Planner LLM proposes a symbolic plan / qualified profile choice
                        |
                        v
Local validation + deterministic trajectory/schedule compilation
                        |
                        v
Same physical arms execute one bounded attempt
                        |
                        +--> motor telemetry
                        +--> optional consented audio recording
                                      |
                                      v
                        Pretrained audio evaluator
                                      |
                                      v
                  Bounded assessment with uncertainty
                                      |
                                      +--> planner revises the next attempt
```

The changing object is a **performance plan or approved profile selection**, not neural
weights. The planner gets previous outcomes in its context; successful plans can be saved
locally and explicitly loaded on the next session. An API session-affinity header is not
persistent model memory or fine-tuning.

## 2. Separate the roles

| Role | Responsibility | Not authorized to do |
|---|---|---|
| Planner | Propose notes/phrase structure or qualified profile changes from observations | Invent raw joints/via-points, bypass limits, alter motor configuration |
| Audio evaluator | Assess a recording against the supplied phrase/rubric and state uncertainty | Execute tools or claim acoustic evidence proves a mechanical cause |
| Local planner/compiler | Check the plan, choose qualified transitions, calculate timing, enforce resources | Silently move note onsets or reduce required clearance to make a bad plan fit |
| Local controller/operator | Execute, monitor readiness/health, handle stop/thermal faults | Wait for a cloud model to decide whether to respect a protection condition |

A text/state planner plus a separate audio-capable evaluator is sufficient; camera input
is not needed. The roles may share a model if its endpoint passes the required text/audio
workload. A vision-capable model does not automatically accept microphone audio, and ASR
is not automatically guitar evaluation. Test the selected inputs without adding a camera
as an unstated prerequisite.

For Baseten-centered product inference, use verified Baseten endpoints for the roles we
claim Baseten performs. Astra, if used via a different provider, must be labeled accurately;
there is no assumed Baseten-hosted Astra endpoint.

## 3. Minimum attempt loop

1. Select a short phrase that the qualified rig can play; record expected notes, rhythm,
   allowed profiles, and the local calibration/registry version.
2. Capture fresh controller state and obtain one bounded planner proposal.
3. Validate the entire phrase/path/schedule before motion. Reject stale, unsupported, or
   infeasible output; the model may propose an explicitly approved slower arrangement.
4. Execute locally and record intended/actual command and sampled arrival times separately.
5. If audio is enabled with consent, capture a short aligned clip around the attempt. Keep
   the device/timebase and recording quality attached; do not silently substitute old audio.
6. Ask the evaluator to compare the clip with the intended phrase, flag uncertainty, and
   report observations rather than instructions to change physical limits.
7. Present the assessment and telemetry to the planner. Change one supported variable at
   a time so the next attempt has an interpretable comparison.
8. Stop at the attempt/time budget, on uncertain/faulted state, repeated lack of improvement,
   or operator request. Save the best **validated** plan and its evidence, not just the last one.

Use a small explicit attempt budget, for example three attempts after operator qualification;
that is a proposed software cap, not authorization to run three physical trials now.
Inference happens between attempts or ahead of a future phrase, not per servo tick.

## 4. What useful feedback looks like

An illustrative assessment could say:

- The recording was usable / clipped / noisy / too quiet to judge.
- A particular expected attack may be missing, with an approximate segment reference.
- The sequence sounds less consistent than the previous attempt, with a short explanation.
- There is insufficient evidence to distinguish poor contact from a capture problem.

Do not require the evaluator to guess if evidence is unclear. Do not turn a fluent
explanation into a definitive diagnosis such as “increase press depth by 2 mm.” The planner
may select only already-qualified profiles or request operator inspection.

Use a fixed rubric and compare attempts under similar recording conditions. A model's
rating is an **assessment**, not calibrated ground truth. If precise note/pitch/onset
metrics are later needed, validate those separately; an audio model's estimated timestamp
is not proof of a 5 ms improvement. Operator listening can corroborate outcomes but must
be labeled as human review.

## 5. What the planner may change

Initially allow a small set: supported note/phrase choices, a qualified conservative timing
profile, an approved pick/fret profile, repeat/inspect/pause, or a state-preserving plan that
passes [the motion planner](PLANNING.md).

Do not allow the model to:

- Open the tool grippers, raise grip torque, clear thermal protection, or rewrite calibration.
- Skip necessary fingertip lift, pick reset, or a reviewed intermediate pose.
- Extend a contact/hold beyond its qualified duration or introduce unreviewed arm overlap.
- Generate arbitrary Cartesian/joint paths or calculate the final millisecond schedule.
- Modify its own executable controller, safety checks, or registry during rehearsal.

Returning to a prior best plan still requires fresh-state admission; it is not a blind
replay after a fault. A fault or emergency stop is handled locally and immediately.

## 6. Current repo blockers before autonomous attempts

- [Operator instructions](../AGENTS.md) report a 75 C gripper incident and latest live grip
  setting 110; code default remains 180. The inspected connection path can restore the
  wrong setting, and the grip reassertion path needs protection review. No unattended loops.
- The bundled fret map does not provide a qualified plucking map or a complete two-arm
  scheduler. A fretting tool waiting for a human pluck is not autonomous two-arm playing.
- The existing [`agent/loop.py`](agent/loop.py) now defaults to camera off and renders
  input-aware prompts/specs. Its legacy mic default, base-mode assumptions, synchronous
  model waits, and automatic rest cleanup still need their respective review. Do not treat
  the camera change as a finished implementation of this bounded rehearsal design.
- Audio input/quality, chosen model's musical assessment, and its latency are not verified
  by fake-motion tests. Do not claim useful critique just because the API accepts a WAV.
- The active [Baseten planner](model/README.md) now uses managed Kimi K3. Its native tool/result
  round trip passed live with synthetic state, not a robot or recording. This is not a dedicated
  deployment or physical rehearsal result. Raw-audio critique and a separate evaluator path
  still need implementation/validation; the older Qwen Truss recipe is inactive.

The camera-off/input-policy change is implemented and tested with mocked frames. It changes
no motor/gripper settings, microphone defaults, or device permissions; the full evaluator/
phrase-rehearsal workflow remains proposed.

## 7. Relationship to fine-tuning

**Do this rehearsal experiment before committing to weight training if the goal is
improvement over a few attempts.** Prompt/context updates and saved plans may be enough.

Later, permissioned, outcome-reviewed episodes can become training examples for an open
student model. That would be a separate offline job with held-out evaluation, not something
that happens automatically while the robot plays. The symbolic-plan experiment referenced by
[FINETUNING.md](FINETUNING.md) is deferred research, not a task required to complete this loop.

For a truthful demo, distinguish: initial versus revised plan, actual recording, evaluator
assessment, local acceptance/rejection, telemetry, and any operator intervention. Do not
promise every attempt improves or manufacture a poor first attempt to make the loop look good.
