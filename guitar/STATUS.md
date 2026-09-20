# Guitar implementation status and consistency audit

**Source/status snapshot, not a physical qualification report.** Requirements are in
[DESIGN.md](DESIGN.md); operator facts/overrides remain in [../AGENTS.md](../AGENTS.md).
The pulled single-arm tap web app is now the active web milestone; it is **not** the
older fake/two-arm console. Camera remains off. No deployment, training, real motion
or real microphone was exercised by the checks below. The separately approved synthetic
Baseten inference probe and its limits are distinguished from offline implementation tests.

### Audio implementation follow-up (2026-09-20)

**Baseten only; full preview Inkling primary, bounded Small fallback; local estimates
support qualitative review.** [Current interface](model/AUDIO.md), [investigation/history](model/AUDIO_INVESTIGATION.md)
and [sanitized live evidence](model/audio-inference-check.json) supersede older audio
snapshots below about failed access, missing grounding, and no fallback.

- The operator approved **three synthetic inference requests within $0.10**. All returned
  HTTP 200 with reasoning disabled: full text **0.485s**, full audio **6.447s**, Small audio
  **3.272s**. Both audio responses reported **21 audio-input tokens** and passed the v1
  schema used for the probe. Usage-based uncached-price estimate: **$0.00175575**, not an
  invoice. No fourth request. Current access works; the older timeout cause is unproven,
  not an established entitlement denial. Catalog modality metadata did not block audio.
- **Connectivity is not musical accuracy.** The one-second generated clip had two tones
  and no room noise; neither model described both, and both mentioned room noise. The
  old prompt also elicited targetless numeric grades. This was not real guitar audio.
- Runtime source now uses audio-only reasoning default **none**, a 1,536-token cap, at
  most primary + one logged Small fallback for transient failures, and a **75s** review
  admission/result budget capped further by the caller's remaining time. Stop/deadline
  checks prevent further calls and discard late results. Auth/billing/input/assessment
  errors do not trigger alternate-model shopping. Socket timeouts do not cancel billing.
- DSP v2 fixes all six reproduced regressions: energy rises instead of sustained-level
  “onsets,” one-to-one event assignment, preserved plan/event identity, separate note
  identity/tuning cents, and octave ambiguity. Multiframe periodicity, clipping, short/
  unstable signal and note-boundary gates can abstain. These remain unqualified acoustic
  heuristics; no string-contact, calibrated confidence or absolute-delay claim is made.
- Source-WAV-hash-bound estimates and capture quality now reach **Inkling and Kimi**;
  compact versioned summaries/reviewer identity reach bounded history. Unknown evidence
  stays unknown. Current plans explicitly lack acoustic timing targets, even on DSP
  failure; unsupported timing claims are rejected and delay/rhythm-error/jitter remain
  unavailable. v2 permits null scores instead of forcing grades on unassessable evidence.
- UI labels attack candidates and uncalibrated model opinion, displays reviewer/fallback
  failures, and no longer presents the old timeout warning as current endpoint health.
- **Verification:** current combined `arm_controller/tests` + `guitar/tests` passed
  **340 Python checks** with no expected failures; three Node capture checks and JS syntax
  checking passed. The old DSP xfails are normal regressions now; duration/schema fixtures
  match the current contract. Two dependency-deprecation warnings remain, not test failures.
- **The revised v2 contract/feedback loop was verified offline only after the three live
  v1 probes.** No real recording, microphone/camera, motion, deployment, training or
  physical improvement was tested. This audio task made no credential/environment edit,
  hardware change or server restart. Concurrent motion/merge work below is separate;
  existing operator/thermal/path gates and separate approval of each next take remain.

## Current motion correction: lift-first tap routes + explicit arm ownership

This update applies to **`arm_controller/` on 8788**, not the old fake console on
8787. Earlier prompt-only changes under `guitar/orchestration/` did not affect this
player. The actual cause was a fixed `rest → tap → rest` cycle with all body goals
sent together: its named “lift” did not enforce clearance before lateral movement.

- [`tap_paths.py`](../arm_controller/tap_paths.py) now compiles the whole phrase
  through reviewed contact/hover pairs and directed hover crossings. The executor
  waits for the current key's own lift, then takes the minimum joint-count-travel
  reviewed route and lowers/taps. No global rest between notes, contact-to-contact
  shortcut, guessed hover, or fall-back-to-neutral route. Repeated keys still tap/lift.
