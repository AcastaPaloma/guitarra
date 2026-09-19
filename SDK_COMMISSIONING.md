# SDK commissioning and physical demonstration — 2026-09-19 UTC

The authenticated SDK now runs checked clips on the lamp. A camera-supervised
57.5-second diagnostic demonstrated individual axes followed by a gentle wiggle.
It completed through the SDK. **This does not confirm full five-joint health:**
the elbow response is limited and its final posture error grew across trials.
The full two-style musical rehearsal remains blocked by that physical finding,
not by missing authentication. No universal calibration was established.

Harness continuation commit: `e6e5ad8`. Runtime correction: `2fb7457`.
No GitHub push or media publication was performed.

## What was repaired and deployed

- Pulled the force-pushed guitarra origin (`d33036f`, clean-history initial
  commit), preserved the old local branch, and replayed the existing candidate
  as `e0caddc` and `4d3d988` on `lelamp-integration-20260919`. The robot checkout
  uses the same branch. Unrelated lighting-profile changes were preserved.
- Configured SDK authentication in protected local/device files and the existing
  service environment. No token is committed or printed. Repaired the existing
  runtime lock's ownership only after checking it had no owner; locking remains
  enabled. The runtime remains the only serial-bus owner.
- Found a real idle-clear failure: HTTP success with `name: null` left idle
  running. The behavior layer rejected the literal `clear_idle_animation` name.
  In runtime `apps/robot_runtime/web/legacy_routes/animations.py::set_idle`, map
  clear to the existing `none` sentinel and use `synchronous_motion: true`.
  Commit `2fb7457` on `guitarra-idle-control-20260919` is deployed. Five new route
  tests failed before the fix; 33 route/SDK tests passed afterward. The physical
  runtime then reported no configured/running idle and a stable held pose.
- `band/rehearsal/commission.py::build_probe` authors small/envelope probes,
  one-axis plateau tests, and the diagnostic showcase. All use the fixed planned
  baseline and existing composer bounds. `run_probe` uses authenticated SDK
  upload/play/result/cancel, records telemetry, and never marks a stage verified.
  `require_held_runtime` refuses active or resumable idle without stopping someone
  else's action. It is a preflight, not an exclusive lease against other clients.
- `band/rehearsal/recorded.py::recorded_probe` waits for a fresh physical-camera
  frame and reaps the recorder on success or fault. This prevents the invoking
  process from orphaning a recorder that tooling cleanup could kill early.
- `observe.py::capture_is_fresh` reads file time before current time. The previous
  ordering had a concurrent-write race that could report a fresh frame as future
  dated. A showcase stopped on the stale-camera check despite continuous capture
  (maximum nearby log gap 37.7 ms). The race is reproduced in a regression test;
  its attribution to that live incident is strongly supported, not instrumented
  proof of the exact failed age value. The same check is used in `execute.py`.
  The three-second stale limit was not widened. The unchanged showcase completed
  after this software fix.

## Physical runs and failures

All times below are UTC trial-start timestamps from the observer laptop. Commands
are normalized units, not degrees. Every motion used SDK `clip.play`, with the
runtime checking the complete path and its entry. The model covers head/base
clearance; it does not certify all servo housings, cables, people or furniture.
The external camera supplied an unmirrored side view. The view was rechecked
when the laptop moved; motion was held while the base was cropped and a hand was
near the arm. Workspace clearance was visually restored before continuing.

| Trial | Started | Result |
|---|---|---|
| `probe-small-01` | 06:40:37.907 | Recorder window ended during the run; SDK cancellation confirmed. |
| `probe-small-02` | 06:42:12.572 | SDK completed 15 authored + 2 entry seconds; tiny offsets did not move yaw/roll/head measurably. Recorder later truncated when its parent exited. |
| `probe-envelope-01` | 06:44:03.619 | SDK completed 25 + 2 seconds, ±4 authored waves. Valid 45-second recording: 1,350 frames, 208 samples, no telemetry failure. |
| `joint-elbow-01` | 06:49:09.277 | SDK completed 25 + 2 seconds. Other targets fixed; +4/−4 plateaus exposed a small, asymmetric elbow response. |
| `sdk-showcase-01` | 06:50:13.339 | Camera watchdog canceled at about 30 seconds; torque retained. This is a failed diagnostic, not a completed dance. |
| `sdk-showcase-02` | 06:51:51.505 | Same motion completed after watchdog correction: 57.5 authored + 2 entry seconds. 2,325 camera frames over 77.5 seconds; 383 recorder samples, zero read failures. |

