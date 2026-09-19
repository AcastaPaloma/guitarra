# Agent loop — current code versus target rehearsal

[DESIGN.md](../DESIGN.md) owns the current guitar requirements: same two arms, defined
qualified tools, a pretrained planner, and optional pretrained audio assessment feeding
bounded plan revision. **That loop does not require weight fine-tuning.**

This directory has an earlier single-role implementation. It is not a completed two-arm
phrase scheduler, external audio-evaluator loop, or independent hardware watchdog.
[STATUS.md](../STATUS.md) lists remaining code gaps; this README does not fix them.

## Current data path

```text
Camera relay -> one JPEG snapshot --------+
Local mic heuristics -> text score -------+-> selected backend -> proposed tool calls
Arm summary -----------------------------+                         |
                                                                  v
                      local Toolbox -> Arm -> trajectory guards -> device driver
```

The selected backend sees text/images, not a continuous raw audio/video feed. The local
mic summary is not an external audio model's assessment. The current Baseten Qwen2.5-VL
configuration is not a raw-audio endpoint.

## Files and current behavior

| File | Role / limitation |
|---|---|
| [`loop.py`](loop.py) | CLI, one arm role, recorder, turn/time counters; defaults to `claude`; attempts rest in cleanup |
| [`tools.py`](tools.py) | Common tool specs and execution; numeric checks and motion guards, not full fresh-state/expiry/thermal admission |
| [`backends/astra.py`](backends/astra.py) | Astra Responses API adapter; separate provider from Baseten |
| [`backends/claude.py`](backends/claude.py) | Anthropic Messages adapter; separate provider from Baseten |
| [`backends/baseten.py`](backends/baseten.py) | Direct HTTP custom-predict client; requires matching server implementation |
| [`backends/scripted.py`](backends/scripted.py) | Fixed fake-test plan; not inference or autonomous learning |

Historical notes reported Astra/Claude API use. This review performs no live calls and
establishes no Baseten endpoint, physical improvement, or acoustic qualification.

### Tools

- Fret role: `fret(string, fret, press_mm, speed)`, `release(speed)`, `move_to`, `look`, `done`.
- Pluck role: `pluck(depth_mm, speed)`, `move_to`, `look`, `done`.
- Fret execution can wait for a human pluck when a microphone is enabled. That is not
  automatic coordination with a second arm.
- The supplied fret map has no plucking poses. A pluck-role fake run with its default
  `pluck_arm` map is not a valid smoke test of the bundled checkout.
- The model can request numeric depth/speed within API checks today. The intended rehearsal
  design must restrict adjustments to the operator-qualified subset/profiles; a broad
  software range is not physical permission to explore every value.

## Flags and provider selection

The CLI defaults to `--backend claude`, `--role fret`, and **real hardware unless
`--fake-arm` is supplied**. Select the provider explicitly; a Baseten setup file does not
change that default.

`--no-mic` and `--no-camera` disable those observation paths. They do not rewrite the
system/tool descriptions, which still assume audio feedback and contain overconfident
heuristic interpretations. Treat “judge from the camera” as missing audio evidence, not
an alternative acoustic measurement. Prompt/evidence-mode handling is a pending code fix.

`--turns` and `--minutes` are not independent watchdogs: checks occur between turns, after
calls execute, and do not bound every action in a response before dispatch. Model/network
work is synchronous. Do not describe those counters as a complete autonomous safety system.

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
guitar/.venv/bin/python -m pytest guitar/tests/test_motions.py guitar/tests/test_embodied.py -q
```

Synthetic audio tests test code on synthetic signals, not the real guitar or a model critic.
The recorder currently writes JSONL and JPEGs under `guitar/runs/`; it does not implement
persisted attempt-audio export, structured evaluator feedback, best-plan selection, or
validated replay. Those belong to the target [rehearsal loop](../REHEARSAL_LOOP.md).
