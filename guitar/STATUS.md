# Guitar implementation status and consistency audit

**Source/status snapshot, not a physical qualification report.** Baseten managed Kimi K3
now drives a fake-only orchestration runner; all four initial workflow cases passed in a
live paced batch. Hardware qualification remains outstanding. Audio work is parked. Requirements are in
[DESIGN.md](DESIGN.md); current operator facts and overrides are in [../AGENTS.md](../AGENTS.md).
Unrelated uncommitted work is preserved. The camera-off/input-policy change is implemented
and covered by offline tests; the other source/runtime gaps below are not fixed by that change.
**Camera input is off by default** in the CLI and Toolbox. Only explicit `--camera` enables
optional diagnostic snapshots; `--no-camera` keeps the default. Normal planning needs no images.

## 1. What exists

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

No complete audio-evaluator feedback loop, qualified two-arm performance, fine-tuned model,
or custom Baseten deployment is established. The live Kimi K3 result verifies managed provider
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
