# Prompt for the agent with external camera and YouTube access

You are taking over the visual performance phase of a real robot band project. Work with the live lamp, inspect external camera footage, study actual duet performances, and implement the smallest evidence-backed code changes that make the lamp a convincing frontperson. Do not stop at aesthetic advice: connect each finding to a specific function, configuration, or new module and verify the result physically.

## Context and scope

The lamp is a singer/dancer/bandleader. A future robotic guitar, operated by two arms, accompanies it and sometimes takes solos. Ultimately judges will request songs and the band will interact with the crowd. Right now, implement the lamp's reusable performance vocabulary and a short rehearsal scene; represent the guitar with timed cues. Do not expand this task into implementing the entire band or five-song repertoire.

Working locations:

- `/home/lelamp/guitarra`: architecture, future harness, and movement evidence. Read `ARCHITECTURE.md`, `BILL_BRIEF.md`, and `evidence/` first. Reconnaissance commit: `fc69642`.
- `/home/lelamp/lelamp-hackathon-2026`: running lamp runtime. Reconnaissance source commit: `fe874862b1ceaf151a6b37b184ab5ec12e09e6cd`.
- Guitar reference: https://github.com/shaoming11/astra-guitar, previously inspected at `c4283aafe2ab0e0ae323cd6ec5ed8f89fba56b85`.

Recheck repository instructions, working-tree changes, hardware state, and current code before editing. Preserve other work. The previous documentation commit was local: pushing failed because GitHub authentication was absent. Do not assume it reached the remote.

A laptop camera points at the lamp. Discover whether your available tools expose it. If not, ask once for a reachable stream URL and continue independent work. An SSH session on the robot does not itself expose the laptop camera. Verify a live, fresh view of the whole lamp and its surroundings before visually guided movement. Confirm whether the video is mirrored; establish audience direction and the future guitar position.

## Established findings to verify, not rediscover blindly

- Five servos: `base_yaw`, `base_pitch`, `elbow_pitch`, `wrist_roll`, `wrist_pitch`.
- Coordinates are `normalized_m100_100`, not degrees. Package neutral differs substantially from the measured folded pose; do not jump to it.
- Twenty-one completed trials exercised all axes, yaw at three durations, and coordinated sway. Small yaw/roll targets tracked relatively well; the loaded elbow showed approximately 6–8 units of error in the tested pose. These are limited measurements, not a workspace-wide calibration.
- HTTP `/api/motors/positions` acknowledges before physical completion. Its dashboard route does not perform the SDK's self-collision check; the prior tests checked paths locally before submission.
- Existing SDK `motion.move` has a runtime-selected minimum duration of two seconds. `clip.play` adds an entry transition with the same minimum, even at a matching initial pose. Successful research motion can resume idle.
- The SDK was enabled but unusable because `LELAMP_SDK_TOKEN` was unset. Do not disable authentication to work around this.
- Audio selected `auto_null` / Dummy Output. A ReSpeaker directional array was not detected. The robot's camera image was obstructed, and vision inference was disabled. Recheck; distinguish these from the external rehearsal camera.
- Normal idle and enabled torque were restored after testing. Runtime source, calibration, and servo gains were unchanged.

## Observe before choosing the fix

1. Record a baseline with a fixed external view, real frame timestamps, the intended beat/audio reference, command events, and encoder feedback. Estimate camera/audio capture delay before attributing visible lateness to motors. Report timing uncertainty; pixels from one camera are not calibrated 3D joint measurements.
2. Review at least four accessible actual duet performances across rock, country/soul, folk/ballad, and acoustic rhythm. Starting references:
   - https://www.youtube.com/watch?v=yXlULkwhgrc — White Stripes, Jolene.
   - https://www.youtube.com/watch?v=3Nl2rdaddKw — Stapleton/Timberlake, CMA 2015.
   - https://www.youtube.com/watch?v=HamYmjllE6A — Civil Wars, NPR Tiny Desk.
   - https://www.youtube.com/watch?v=PMpGjox3TBs — Rodrigo y Gabriela, NPR Tiny Desk Home.