- Missing/stale paths reject **before reservation/mic/serial access**. Unknown start
  pose, drift and lift timeouts prevent continuing; motion faults latch. Final parking
  uses reviewed exit edges, respects the deadline, remains Force-Stop-addressable,
  and a failed exit is no longer hidden as a successful take.
- Current source map is **not empty**: 25 v4 contacts (rows 1–4 × six strings plus
  `r5_1`), `rest`, and `neutral`. It has **zero key hovers** and **no lift-first review**.
  Playback is deliberately blocked until an operator-reviewed small subset exists.
  No calibration/poses, grip settings, speed, acceleration or contact dwell were changed.
  Old rest/row profiles remain readable in history but no longer authorize real taps;
  extra-pose/SNA playback and the old row-hub sweep cannot bypass this rule.
- Kimi's arrangement contract now includes explicit `arm` ownership and available
  reviewed transition costs, with lift-first/minimal-travel priority. The primary
  native tool schemas also require an owner and reject wrong-arm/raw-target arguments;
  global parking and sustained holds are not model-callable choices between notes.
  The local compiler, not prompt compliance or an audio model, decides the final route.
  The UI previews named stages with `/api/trajectory`; no media/model/device access.
- [`tap_arms.py`](../arm_controller/tap_arms.py) reserves `tap_primary` for its recorded
  rows 1–5 and **future `tap_secondary` for rows 7–11, strings 1–6 right-to-left**.
  The latter is explicitly unavailable: no guessed port/IDs, poses, connection, or
  executor. Cross-owner/unrecorded/disabled assignments fail locally. A device-free
  future dual-owner schedule serializes the shared guitar workspace; **not** a live
  two-arm executor or permission for overlapping motion.
- The pulled player's normal final park/body-torque-hold vs fault/body-torque-off
  policy remains (force stop holds frozen goals). Motor 12 is never commanded.
  This is not an independent thermal monitor or hardware E-stop; historical thermal
  and sustained-holding gates still apply. No physical playing/clearance was verified.

Details and the minimal two-key recording/review follow-up: [PATHS.md](../arm_controller/PATHS.md).
Tests use artificial poses and a fake serial bus through the actual `FretArm` methods.
The original combined working-tree run reported 274 passes, six expected failures
from separate uncommitted DSP checks, and two pre-existing audio test-fixture failures.
The merge update below validates the exact scoped commit independently of that work.
Three Node capture checks and seven fully mocked browser cases passed, including
missing-path rejection before microphone/Play, successive takes, cancellation, and
mobile layout. Optional Playwright was reused from `/tmp/guitarra-browser-check`
without altering the robot environment. Private evidence:
`guitar/runs/lift-first-browser-check.json` (synthetic, not audio/hardware evidence).
The idle tap server was restarted on **8788**, after checking no active take/riff,
serial device, or external request. Bootstrap confirms 25 contacts, zero hovers,
no admitted path profile, and the secondary arm unavailable. A local trajectory
preview rejects missing clearance without reserving/playing a take. **Reload the page**
for its new session token. Other servers on 8787/8765 were left alone.
No live model request, real microphone/camera, hardware motion, deployment or training
was made for this motion change. Commit/push was subsequently requested by the operator.
Separate audio/provider and legacy-console edits are preserved locally, not bundled
into the motion/merge commit.

### Merge integration (2026-09-20)

Integrated upstream `3322eba` with the lift-first/arm-owner work. The overlapping
planner example retains explicit ownership and `lift_first`, while keeping the
incoming 2,000-character rationale limit and unavailable-key guardrails. Invalid
provider/schema/local proposals preserve the recorded review and finish `inspect`;
Stop or a changed calibration still wins (`stopped`/`expired`), with no replay.
The two older evaluator fixtures were aligned with the already-existing WAV duration
limit and required assessment fields; no runtime audio behavior changed here.
Merge verification: **276 Python checks passed** against an isolated export of the
exact scoped motion/merge commit, excluding concurrent audio/provider development.
Node capture checks and the mocked browser flow also passed; no device/media/provider
access or physical qualification was performed. The merged app is served on 8788;
Play remains gated by missing recorded/reviewed hover paths.

## 0. Original single-arm web rehearsal snapshot (2026-09-19; historical)

**The current motion/keypoint/ownership facts above supersede this earlier snapshot.**
Its four-note budgets, empty key file and rest-hub-only route described the original
implementation, not the current player. Audio-specific development remains separate.

Source: [`../arm_controller/webapp.py`](../arm_controller/webapp.py),
[`rehearsal.py`](../arm_controller/rehearsal.py), [`tap_plans.py`](../arm_controller/tap_plans.py),
and [workflow/limits](../arm_controller/REHEARSAL.md).

