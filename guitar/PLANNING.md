# Guitar motion planning — direct transitions, telemetry-first timing

**Status: motion/timing requirements, not a completed phrase executor.** The active
[DESIGN.md](DESIGN.md) is same-arm guitar rehearsal with pretrained models; current code
and gaps are in [STATUS.md](STATUS.md). No replacement hardware, simulated performers,
or source-code transfer from the separate `astra-guitar` experiment is required.
This document owns local planning; [FINETUNING.md](FINETUNING.md) is deferred research.

## 1. Decision

Build a **state-aware, telemetry-calibrated phrase planner**:

- Avoid unnecessary global-rest excursions and redundant release/re-press operations.
- Keep required lifts, approach/retreat paths, pick resets, and stop behavior.
- Calculate schedules and trajectories in local code, using verified poses and measured
  mechanical timing—not numbers invented by an LLM.
- A pretrained planner may propose **symbolic plans**. Validate/compile them locally;
  weight training is not required and is not an implementation prerequisite.

The core motion/timing work has **no audio or multimodal training-data dependency**.
For the user's optional feedback idea, [REHEARSAL_LOOP.md](REHEARSAL_LOOP.md) adds a
pretrained audio evaluator and planner revision between attempts, without weight training.
Telemetry measures mechanical execution; it does not establish clean notes or audible
onsets. Audio-model judgments are separate assessments, not exact timing/contact truth.

The old agent loop still contains optional microphone code. This documentation does not
change its runtime defaults or prompts; it is not the new planner/data-collection runner.
Do not use its “judge from the camera” text as evidence of an acoustic result.

## 2. What the current source actually does

| Component | Observed behavior | Consequence |
|---|---|---|
| [`motions.py`](motions.py) | One persistent session; fake by default; ready/hover/touch/press/release/rest methods | Use session state as an interface requirement; do not assume a physics simulator |
| [`Arm.fret`](robot/arm.py) | If pressing, lifts to the old hover; then travels to the new hover/touch/press. Enters through `ready` only when outside the fret region | **Global rest is not inserted between every fret operation already** |
| Repeating `fret` on the same spot | Still lifts and approaches again | A qualified repeat-note hold is a candidate optimization, not implemented behavior |
| `Arm.pluck` | Approach, stroke, return to `above_string` | This is a local pick reset, not global rest. Do not remove it without a qualified replacement |
| Supplied [`fret_arm.json`](robot/poses/fret_arm.json) | Rest/ready and 54 above/touch pairs, including interpolated poses; no pluck map | Saved pose availability is not physical qualification; the two-arm path remains incomplete |
| `_execute` / `interpolate` | Base-first segments followed by remaining joints, linear joint interpolation at nominal 50 Hz, final fixed 0.15 s sleep | Not an IK/spline optimizer or a learned physical dynamics model |
| Guards | Joint boxes, speed/segment/drift/tracking checks | Useful protections, not complete swept-volume collision or contact-force validation |
| Returned timing | `t_cmd` is first non-base segment time; `duration_s` is rounded and can exclude the initial base movement; pluck reports the stroke plus separate approach information, not the whole cycle | Not suitable as precise full-transition/arrival labels without new instrumentation |
| [`agent/loop.py`](agent/loop.py) | One arm role per loop; fretting can request a human pluck; cleanup attempts rest | Not a demonstrated coordinated two-arm phrase scheduler; distinguish cleanup from between-note travel |

The **baseline to beat is the actual current direct-transition controller**, not an
artificial “always go home” straw man. Keep existing uncommitted motion work intact.

## 3. Current hardware gate

Read [../AGENTS.md](../AGENTS.md) before any hardware action:

- Never loosen the tool-holding grippers during ordinary motion, rest, or disconnect.
  `release()` lifts the fingertip from the string; it does not open the hand.
- Motor 12 previously reached 75 C. The latest operator-selected live limit is **110**,
  not a grip-force measurement or sustained thermal qualification.
- [`AstraSO101Config`](lerobot_robot_astra/config_astra_so101.py) still defaults to **180**.
  `motions.connect()` / `RealArm` do not expose/pass a grip-torque override in the inspected
  code. A normal connection can therefore reapply the wrong setting.
- `reassert_grip()` writes torque-enable again; do not assume it is safe to call after a
  protective trip. The thermal/electrical exception must override normal clamp retention.
- Do not start automated data sweeps, raise torque, repeat long holds, or use sudden large
  step commands to gather a dataset. Resolve configuration/thermal handling with the operator.
- Support the arm before ordinary body-torque release. In an emergency/thermal fault,
  necessary gripper power removal must not be defeated to preserve the grip.

This plan changes no torque setting, motor ID, calibration, or executable control code.
Software-only planning/data-schema work can proceed independently.

## 4. Represent the instrument as approved states and transitions

Create a versioned **capability graph**, not a new string-physics simulator.

A node describes a qualified state: named hover/contact/held-fret state, pick readiness,
arm identity, and relevant resource ownership. An edge is a reviewed transition with:

- Exact source/destination conditions and pose/calibration versions.
- The required lift/approach/retreat recipe and qualified speed/profile.
- Resource locks and allowed overlap with the other arm.
- Conservative duration estimate and its evidence/uncertainty.
- Limits on contact/holding time and the required fault/stop response.

An interpolated pose existing in a JSON file does not create an approved edge. Unknown
transitions are unavailable, not an invitation for a model to interpolate a shortcut.
Both arms share one scheduler; one process owns each serial bus.

### Useful candidate optimizations

1. **Repeated same note:** retain a qualified fretting posture across multiple pick cycles
   instead of reissuing `fret` each time. Only if contact duration, thermal behavior, and
   current position remain within the qualified envelope; stationary holding is not free.