3. Watch representative sections and transitions, including partner cues and endings. Log exact URLs, timestamps, and what you actually saw. Distinguish sampled frames from continuous playback. If unavailable, use an accessible alternative and disclose it. The previous agent could access metadata but not video; no previous visual analysis should be assumed.
4. Translate observations into lamp behaviors: anticipation, held poses, phrase accents, body/head phase, audience attention, partner acknowledgment, and yielding the spotlight. Do not imitate human anatomy or equate larger/faster motion with better performance.
5. Run small A/B trials, changing one factor at a time. Assess continuity, beat/phrase alignment, clear intention, repetition, silhouette, and the readability of “leading,” “listening,” and “supporting a solo.” Separate subjective scores from measured timing and tracking error.

Start within the previously tested small offsets and expand only when live feedback, collision checks, and the external view support it. Keep a single serial-bus owner. Do not increase torque/gains, widen calibration limits, bypass guards, or compensate the elbow with an invented fixed offset. Pause, controlled hold, torque release, and emergency stop have different consequences on this gravity-loaded mechanism.

## Concrete code map: change according to evidence

Paths in A are relative to `guitarra`; paths in B are relative to the lamp runtime. These are implementation targets, not a requirement to modify every file. First trace which code path your experiment actually uses.

### A. Put choreography and rehearsal work in the harness

**`band/performance/primitives.py` — new:** define versioned, parameterized primitives such as `listen`, `address_audience`, `prepare_downbeat`, `groove`, `phrase_accent`, `yield_spotlight`, `support_solo`, and `bow`. Each declares joint ownership, duration in beats, entry/exit state, and approved envelope. Keep creative content here rather than hardcoding it into the motor executor.

**`band/performance/profiles/*.yaml` — new:** store style parameters supported by the video review: amplitude, phrase length, accent placement, head/body phase, gaze dwell, and stillness. Store physical stage-pose/envelope data separately with device/calibration identity. If motion feels repetitive or emotionally flat despite good tracking, change primitives/profiles first.

**`band/performance/composer.py` — new:** combine groove, attention, and expression into one trajectory. Enforce finite values, joint masks, position/velocity/acceleration limits, bounded jerk, and continuity at joins. Retain intended musical landmarks. If smoothing shifts an accent, retime or reject it rather than silently moving the beat. Use a planned pose baseline; do not repeatedly redefine the target from sagged feedback.

**`band/performance/attention.py` — new if needed:** map audience sectors and partner location into bounded gaze targets, with dwell, hysteresis, and gentle release. If the lamp darts between targets, fix event selection and dwell rather than globally slowing all motors. Never infer sound direction from a missing microphone array.

**`band/adapters/lamp/client.py` — new:** wrap authenticated capability/session/action calls, terminal results, telemetry, and cancellation. Reject unavailable capabilities and stale observations. If “done” is reported too early, fix lifecycle handling here; waiting for an arbitrary sleep is not a production completion protocol.

**`band/rehearsal/runner.py` — new:** provide a reproducible baseline/variant runner with a fixed beat track, named presets, timing logs, camera capture references, and a simulated guitar cue sequence. Buffer local movement ahead; never place model inference in the per-frame or per-beat execution loop.

### B. Modify runtime mechanisms only when they cause the observed defect

**Jerky starts/stops or bad joins:** inspect `modules/robot_base/motion/interpolator.py`, `trajectory_processing.py`, `transitions.py`, and `fusion.py`. Existing functions include `smooth_motion_plan`, `limit_motion_velocity`, `make_transition_plan`, `prepend_transition`, `make_transition_quintic`, and `fuse_into_motion_plan`. Inspect `modules/robot_base/control/playback_pipeline.py` to establish which processing is actually applied. Reuse or correct existing behavior before adding another smoother. Minimum-jerk rest-to-rest easing is not sufficient for a moving-to-moving join; match appropriate boundary derivatives and preserve limits.