- The working tap/fret arm (body IDs **7–11**) is the active subset of the same rig.
  The pluck arm is out of service. Tool-gripper **12 is never commanded** by this path.
  No old map, additional performer/arm, plugin reconnect, or camera fallback is introduced.
- The updated app is launched at **http://127.0.0.1:8788**. The older `guitar/web` fake
  console on **8787** and the unrelated service on **8765** are untouched.
- **Current keypoints are empty:** the pulled calibration commit cleared
  `arm_controller/keyframes_arm2.json` for re-recording. The backup/calibration files
  are preserved, not automatically restored. Planning/play admission fails closed until
  a valid current rest/key grid exists. Earlier reported successful tap playing does
  not mean this emptied checkout is presently ready to play.
- Play + Listen requires per-take mic/upload/inference and supervision/body-support
  consent. Browser WebAudio/AudioWorklet capture starts and produces samples before
  Play submission. Permission denial/cancellation, capture interruption, empty/invalid
  audio, stopped/faulted playback, stale calibration, or expiry cannot trigger replay.
- One **completed** take's bound WAV is validated/resampled through the existing Baseten
  audio adapter; its assessment is passed as **untrusted data** to one bounded Kimi
  proposal, separately from command/encoder telemetry. A successful schema/audio-token
  response is an assessment, not proof of a clean note or qualified mechanics.
- Software bounds: **four notes/take, 60s capture, 55s local execution budget**, one
  audio request plus at most one text revision per take, **three explicitly started
  attempts per revision chain**. These limits are not physical/thermal qualification.
- Proposed changes are one category at a time: up to three post-lift pauses in 50ms
  steps (at most ±100ms each), one adjacent event swap, or one recorded same-pitch
  key alternative. The present 18-key set has no same-pitch alternatives. Exact
  acoustic onset scheduling, contact-depth/XYZ changes, and new trajectories are absent.
- **Only `rest_hub` is executable.** No qualified hover transitions exist; audio and
  estimated XYZ cannot certify a shorter A→B path avoids unintended strings. The model
  may request operator inspection/qualification but cannot invent/enable a path.
- Proposals display a diff, stage the next tuning, require a separate confirmed Play,
  expire after five minutes, and revalidate the current calibration fingerprint. No
  automatic physical repeat, recovery move, or model tool dispatch is enabled.
- The main UI is compact; **Progress** is separate. Persistent phrase sessions store
  per-take WAVs/reviews/plans, tuning IDs, and an operator-preferred take. Previously
  performed tunings can be staged/reused without rebuilding the song; new captures and
  fresh admission are mandatory. One session can continue across explicitly supervised
  revision sets (100 takes/session), not unattended budget resets. Restart never resumes
  motion/capture/inference. A bounded last-three-attempt text history reaches the planner.
- Progress compares command durations for the same pitch order/calibration only, separately
  from uncertain categorical audio judgments. No calibrated quality/improvement score or
  automatic “best” claim. Human preference is labeled as human, not model qualification.
- Runtime corrections: raw `fret.py` encoder timeouts now raise rather than silently
  continuing. Web playback disconnects with **body torque off** before inference
  (**support the body**); it does not open/reassert grip or home on faults. This differs
  from the old web player's body-torque-on cleanup. The standalone CLI default is unchanged.
- Cooperative Stop/heartbeat watchdog blocks subsequent taps and discards late model
  results; a current bounded tap/lift may finish. It is **not** an independent hardware
  E-stop or thermal/electrical monitor. The recorded 75°C incident/live 110 setting and
  legacy plugin default/reassertion issues remain unresolved. No unattended loops.
- WAV + structured reports are private local, Git-ignored files under
  `guitar/runs/tap_rehearsal/<UUID>/`. Source/capture alignment is browser-attested and
  approximate, not independently verified hardware/ADC provenance. No automatic retention
  cleanup; delete/share recordings deliberately. Keys stay server-side. Received partial
  buffers on Stop/device interruption can be archived locally, marked incomplete, and
  are **never** uploaded to the evaluator. Denied/no samples/tab loss/upload failure can
  leave a take without audio. Archived audio reads require the local token and reject
  path traversal/symlinks. Sessions/favorites live in `tap_rehearsal/sessions/`.