2. **Changed fret:** lift from the current contact, use a qualified hover-to-hover route,
   then lower at the next fret. Do not drag along a pressed string to save distance.
3. **Pick reuse:** retain or reset the pick only as required by the qualified stroke. An
   alternating stroke is a new skill to qualify, not a free optimizer shortcut.
4. **Preparation overlap:** prepare the pick while the fret arm moves only for explicitly
   compatible paths/resources. No cross-arm collision clearance is inferred by an LLM.
5. **Whole-phrase compilation:** plan once, execute locally; no cloud call per note.

Do not remove the existing base-first routing or fixed settling sleep just because a
mathematical path is shorter. Such changes need separate path/tracking qualification.

## 5. Score and deterministic scheduling

Input: the ordered notes/spots, intended onsets and durations, and supported profiles.
Respect this repository's string convention: 6 = low E, 1 = high E; `e`/`E` spot spelling
is case-sensitive. Do not import another project's string indices or fret assumptions.

For each note:

1. Determine the current approved fret/pick states.
2. Select a feasible transition path through the capability graph.
3. Reserve fret release/travel/contact/settling and pick preparation/stroke/reset windows.
4. Make fret readiness precede the intended pick event by a qualified margin.
5. Preserve the previous note's required hold window and both arms' resource constraints.
6. Reject an infeasible tempo/phrase or propose an explicitly approved slowdown. Do not
   silently delay notes and call the result rhythmically accurate.

Use a lookup/shortest-path/dynamic-programming baseline as appropriate. With a small pose
library and fixed note order, this is often a small, tractable optimization problem—not
something that needs a large LLM. Do not claim a solver makes paths “physically perfect.”

Priorities are lexicographic: obey hard constraints and event requirements first; then
reduce avoidable travel, transition time, and redundant operations. Joint travel is a
**motion proxy**, not electrical energy or acoustic quality.

## 6. Measure mechanical timing on the real rig

First fix the telemetry definition; then collect small operator-approved runs.
No autonomous exploration, global sweeps, or simulator-derived acoustic labels. Optional
recordings for the rehearsal evaluator do not replace mechanical timing measurements.

Record these separately using local monotonic time:

| Measurement | What it means |
|---|---|
| Request/planning start | Software overhead begins |
| First motor command write | Physical command stream starts, including base-only movement |
| Last command write | Planned command stream ended; **not** proof the arm arrived |
| Sampled position versus target | Actual observed tracking error in verified driver units |
| First observed settled interval | All required joints remain within operator-defined tolerance for a specified dwell |
| Full skill/transition completion | Includes approach, stroke, retreat, and required waits |
| Fault/abort/timeout | A separate outcome, not a fast successful transition |

The current 50 Hz command grid is 20 ms; tracking checks are nominally every five steps
(about 10 Hz), with other reads around operations. This does not resolve hypothetical
5–8 ms mechanical offsets. Log actual sample times and uncertainty; if the target is reached
between polls, arrival is an interval, not an exact timestamp.

Do not reuse the 6-degree drift or 12-degree lag guard thresholds as “settled for guitar”
criteria. Those are different engineering quantities. Choose appropriate position/dwell
criteria with the operator and record them in the dataset version.

Suggested record fields: run/trial ID, arm/map/driver/base-mode versions, source/target
state, approved profile, command timestamps, position samples, read timing, observed settle
interval, outcome, and existing health/temperature/load readings if safely available.
Do not call raw load a measured force or current without a calibrated conversion.

Keep timed-out/aborted attempts marked as censored/failed; do not drop them or label their
short runtime as success. Keep physical records separate from fake/software-estimated data.
The fake arm follows commands instantly and cannot provide real latency labels.

## 7. Timing models: start simple

Start with an empirical transition-duration table plus conservative margins, separated
by arm, direction, speed/profile, base mode, and calibration revision. Measured variation
matters more than a model producing more decimal places.

If the table has insufficient coverage, evaluate a small numeric regressor or residual
model against it. A learned timing estimate can help plan ahead, but it is not a safety
certificate and cannot override qualified limits/readiness checks. Underprediction and
unknown transitions must lead to conservative handling, not faster motion.

Predicting mechanical settle time is **system identification**. Predicting symbolic next
states from known tool semantics is a **planning model**. Neither demonstrates learned
string acoustics or a general neural physics engine.

## 8. Work order and evidence

| Step | Deliverable | Acceptance evidence |
|---|---|---|
| P1 | Capability/state/score contracts and offline compiler | Valid paths only; explicit expiry/version checks; no devices or audio |
| P2 | Better event/position timing instrumentation | Full base/approach/stroke/retreat accounted for; sampling uncertainty retained |
| P3 | Operator resolves grip/thermal/configuration and verifies a small set of transitions | Qualified subset and short supervised measurements; no unattended sweeps |
| P4 | Deterministic state-aware phrase planner | Same-note/changed-note cases, hold limits, resource ordering, infeasible-tempo rejection |
| P5 | Local execution of a fully admitted phrase | Telemetry confirms mechanical criteria; failures/interventions reported |
| P6 | Bounded pretrained-model rehearsal, optional audio evaluator | Evidence drives permitted plan/context revision; no weight updates |
| Research only | Timing estimator or plan-selector fine-tune | Separate approved experiment after a demonstrated need; not a prerequisite above |

Report command scheduling error, sampled arrival/settling, travel proxy, unnecessary
rest/lift count, planning latency, deadline misses, and faults. Do **not** infer acoustic
note accuracy, buzz elimination, or audible onset error from telemetry. If the optional
rehearsal evaluator is used, report its judgments separately with uncertainty. See
[FINETUNING.md](FINETUNING.md) for why weight training is deferred and the conditions for
reconsidering it.