There were six submitted SDK trials: four completed and two confirmed canceled.
An earlier audio/video startup attempt produced no frames and sent no motion.
No recording or audience footage is published. Local media is under
`/tmp/guitarra-rehearsal-20260919/`.

## What the demonstration actually shows

The showcase authors ±3-unit individual movements in joint order yaw, waist,
elbow, roll and pitch, followed by a ±2 five-axis wave with phased reversals.
Live camera samples around elapsed 11, 37, 53 and the ending show an open lamp,
changing body/head orientation, and no observed self-contact. These are sampled
views, not a certified continuous contact inspection. The isolated elbow trial
also visibly changed the upper-arm/head angle slightly while other feedback
coordinates were stationary. In the final showcase's dedicated elbow interval,
the elbow feedback was essentially stationary; its full-run range includes
entry drift and must not be mistaken for successful target following.

| Axis | Final showcase measured span | Final measured − planned |
|---|---:|---:|
| Base yaw | 4.362 | −0.783 |
| Base pitch / waist | 5.255 | −0.210 |
| Elbow pitch | 2.618, mostly entry drift | **−8.853** |
| Wrist roll | 4.595 | −0.104 |
| Wrist pitch | 3.003 | +1.401 |

In the isolated elbow test, positive command produced only about 2.24 units of
upward response after entry; the negative/return intervals changed about 0.125.
Final elbow error there was −5.860 units. This is not a healthy bidirectional
tracking result. The camera and encoders do not establish a mechanical cause.
Do not increase gains, add a fixed elbow offset, widen tolerances, or chase the
sag by redefining the planned baseline. Inspect the loaded joint/mechanism before
larger or prolonged dancing. The stored stage remains `hardware_verified: false`.

The existing runtime tolerances remain 2 units by default, 10 for elbow and 3 for
head pitch. SDK `clip.play` success means the executor finished; its code checks
terminal position tolerance only for `motion.move`, not uploaded clips. Even a
result within those existing tolerances would not establish good dance tracking.

No audible beat was recorded. Dummy Output remains the robot's only selected
speaker route, perception is disabled and directional sensing is unverified.
Camera/audio physical delay is unknown. Final-run SDK telemetry RTT median was
34.8 ms, maximum 351.2 ms; these are request timings, not physical motion latency.
The SDK action lasted about 62.21 wall seconds with a reported 59.5-second plan;
preparation/polling/timeline uncertainty prevents assigning the difference to
servo lateness. No beat-error or naturalness improvement score is claimed.

## Current state, checks, and remaining acceptance

After the final run, the SDK reported `succeeded`, `completed: true`, and
`collision_checked: true`. Runtime status showed no active motion, no configured
idle, torque enabled and no last error. The lamp is holding open. Normal idle is
left off to respect the user's explicit request to avoid folding onto itself;
automatic restoration has not been physically approved for this posture.

33 local regression checks pass, including isolated-axis ownership, bounded
showcase composition, stale-camera detection, the timestamp race, recorder
lifecycle, SDK completion/cancel, idempotency and composer continuity. The robot
checkout is checked separately after synchronization. These are software checks,
not substitutes for physical evidence.