**Verification:** **188 Python checks passed** (67 new single-arm checks + 121 existing).
Three Node PCM/worklet checks also passed (WAV encoding, startup readiness, and rejection
of post-readiness render gaps/missing input). Six browser cases passed using an
oscillator-generated MediaStream and mocked HTTP/motor/
model results: two successive reviewed takes with cached tuning/favorite/history/reload,
denial, late permission after Stop, stop during playback, provider-unavailable feedback,
and mic disconnect. Stop/disconnect kept local-only partial buffers. All tracks closed;
no JS errors or mobile/desktop horizontal overflow. Private, explicitly synthetic evidence:
`guitar/runs/tap-browser-check.json` and `tap-browser-check-{play,history}-{1100,390}.png`. No paid API/device test occurred.

**Audio remains live-unverified:** the last Inkling probe still timed out; see
[model/audio-connection-check.json](model/audio-connection-check.json). No new successful
listening, useful guitar critique, physical improvement, or thermal qualification is claimed.
A consented non-motion endpoint check and separately approved supervised physical take are
still needed after keypoint and protection readiness. The browser loop is implemented in
source and offline fixtures; it is not a demonstrated live autonomous rehearsal.

## 1. Earlier `guitar/` source audit (separate legacy/fake paths)

The following audit describes the older CLI and fake two-arm orchestration, **not** the
new `arm_controller/` tap app. References below to parked/unintegrated audio, fake-only web,
or missing two-arm execution apply to those paths; §0 supersedes them for the new web source.

| Component | Source evidence | Limit |
|---|---|---|
| Named guitar motions | [`motions.py`](motions.py), [`robot/arm.py`](robot/arm.py) | Fake by default in `motions.connect`; a stateful single-arm API, not a complete two-arm phrase executor |
| Fret pose map | [`robot/poses/fret_arm.json`](robot/poses/fret_arm.json), [`fretmap.py`](robot/fretmap.py) | 54 above/touch pairs across six strings/frets 1–9, including interpolation; not 54 physically qualified targets |
| Pick primitive | `Arm.pluck` | Requires `above_string`, `pluck_start`, `pluck_end`; the bundled fret map has none |
| Local guards | [`guards.py`](robot/guards.py) | Joint/speed/segment/drift/tracking checks; not complete collision/contact/force or thermal qualification |
| Legacy agent loop | [`agent/loop.py`](agent/loop.py), [`tools.py`](agent/tools.py) | One role per run; fret role can wait for a human pluck; no whole-song/two-arm clock proven |
| Fake orchestration | [`orchestration/`](orchestration/README.md) | Real Baseten inference over existing Motions/FakeArm and a synthetic pick; four live workflow cases passed, not physical playing |
| Local web app | [`web/`](web/README.md) | Loopback-only prompts/notes, preset/custom runs, live event/state views, cooperative controls, history/downloads; fake-only with no hardware unlock |
| Model adapters | [`backends/`](agent/backends/) | CLI now defaults to `baseten` (managed Kimi K3); Astra/Claude/scripted and the inactive custom Truss adapter remain explicit alternatives |
| Baseten client | [`baseten.py`](agent/backends/baseten.py), [`transport`](model/baseten.py) | Active native Chat Completions/tool calls, local schema validation, one-call cap; live synthetic continuation passed |
| Baseten evidence | [`connection-check.json`](model/connection-check.json) | Synthetic `look` → result → `done`; no tool dispatch, media, or hardware |
| File-based audio evaluator | [`audio.py`](model/audio.py), [`evaluate_audio.py`](scripts/evaluate_audio.py) | Explicit upload of a selected PCM16 WAV, local resampling, schema validation; no devices/tools; live endpoint still times out |
| Older Baseten package | [`config.yaml`](model/baseten_guitar_agent/config.yaml) | Inactive Qwen2.5-7B/vLLM Truss recipe; no successful deployment claimed |
| Older Baseten server | [`model.py`](model/baseten_guitar_agent/model/model.py) | Inactive custom `/predict` server; not used by managed Kimi K3 |
| Camera | [`camera.py`](sense/camera.py), [`camera_relay.py`](sense/camera_relay.py) | **Off by default** in CLI/Toolbox; `--camera` explicitly requests optional snapshots from a separately started relay. Default runs never probe the relay or attach images |
| Microphone/scorer | [`mic.py`](sense/mic.py) | 44.1 kHz ring buffer and handcrafted pitch/onset/level heuristics; **not** a pretrained audio-model evaluator |
| Run log | `Recorder` in `agent/loop.py` | JSONL includes selected input modes; JPEGs only for opt-in frames. No persisted per-attempt WAV/evaluator contract in this recorder |

