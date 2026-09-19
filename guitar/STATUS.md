# Guitar implementation status and consistency audit

**Source-inspected snapshot, not a physical qualification report.** Requirements are in
[DESIGN.md](DESIGN.md); current operator facts and overrides are in [../AGENTS.md](../AGENTS.md).
Existing uncommitted code/config changes are preserved. This audit does not implement fixes.

## 1. What exists

| Component | Source evidence | Limit |
|---|---|---|
| Named guitar motions | [`motions.py`](motions.py), [`robot/arm.py`](robot/arm.py) | Fake by default in `motions.connect`; a stateful single-arm API, not a complete two-arm phrase executor |
| Fret pose map | [`robot/poses/fret_arm.json`](robot/poses/fret_arm.json), [`fretmap.py`](robot/fretmap.py) | 54 above/touch pairs across six strings/frets 1–9, including interpolation; not 54 physically qualified targets |
| Pick primitive | `Arm.pluck` | Requires `above_string`, `pluck_start`, `pluck_end`; the bundled fret map has none |
| Local guards | [`guards.py`](robot/guards.py) | Joint/speed/segment/drift/tracking checks; not complete collision/contact/force or thermal qualification |
| Agent loop | [`agent/loop.py`](agent/loop.py), [`tools.py`](agent/tools.py) | One role per run; fret role can wait for a human pluck; no whole-song/two-arm clock proven |
| Model adapters | [`backends/`](agent/backends/) | Astra, Claude, Baseten, and scripted adapters exist; CLI default remains `claude` |
| Baseten client | [`baseten.py`](agent/backends/baseten.py) | Custom `/predict` input/output contract over `urllib`; not a generic native Chat Completions client |
| Baseten package | [`config.yaml`](model/baseten_guitar_agent/config.yaml) | Qwen2.5-VL-7B/vLLM serving configuration; not evidence it loads/runs in a deployed environment |
| Baseten server adapter | [`model.py`](model/baseten_guitar_agent/model/model.py) | Added concurrently during this review; custom Truss `load`/`predict`, latest-image processing, transcript/prompt construction, and tool-call normalization; live behavior unverified |
| Camera | [`camera.py`](sense/camera.py), [`camera_relay.py`](sense/camera_relay.py) | Local relay captures a stream; models receive a reduced JPEG snapshot per observation |
| Microphone/scorer | [`mic.py`](sense/mic.py) | 44.1 kHz ring buffer and handcrafted pitch/onset/level heuristics; **not** a pretrained audio-model evaluator |
| Run log | `Recorder` in `agent/loop.py` | JSONL and image snapshots; no persisted per-attempt WAV/evaluator contract in this recorder |

No complete audio-evaluator feedback loop, qualified two-arm performance, fine-tuned model,
or successful Baseten deployment is established by these files. Historical notes of live
Astra/Claude requests are not a new Baseten validation result.

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
  request can block, and a multi-call response is not fully bounded by the remaining count
  before dispatch. An independent watchdog/strict admission/expiry layer is still needed.
- There is no demonstrated local protection monitor running independently during model
  waits; fresh-state/thermal checks and safe inter-attempt holding cannot be assumed.

### Baseten adapter exists; end-to-end behavior is unverified

A custom `model/model.py` appeared while this documentation was being reviewed. It was
source-inspected and left untouched. It implements the adapter previously missing from
the scaffold: client `system`/tool specs/text/image history become a vLLM prompt, and output
is normalized to top-level `text`, `tool_calls`, `stop`, and `usage`.

This is source-level contract alignment, not a live deployment/model-loading result.
JSON formatting is prompted rather than constrained by a decoder schema. The parser can
discard malformed calls or replace invalid arguments with an empty object; test these
cases explicitly rather than treating normalization as full admission. The server renders
the last 24 transcript entries and uses the most recent image, not streaming video/audio.
The client sends `generation.effort`, but the current server does not consume that setting.
Neither source code nor a YAML file establishes endpoint health, input compatibility,
complete-response reliability, or safe physical operation.

The client builds `/{environment}/predict` URLs and uses its configured auth scheme;
confirm the exact generated endpoint/auth rather than substituting Model API or custom
server URLs interchangeably. It has no raw-audio field, and Qwen2.5-VL is not an audio model.
See [model integration](model/README.md).

### Timing and sensing are estimates, not ground truth

- `_execute` can start `t_cmd` after an initial base-only phase; `duration_s` is rounded and
  includes a fixed settle sleep, not verified encoder-settled arrival.
- Commands are nominally 50 Hz and tracking checks about 10 Hz, not evidence of 5 ms accuracy.
- The microphone callback timestamps callback arrival and ignores callback status/ADC timing;
  capture waits have no independent timeout/retention validation in the inspected code.
- A reported “clean pluck,” “probably missed,” or “buzzed/snagged” explanation is a heuristic,
  not a validated acoustic classification or mechanical diagnosis.
- `--no-mic` disables capture but leaves audio-oriented prompts/tool descriptions and “judge
  from the camera” fallback text. A camera does not provide an acoustic measurement.

See [PLANNING.md](PLANNING.md) and [sense/README.md](sense/README.md) for the proposed fixes.

## 3. What changed in the documentation

| Previous conflict | Current interpretation |
|---|---|
| One-arm open-G chord strumming / π0.5 policy-server setup | Same two arms; default qualified guitar tools; no VLA server prerequisite |
| “Self-tuning” implies weight training | Plan/context revision during rehearsal; fine-tuning is separate, deferred research |
| Audio forbidden or a bespoke trained sound classifier required | Optional pretrained audio evaluator; capture/inference integration needed, no classifier training required |
| Baseten configuration described as a proven deployment | Client/server/config now exist; server arrival during review is recorded, with live compatibility and admission tests still outstanding |
| Pluck-role fake smoke command with no pluck map | Use non-motion endpoint fixtures/fret-map fake cases; do not claim absent poses exist |
| Camera feed treated as raw video/audio input to every model | Current client sends JPEG snapshots and text; verify each endpoint's modalities |
| Return-to-rest optimization presented as wholly new | Current fret-to-fret routing already avoids global rest; proposed gains must beat it |
| Onset count equated with strings/clean contact | Local estimates and model assessments carry uncertainty; no force inference |
| Lamp/band, simulator, or transcription work treated as guitar prerequisites | Explicit separate/reference material, not current scope |
| Ordinary connect/disconnect described as motion/torque-neutral | Actual side effects, mode mismatch, and thermal gate documented |

## 4. Verification boundaries

The targeted `guitar/tests/test_motions.py` suite uses fakes/mocks and checks callable
motion routing/validation, not model inference, camera/microphone devices, training, or
physical clearance. Run/test counts belong to the actual test invocation, not to a claim
that the intended system is complete.

No robot, microphone, camera, API, GPU deployment, or training job is exercised by this
Markdown cleanup. This author does not change source/config code; concurrent additions
are preserved and reflected above. Update status with actual test/run evidence as
implementation progresses.