The controlled software before/after used the same showcase trajectory and
limits: cancellation before the freshness fix, completion after it. This is not
a naturalness A/B. The original 40-second two-style scene, one-factor phase/support
comparison, stage directions and synchronized audible beat remain unverified.
Exact non-sensitive results are in
[evidence/sdk-commissioning-2026-09-19.json](evidence/sdk-commissioning-2026-09-19.json).
Replay instructions are in [REHEARSAL.md](REHEARSAL.md). The public
[LeLamp runtime](https://github.com/humancomputerlab/lelamp_runtime) exists, but the
installed hackathon runtime and its authenticated SDK contract were inspected
and used; installing a different public runtime was unnecessary.


## Requested larger dance — prepared, clearance pending

A subsequent `dance` diagnostic doubles yaw/roll amplitude relative to the
completed showcase wiggle, retains the ±4 tested authoring bound, and keeps the
elbow target fixed. `HeldJointGuard` watches actual elbow movement against a
fixed pretrial reference and triggers SDK cancellation above 0.75 units. A new
integration regression verifies cancellation without torque release. The suite
now has 36 passing checks.

The SDK accepted the 25-second candidate upload without commanding motion.
The current camera setup places a laptop close behind the head; its removal from
the turning space was requested. No exaggerated-dance completion is claimed.
The previous diagnostic evidence and unresolved elbow finding remain unchanged.


## Larger dance attempt — canceled during entry

After the user's “go”, `four-axis-dance-01` started at **07:04:43.405862 UTC**.
The authored 25-second four-axis trajectory was unchanged from the prepared
candidate; elbow target remained fixed at the original planned −68.329177.
Action `sdk_act_456647f7546d46ff` passed the SDK's entry/path collision checks.

Before the dance began, elbow feedback changed from −77.431421 to −80.798005
(**−3.366584 units**). The 0.75-unit held-joint guard triggered about 3.135 seconds
after trial start. SDK cancellation was confirmed about 0.372 seconds after the
fault observation. A later authenticated SDK read showed the same elbow angle;
torque remained enabled, no action or idle was playing. The head appeared lower
and closer to the base; this camera view cannot certify contact or clearance.

The guard is sampled over HTTP. Its 0.75 threshold is a detection threshold,
**not a physical excursion bound**: the first changed sample was already 3.37
units away. There was no completed exaggerated dance, and no retry followed.
The full 45-second video contains 1,350 encoded frames and the post-fault hold.

Source reinspection confirmed `safe_motion.py::with_entry` and
`runtime.py::_play_prepared_motion` construct an entry from current feedback to
the first authored pose. Thus a fixed elbow target in the authored dance does
not mean a fixed elbow target during entry. The failure occurred there; it is
not evidence that the new yaw/roll amplitude caused the drop. Mechanical/load,
servo control, and entry-command effects have not been separated. No runtime
entry bypass, gain adjustment, tolerance expansion or sagged-baseline reset was
used to make this pass.

The resulting elbow posture is 12.468828 units from the original planned target,
outside the runtime's unchanged 10-unit tolerance. Added
`commission.py::require_stage_alignment` to reject any new commissioning probe
whose starting pose is outside the existing per-joint SDK tolerances. A read-only
check of the live SDK response correctly rejected this posture; passing this
check would still not certify safe or accurate motion. The suite now has 38
passing checks. Further motion needs diagnosis of the elbow/entry behavior and
physical clearance, not a looser guard. Evidence is saved in
[evidence/four-axis-dance-result-2026-09-19.json](evidence/four-axis-dance-result-2026-09-19.json).


## Retry diagnosis — hardware damage not established

The user's next retry request was checked through authenticated SDK position
reads and the unchanged commissioning preflight. Four held samples were identical:
elbow −79.301746, approximately −10.972569 from the original planned baseline.
The existing elbow tolerance remains 10; the retry was rejected before any
motion submission. The other four positions also remained stable during those
samples. Position response and holding do not prove a mechanically healthy servo.

An offline reconstruction with the installed runtime's `with_entry` confirms a
specific command transition in the failed trial: the previous successful clip's
planned elbow target was −68.329177, but the first new entry target is the measured
−77.431421. That is a −9.102244 change in the generated target before easing back
toward the authored first pose over two seconds. `MotionExecutor.execute` writes
the first waypoint directly. This establishes the generated command behavior;
the servo's actual goal register and torque were not measured. A resulting change
in holding effort under gravity is a plausible contributor, not proof that it is
the only cause or that hardware is undamaged.

The installed SDK does not expose servo load, temperature, voltage or fault
registers. No raw serial connection, gain change, torque cycle, startup bypass,
baseline reset, or wider tolerance was used to force a retry. Source/status review
and an on-site request to observe clicking/grinding or physical contact are the
current diagnostic steps. There was **no additional dance or motion attempt**
after the stopped test. Saved details:
[evidence/retry-diagnosis-2026-09-19.json](evidence/retry-diagnosis-2026-09-19.json).