No **live-verified** audio-evaluator feedback loop, qualified two-arm performance, fine-tuned
model, or custom Baseten deployment is established. The new single-arm software loop and
its offline verification are described in §0; the legacy paths in this table remain separate. The live Kimi K3 result verifies managed provider
connectivity/tool continuation only. Historical Astra/Claude requests remain separate traffic.

## 2. Hardware and runtime blockers

### Operator configuration and protection

`AGENTS.md` records the gripper thermal incident and latest live setting. At inspection,
that setting is 110 while the plugin default is 180. `motions.connect`/`RealArm` do not
expose/pass an override; a reconnect can reapply the wrong limit. `reassert_grip` writes
`Torque_Enable` again without a demonstrated thermal gate. Do not use autonomous repeats
or sweeps before this is resolved with the operator. Do not bypass protection or loosen
tool grippers in ordinary cleanup.

### Runtime behavior is not the target safety design

- `motions.connect` defaults to `base_mode="position"`; the older agent CLI constructs
  `RealArm` using its legacy `speed` default. Addresses alone do not indicate servo health.
- `agent.loop` attempts rest movement in `finally`, including errors/interrupts, before
  disconnecting. This differs from the callable motion context, which disconnects without
  automatic rest. Neither is proof of an independent emergency-stop path.
- The time/turn budget is checked between turns, after tool calls. A synchronous model
  request can block. The managed Baseten adapter rejects multi-call responses, but other
  adapters still need equivalent admission. An independent watchdog/expiry layer is needed.
- There is no demonstrated local protection monitor running independently during model
  waits; fresh-state/thermal checks and safe inter-attempt holding cannot be assumed.

### Baseten managed Kimi K3 is connected; hardware/audio integration is separate

The quality-first hackathon path uses `moonshotai/Kimi-K3` on
`https://inference.baseten.co/v1/chat/completions`, with high reasoning. It reads the Baseten
key from `.env`, uses Bearer authentication, and requires no private model/deployment ID.
The earlier Truss recipe is retained but inactive. There is no automatic provider/model fallback.

A live two-request synthetic round trip (`look` → supplied synthetic state → `done`) passed
in 2.27 seconds; [evidence](model/connection-check.json) includes usage and the explicit
no-hardware/no-media boundary. The adapter validates tool schemas/arguments and rejects
unknown/multiple calls, duplicate IDs/JSON keys, nonfinite numbers, and incomplete responses.
Provider continuation fields are preserved without printing private reasoning. These are
software checks, not physical readiness, contact-force, or thermal guarantees.

Camera stays off by default. Kimi K3 supports optional images but is not the raw-audio
evaluator. An explicit file-based Inkling audio adapter now exists, but the documented audio
request still timed out on a one-second synthetic WAV. [Probe evidence](model/audio-connection-check.json)
is a failure record, not a listening/assessment result. No user media was uploaded.
The adapter validates/resamples PCM16 WAV files, requires per-call upload consent, and rejects
malformed/refused/truncated/tool-call responses or missing audio-token evidence. Failed requests
produce unavailable feedback, not bad-note scores. It is not connected to the mic recorder,
planner observation loop, or robot tools. See [audio setup](model/AUDIO.md).
The current planner still receives text summaries only.

### Active milestone: real inference, fake execution

`python -m orchestration --allow-inference` from `guitar/` is the current device-free entry
point. There is no hardware/port flag. The fretting tools call existing `Motions` on an
explicit `FakeArm` with an injected virtual clock; pick actions are state-only fixtures.
The real controller keeps its original wall clock. Gripper/connection defaults are unchanged.

One paced live batch passed single-note, repeated-note/string-change, unsupported-target,
and injected-fret-failure workflows. The model reused a held fret and stopped on the
injected fault without retrying/plucking/homing. [Evidence](orchestration/evidence/baseten-workflows.json)
contains model calls/results and honest virtual-time labels. Earlier HTTP 429 interruptions
were infrastructure limits, not coordination failures. The runner now paces requests and
stops batches without replay on provider errors, reporting those runs as incomplete.

Checks cover workflow invariants, not a fixed exact tool trace or actual acoustics/physics.
This does not implement a physical two-arm scheduler, independent watchdog, hold/thermal
qualification, or audio critique. Audio work is parked; no audio endpoint is called here.

