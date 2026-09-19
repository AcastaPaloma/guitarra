# Agent loop — current code versus target rehearsal

[DESIGN.md](../DESIGN.md) owns the current guitar requirements: same two arms, defined
qualified tools, a pretrained planner, and optional pretrained audio assessment feeding
bounded plan revision. **That loop does not require weight fine-tuning. Camera input is
off by default; the normal planner is text/state-based, with available audio feedback.**

This directory has an earlier single-role implementation. It is not a completed two-arm
phrase scheduler, external audio-evaluator loop, or independent hardware watchdog.
For the current real-inference/fake-tool milestone, use [orchestration/](../orchestration/README.md)
instead: it has no hardware option and has passed four initial live workflow cases.
[STATUS.md](../STATUS.md) lists remaining physical/controller gaps.

## Current data path

```text
Arm summary + available local audio estimates
                    |
                    v
Selected backend -> proposed tool calls
                    |
                    v
Local Toolbox -> Arm -> trajectory guards -> device driver

Optional only with --camera: separately started relay -> JPEG snapshot
```

Default runs do not request camera frames, attach images, or write JPEGs. `--camera` can
add snapshots for optional diagnostics, not a continuous raw video feed. The local mic
summary is not an external audio model's assessment. The Baseten planner is text/state;
no visual capability is required, and it is not a raw-audio endpoint.

## Files and current behavior

| File | Role / limitation |
|---|---|
| [`loop.py`](loop.py) | CLI, one arm role, recorder, turn/time counters; defaults to `baseten` (Kimi K3); attempts rest in cleanup |
| [`tools.py`](tools.py) | Common tool specs and execution; numeric checks and motion guards, not full fresh-state/expiry/thermal admission |
| [`protocol.py`](protocol.py) | Lightweight tool messages shared with orchestration; no device imports |
| [`backends/astra.py`](backends/astra.py) | Astra Responses API adapter; separate provider from Baseten |
| [`backends/claude.py`](backends/claude.py) | Anthropic Messages adapter; separate provider from Baseten |
| [`backends/baseten.py`](backends/baseten.py) | Active Baseten Model API adapter; native tool calls, one-call cap, schema validation, and continuation |
| [`backends/baseten_custom.py`](backends/baseten_custom.py) | Inactive custom Truss `/predict` adapter, available only as `baseten-custom` |
| [`backends/scripted.py`](backends/scripted.py) | Fixed fake-test plan; not inference or autonomous learning |

A live Baseten Kimi K3 synthetic tool round trip now passed; see
[connection evidence](../model/connection-check.json). No devices or real tools were executed.
That establishes provider compatibility, not physical improvement or acoustic qualification.

### Tools

- Fret role: `fret(string, fret, press_mm, speed)`, `release(speed)`, `move_to`, `look`, `done`.
- Pluck role: `pluck(depth_mm, speed)`, `move_to`, `look`, `done`.
- `look()` reads arm state without motion. By default it is **state-only**; it asks for an
  optional snapshot only in an explicitly camera-enabled session.
- Fret execution can wait for a human pluck when a microphone is enabled. That is not
  automatic coordination with a second arm.
- The supplied fret map has no plucking poses. A pluck-role fake run with its default
  `pluck_arm` map is not a valid smoke test of the bundled checkout.
- The model can request numeric depth/speed within API checks today. The intended rehearsal
  design must restrict adjustments to the operator-qualified subset/profiles; a broad
  software range is not physical permission to explore every value.

## Flags and provider selection

The CLI now defaults to `--backend baseten` (managed Kimi K3), `--role fret`, and still
**real hardware unless `--fake-arm` is supplied**. Baseten uses `BASETEN_MODEL` (catalog slug)
and `.env` credentials; there is no private deployment ID on this path. Use the provider-only
smoke helper in [model/README.md](../model/README.md) for connectivity, not a hardware session.

**Camera is off by default**, including when constructing `Toolbox` directly.
`--camera` explicitly enables snapshot requests; `--no-camera` keeps them disabled and
remains compatible with old commands. Passing both is an argument error before startup.
Neither flag launches the relay or changes other running camera programs.

Microphone behavior is unchanged: capture remains enabled unless `--no-mic` is supplied.
Prompts and tool descriptions now reflect both input modes. With no mic, the result says
that acoustic measurement is unavailable—it never tells the model to judge sound from an
image. Initial observations/logs record the selected modes. Use `--fake-arm --no-mic` for
a device-free scripted test; no `--no-camera` flag is needed for the default.

`--turns` and `--minutes` are not independent watchdogs: checks occur between turns, after
calls execute. The active Baseten adapter rejects multiple calls per response, but other
backends still need their own admission review. Model/network work is synchronous. Do not describe those counters as a complete autonomous safety system.

## Stop, connection, and clamp behavior

Before hardware use, read [../../AGENTS.md](../../AGENTS.md) and
[CONNECT.md](../CONNECT.md). The operator's current live grip setting, code default mismatch,
thermal history, and grip-reassertion behavior require review before repetition.

- `RealArm` constructed by this CLI retains its legacy speed-base default. The callable
  [motion API](../MOTIONS.md) chooses position mode explicitly; they are not identical paths.
- The loop currently attempts `arm.rest()` in `finally`, including error/interrupt paths,
  then disconnects. This can command motion; it is **not** an independent emergency stop.
- The callable motion context instead disconnects without an automatic return-to-rest.
- Ordinary disconnect releases body torque while retaining the tool grip; support the arm.
  Thermal/electrical emergencies may require grip power removal under the operator policy.
- Never open grippers, restore calibration, increase torque, or bypass protection as a
  routine agent startup or recovery step. No maintenance command is part of this README's
  default workflow.

## Runtime setup and tests

[SETUP.md](../SETUP.md) owns software setup, [model/README.md](../model/README.md) owns the
Baseten contract, and [sense/README.md](../sense/README.md) owns input/evaluator details.
Do not paste an old hardware launch command before resolving the qualification gates.

The reviewed offline suites use fakes/mocks, no model calls, and no device capture:

```bash
# From the guitarra repository root
guitar/.venv/bin/python -m pytest guitar/tests/test_camera_opt_in.py guitar/tests/test_motions.py guitar/tests/test_embodied.py -q
```

Synthetic audio tests test code on synthetic signals, not the real guitar or a model critic.
The recorder writes JSONL under `guitar/runs/` and JPEGs only for explicitly opted-in
frames. The camera regression suite uses mocked frames; it never opens a camera.
The recorder does not implement
persisted attempt-audio export, structured evaluator feedback, best-plan selection, or
validated replay. Those belong to the target [rehearsal loop](../REHEARSAL_LOOP.md).