**Repeated pauses or the beat shifting at every clip:** inspect `modules/robot_base/control/safe_motion.py`, especially `target_plan` and `with_entry`, and `control/runtime.py::prepare_safe_motion` / `_play_prepared_motion`. Prepare the initial transition outside the musical interval. If needed, add an explicit performance preparation/chaining mode that validates the complete transition and exposes its timing. Do not globally remove the two-second minimum or merely omit an entry because positions look close; account for motion state, calibration, continuity, ownership, and safety.

**Idle interrupting a held pose or musical phrase:** inspect `control/runtime.py::_play_prepared_motion`, `pause_idle`, and `resume_idle`, plus `modules/robot_base/behavior/motion_manager.py::_pause_idle_for_tracking` and `_resume_idle_after_tracking`. Add scoped performance ownership with well-defined cancellation, timeout, and release behavior. Preserve ordinary idle behavior outside a performance.

**Gaze and dancing fighting each other:** first fix harness joint ownership/composition. Modify behavior arbitration only if a reproducible runtime conflict remains. Performance and audience tracking must resolve into one final checked trajectory.

**Inconsistent actual start time despite correct choreography:** inspect `control/executor.py::MotionExecutor.execute`. It currently starts a relative local timeline; it is not an externally scheduled show transport. Add scheduled monotonic starts only if needed, with explicit late/cancel behavior and actual execution timestamps. Never turn late frames into an unvalidated catch-up burst. Align transition completion and musical time zero.

**Need a new public scheduled-performance operation:** extend `modules/support/sdk_gateway/domain.py`, `policy.py`, `research.py`, and `service.py`, plus thin routes in `apps/robot_runtime/web/routes/sdk.py` or `sdk_research.py` as needed. Route through the existing motion owner and safeguards. Define prepare/commit/result/cancel semantics, versioning, idempotency, ownership, and deadlines. Do not expose arbitrary event-bus publishing, shell access, or raw motor writes. Do not silently redefine existing `motion.move` behavior.

**Persistent elbow/head error or posture droop:** start by measuring several safe poses and directions with camera plus feedback. Change the harness stage pose, joint allocation, amplitude, or tempo when that resolves the visual defect. Any later compensation must be bounded, calibration-specific, validated, and have a failure threshold. Raising completion tolerances does not improve accuracy.

## Deliver, then prove the improvement

Produce a reproducible 30–45-second scene: notice the audience → count in → perform a groove/phrase → cue the simulated guitarist → visibly support its solo → acknowledge the ending → bow. Demonstrate two contrasting style presets. Singing playback and audience detection may be explicitly simulated if their hardware/services are unavailable; do not call them verified capabilities.

For each change, record: observed defect and clip timestamp → hypothesis → exact file/function changed → expected effect → measured and visual before/after → remaining limitation. Avoid changing unrelated systems.

Add meaningful regression coverage for the changed composer, timing, ownership, and SDK contracts. Relevant existing SDK tests are `tests/unit/test_sdk_gateway.py`; add focused tests for new behavior. Verify valid trajectories, preserved musical timing, stale/duplicate requests, cancellation, fault behavior, and restoration of idle. Use the runtime's applicable repository checks; do not claim hardware verification from mocks.

Repeat the final scene under the same camera/audio conditions and report run count, tracking errors, timing uncertainty, visible naturalness judgments, and failures. Restore the prior healthy operating mode after successful trials; on a fault use the defined safe hold/stop procedure rather than automatically restarting movement.

Save `VISUAL_FINDINGS.md`, a concise code-change summary, exact replay commands, and non-sensitive metrics in `guitarra`. Keep large rehearsal media local/ignored unless asked to publish it. Update `ARCHITECTURE.md` and `BILL_BRIEF.md` to reflect demonstrated capabilities. Commit logical changes separately in each affected repository; identify commits and any unavailable checks. Do not publish captured audience footage or push runtime/deployment changes without authorization.

If you have visual access but cannot edit or reach the robot, complete the reference/footage analysis and write a precise implementation handoff instead. Never claim you moved, watched, changed, or verified something you could not access. Ask only for genuinely missing access or a physical condition that blocks the next step; continue independent work meanwhile.