The local web console now wraps this same runner at `http://127.0.0.1:8787`. It adds operator
prompts, editable expected notes, budgets, event/state polling, history, and log downloads.
Pause gates future requests/dispatch; Stop discards pending calls when an in-flight request
returns. Neither is a hardware emergency stop. The browser never receives the Baseten key.
One actual browser-submitted Baseten workflow passed with the requested `where` call first;
[web evidence](runs/web-ui-check.json) is local/Git-ignored. No hardware/media was accessed.

### Timing and sensing are estimates, not ground truth

- `_execute` can start `t_cmd` after an initial base-only phase; `duration_s` is rounded and
  includes a fixed settle sleep, not verified encoder-settled arrival.
- Commands are nominally 50 Hz and tracking checks about 10 Hz, not evidence of 5 ms accuracy.
- The microphone callback timestamps callback arrival and ignores callback status/ADC timing;
  capture waits have no independent timeout/retention validation in the inspected code.
- A reported “clean pluck,” “probably missed,” or “buzzed/snagged” explanation is a heuristic,
  not a validated acoustic classification or mechanical diagnosis.
- Prompts/specs now reflect camera/mic availability. Camera defaults off; `--no-mic` marks
  acoustic measurement unavailable instead of directing the model to judge sound from an image.
  Local scorer heuristics themselves still need the quality/timebase checks described above.

See [PLANNING.md](PLANNING.md) and [sense/README.md](sense/README.md) for the proposed fixes.

## 3. What changed in the documentation

| Previous conflict | Current interpretation |
|---|---|
| One-arm open-G chord strumming / π0.5 policy-server setup | Same two arms; default qualified guitar tools; no VLA server prerequisite |
| “Self-tuning” implies weight training | Plan/context revision during rehearsal; fine-tuning is separate, deferred research |
| Audio forbidden or a bespoke trained sound classifier required | Optional pretrained audio evaluator; capture/inference integration needed, no classifier training required |
| Baseten configuration described as a proven deployment | Managed Kimi K3 now has actual synthetic tool-call evidence; older Truss deployment and physical/audio claims remain unverified |
| Pluck-role fake smoke command with no pluck map | Use non-motion endpoint fixtures/fret-map fake cases; do not claim absent poses exist |
| Camera assumed to be part of every request | CLI/Toolbox default off, `--camera` opt-in, state-only `look()`, no default frame requests/attachments/recordings |
| Disabled inputs still described as present | Input-aware prompts/specs and unavailable-audio output; verify actual model modalities separately |
| Return-to-rest optimization presented as wholly new | Current fret-to-fret routing already avoids global rest; proposed gains must beat it |
| Onset count equated with strings/clean contact | Local estimates and model assessments carry uncertainty; no force inference |
| Lamp/band, simulator, or transcription work treated as guitar prerequisites | Explicit separate/reference material, not current scope |
| Ordinary connect/disconnect described as motion/torque-neutral | Actual side effects, mode mismatch, and thermal gate documented |

## 4. Verification boundaries

`guitar/tests/test_camera_opt_in.py` covers default/explicit/legacy camera flags, conflicting
flags, state-only tool behavior, input-aware prompts/specs, unavailable-audio handling, and
fake-session frame requests/backend inputs/JPEG records. Opt-in cases use mocked frames;
no real camera is opened. The existing motion/embodied suites exercise fakes and synthetic
signals, not physical qualification or a live model.

The camera change updates CLI/Toolbox defaults, prompt/spec wording, input-mode logging,
and example metadata; it does not change motion, grip settings, backend selection, mic
defaults, or provider deployment. No robot, microphone, camera, API, GPU deployment, or
training job is exercised by the offline checks. Update status with actual test/run evidence
as implementation progresses.

The separate file-only evaluator has 20 offline regression checks covering normalization,
provenance, explicit consent, schema failures, timeout behavior, and no Kimi/audio fallback.
They passed alongside the existing 71 camera/motion/embodied checks. A CLI local-inspection
check also passed without API/device access. These mocks do not establish audio-model quality.

The new orchestration suite adds 21 offline checks: actual fake-motion routing, pick/fret
preconditions, schema/call-ID rejection, no cleanup hiding a held fret, injected faults,
independent trace grading, budgets, expiry, provider errors, pacing, and no device-library
imports. The full suite passed 112 tests after the clock/protocol changes. With the web app, it now
passes **121 tests**, including Host/Origin/CSRF/consent checks, prompt propagation, event/history
access, path/symlink boundaries, custom-task validation, single-run ownership, pause/resume,
and cancellation of pending dispatch. A desktop/mobile browser check reported no JavaScript
errors or horizontal overflow. These results do not establish safe real-arm operation.
