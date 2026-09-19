# Guitar setup — current workflow

Follow [DESIGN.md](DESIGN.md) for scope and [STATUS.md](STATUS.md) for actual implementation.
This replaces the older one-arm/Open-G/π0.5/GPU-policy-server startup plan.
No weight training, new sound classifier, physics simulator, or extra robot is required.

## 1. Start with existing offline tests

All commands in this document start at the **guitarra repository root** unless stated.
Use the existing isolated `guitar/.venv/` where available:

```bash
guitar/.venv/bin/python --version
guitar/.venv/bin/python -m pytest guitar/tests/test_motions.py -q
```

If setting up another machine, first review/pin an appropriate driver/dependency version.
The current guitar package declares **Python >=3.12**, not the obsolete Python 3.10 path
in the old setup notes. For an absent environment, the package installation pattern is:

```bash
uv venv --python 3.12 guitar/.venv
uv pip install --python guitar/.venv/bin/python -e 'guitar[dev]'
```

This installs software; it does not qualify hardware or require opening a serial port.
Do not recreate an existing hardware environment casually or import `scripts/` as tests.
`motions.connect()` defaults to fake execution; see [MOTIONS.md](MOTIONS.md) for its actual API.

## 2. Resolve physical setup with the operator

Use the same arms. Follow [CONNECT.md](CONNECT.md) and the authoritative
[operator instructions](../AGENTS.md): verify the current mapping, units, pose/calibration
pairing, stop/holding behavior, and gripper thermal/configuration issue before connection.
Do not renumber motors, restore old calibration blindly, open the grippers, or use a
large sweep merely because an older example says to do so.

The supplied map does not include a plucking trajectory. Qualify the needed pick/fret
subset and local coordination before promising two-arm songs or autonomous repetitions.

## 3. Resolve Baseten separately from motion

A client, Qwen2.5-VL configuration, and custom server adapter now exist. Test the complete
request/response path, dependency/model loading, and deployed endpoint before presenting a
push or smoke command as successful. Source code alone is not live inference evidence.
[model/README.md](model/README.md) owns the current contract and validation requirements.

Live inference needs approved credentials/spend. Deployment can incur idle GPU cost and
is not a routine setup step. Do not silently use the CLI's current default backend
(`claude`) when the intent is to demonstrate Baseten; select the provider explicitly.

Astra/Claude are alternatives, not assumed Baseten models. API keys stay in the shell or
ignored secret files, never in docs, logs, screenshots, or model context.

## 4. Add observation and evaluation only when needed

Camera and microphone access are opt-in external actions. The existing agent enables
capture unless `--no-camera` / `--no-mic` is passed; those flags do not rewrite its older
prompt assumptions. Read [agent/README.md](agent/README.md) before using that CLI.

Current sensing provides JPEG snapshots and local acoustic heuristics. The optional
pretrained audio evaluator still needs recording/export, an audio-capable endpoint, and
a bounded assessment interface. Qwen2.5-VL does not accept raw microphone audio. See
[sense/README.md](sense/README.md). No training dataset is needed just to try that loop.

## 5. Build the intended rehearsal path

After the relevant software and physical checks:

1. Prepare a supported short phrase and one fully validated attempt.
2. Execute with a local clock, not one cloud request per note.
3. Record actual observations/telemetry; optionally obtain a pretrained audio assessment.
4. Give the planner the previous outcomes and let it revise one permitted choice.
5. Re-admit the new plan against fresh state; stop at the budget or any fault/uncertainty.
6. Save the best validated plan and evidence explicitly, without changing model weights.

The current single-role CLI is not a completed implementation of this sequence. Neither
its automatic rest cleanup nor a model response is an independent stop/watchdog.
[REHEARSAL_LOOP.md](REHEARSAL_LOOP.md) owns this target behavior.

## 6. What not to set up for the current milestone

Do not provision a π0.5/ACT/Diffusion server, launch H100 training, build a string-physics
simulator, integrate the old transcriber, or add lamp/band performers as prerequisites.
[FINETUNING.md](FINETUNING.md) is deferred research, not part of startup.
