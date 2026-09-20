# Guitar setup — current workflow

Follow [DESIGN.md](DESIGN.md) for scope and [STATUS.md](STATUS.md) for actual implementation.
This replaces the older one-arm/Open-G/π0.5/GPU-policy-server startup plan.
No weight training, new sound classifier, physics simulator, or extra robot is required.
**Camera input is off by default; no relay or vision model is needed for the normal path.**

## 1. Start with existing offline tests

All commands in this document start at the **guitarra repository root** unless stated.
Use the existing isolated `guitar/.venv/` where available:

```bash
guitar/.venv/bin/python --version
guitar/.venv/bin/python -m pytest guitar/tests/test_camera_opt_in.py guitar/tests/test_motions.py -q
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

The active path is **Kimi K3 on Baseten's managed Model API**, with high reasoning. A live
synthetic tool/result round trip passed; it did not execute hardware or inspect media.
Set `BASETEN_API_KEY` and `BASETEN_MODEL=moonshotai/Kimi-K3` in `.env`; no Truss push or
private deployment ID is needed. [model/README.md](model/README.md) has exact commands.
The older Qwen2.5 custom deployment recipe is inactive and unvalidated, not the current setup.

Live inference consumes approved account credits. The CLI now defaults to `baseten`, not
`claude`; select alternatives explicitly. A dedicated GPU deployment is a separate decision
and can incur idle costs. No dedicated GPU has been provisioned for this managed path.

Astra/Claude are alternatives, not assumed Baseten models. API keys stay in the shell or
ignored secret files, never in docs, logs, screenshots, or model context.

### Current single-arm tap/rehearsal web console

```bash
# From the repository root; no device or model access at startup:
guitar/.venv/bin/python arm_controller/webapp.py --port 8788
```

Open **http://127.0.0.1:8788**. This is the pulled **real single-arm tap app**,
not the older fake console below. See [arm_controller/REHEARSAL.md](../arm_controller/REHEARSAL.md)
for browser mic consent, one bounded audio/model review, a proposed diff, and a
separate operator-approved Play. No automatic physical replay or camera input.

Current motion blocker: the v4 map has **25 contact keys but no per-key hovers or
lift-first path qualification**. The web player now refuses contact-only rest/row-hub
routes rather than repeating the reported diagonal/scraping-prone motion. See
[PATHS.md](../arm_controller/PATHS.md) for whole-phrase preview, named lift/hover paths,
and the pending second tap arm's dedicated rows 7–11 (not enabled). No old map is restored.
Physical/thermal qualification and live audio verification remain unresolved; see
[STATUS.md](STATUS.md) and [audio setup](model/AUDIO.md).
Current clean web completion parks via a reviewed final exit and **holds body torque**;
faults release body torque without recovery motion, force stop holds frozen goals.
Support the body and respect protection; no independent thermal watchdog is supplied.
Tool-gripper 12 is never commanded. New/offline checks:

```bash
guitar/.venv/bin/python -m pytest arm_controller/tests guitar/tests -q
```

### Older local web console (fake tools only, separate app)

```bash
# From repository root; this leaves the parent shell's working directory unchanged.
(cd guitar && .venv/bin/python -m web --port 8787)
```

Open **http://127.0.0.1:8787** to edit prompts/notes, start an explicitly approved Baseten run,
inspect live fake state/tool results, use cooperative pause/stop, and download logs.
Credentials stay server-side in `.env`; startup/page loading makes no inference request.
There is **no hardware adapter or unlock switch**, and the Stop button is not a physical E-stop.
See [web/README.md](web/README.md) for dependencies, local security, and commissioning gates.

### Current fake-only CLI entry point

With the existing `.env` key, run real inference without devices:

```bash
cd guitar
.venv/bin/python -m orchestration --allow-inference
# Or the initial four workflow cases:
.venv/bin/python -m orchestration --scenario all --allow-inference
```

This runner calls the existing motion code on a fake fret arm and an explicitly synthetic
pick fixture. It has **no hardware option** and never captures media. Audio work is parked.
It records decisions/results and independently checks the workflow. Read
[orchestration/README.md](orchestration/README.md) for request pacing and validation limits.

## 4. Add observation and evaluation only when needed

| Input | Current default and controls |
|---|---|
| Camera | **Off.** No relay requests, attached images, or JPEG recordings in the default path. `--camera` is explicit diagnostic opt-in; `--no-camera` explicitly keeps it off. The two flags are mutually exclusive. |
| Microphone | Legacy local capture is still on unless `--no-mic` is supplied. This camera change does not alter microphone defaults; use `--no-mic` for device-free tests. |

Prompts and tool descriptions now reflect the selected inputs. A state-only `look()` does
not fetch an image. Neither camera flag starts a relay or stops other camera software.
Device access/media upload still require approval. Read [agent/README.md](agent/README.md).

The normal path needs state/text plus available audio feedback, not a vision model. Current
microphone code provides local heuristics. A separate [file-based evaluator](model/AUDIO.md)
provides explicit WAV upload and a bounded assessment interface. Approved synthetic checks
now verify full Inkling and Small audio access with reasoning disabled; they do **not**
qualify guitar critique. The single-arm `arm_controller/` app feeds the clip and local
confidence-aware pitch/onset estimates to Inkling, then a bounded proposal to Kimi, with
persistent session/audio/tuning history and operator-started Next Take. The revised v2
feedback contract is offline-tested, not real-guitar-qualified. The older CLI/fake
orchestration still lacks that integration; supervised acoustic validation remains.
The configured Kimi planner cannot accept raw microphone audio. See
[sense/README.md](sense/README.md). No training dataset is needed for the rehearsal loop.

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
