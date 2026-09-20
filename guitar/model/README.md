# Baseten planner — Kimi K3, live managed inference

**Active model: `moonshotai/Kimi-K3`, reasoning effort `high`.** This is a Baseten-hosted
Model API, not an OpenAI service and not our own Truss deployment. No GPU build, dedicated
model ID, or weight training is needed. Camera remains off by default.

A live native tool-call round trip passed on 2026-09-19: `look` → synthetic state → `done`,
2.27 seconds across two requests. See [connection-check.json](connection-check.json).
No robot, camera, microphone, audio upload, or tool dispatcher was used. This demonstrates
provider/continuation compatibility, **not** physical qualification or guitar skill.

The next milestone is now working: [fake orchestration](../orchestration/README.md) runs
real Baseten decisions through the existing `Motions`/`FakeArm` tools and a synthetic pick.
All four initial workflow cases passed live. The [web console](../web/README.md) now provides
prompt/note editing, fake run controls, and history at http://127.0.0.1:8787. A browser-submitted
Baseten workflow also passed. Audio work is parked; no audio call is needed.

```bash
# From guitar/:
.venv/bin/python -m orchestration --allow-inference
```

## Configuration

Put these settings in `guitar/.env` (ignored by Git). Existing nonempty environment values
win, then `guitar/.env`, then the repository-root `.env`. `BASETEN` remains a key alias.

```dotenv
BASETEN_API_KEY=your_key_here
BASETEN_MODEL=moonshotai/Kimi-K3
BASETEN_REASONING_EFFORT=high
BASETEN_MAX_TOKENS=8192
BASETEN_TIMEOUT_S=180
```

The key is never sent in model context. The client uses:

- URL: `https://inference.baseten.co/v1/chat/completions`
- Authentication: `Authorization: Bearer <Baseten key>`
- Native Chat Completions `messages`, `tools`, and `tool_calls`.

**`BASETEN_MODEL_ID`, `BASETEN_MODEL_URL`, and `BASETEN_ENV` are not used by this path.**
Those settings belonged to the earlier custom Truss adapter. The exact managed model name
is the slug above. An empty list of private deployments does not mean Model APIs are unavailable.

## Commands — from the repository root

```bash
# Installs the extra local JSON Schema validator, without installing a GPU runtime.
guitar/.venv/bin/python -m pip install 'jsonschema>=4.23,<5'

# Configuration only; no inference or devices.
guitar/.venv/bin/python guitar/scripts/baseten_setup.py status

# Read-only managed catalog lookup using .env credentials.
guitar/.venv/bin/python guitar/scripts/baseten_setup.py models

# Two billed, synthetic tool-call requests. No devices and no tool dispatch.
guitar/.venv/bin/python guitar/scripts/baseten_setup.py smoke --yes
```

No `truss login` or `truss push` is required. The script works from any current directory;
from `guitar/`, use `.venv/bin/python scripts/baseten_setup.py ...`.
The agent CLI now defaults to `--backend baseten`; `--model` overrides the **managed slug**.
Use `--fake-arm --no-mic` for device-free agent work. The legacy CLI still defaults to real
hardware when an arm session is started; do not use it as a provider connectivity check.

## What the model does

```text
Goal + qualified capabilities + state + attempt history + text audio summaries
    → Kimi K3 on Baseten
    → one proposed native tool call
    → local schema validation, motion guards, and execution authority
```

This is pretrained inference and in-context plan revision, not fine-tuning. Numerical
scheduling, path selection, readiness, gripper/protection policy, and attempt budgets remain
local. [DESIGN.md](../DESIGN.md), [STATUS.md](../STATUS.md), and [AGENTS.md](../../AGENTS.md)
retain authority over scope and physical use.

The client rejects unknown tools, malformed/duplicate-key/nonfinite argument JSON,
schema violations, repeated call IDs, multi-call responses, and truncated responses before
returning any call to the dispatcher. It preserves native call IDs and provider continuation
fields. It does not repair bad arguments or automatically retry/fall back to another model.
These checks are not a physical safety certificate or an independent hardware watchdog.

## Audio and optional images

- **Current planner input is text/state.** Local microphone pitch/onset/level summaries,
  when enabled, are text observations—not evidence the planner heard a recording.
- **Kimi K3 is not documented as accepting raw audio on Baseten.** It supports text and
  optional image inputs; no image is fetched/sent without explicit camera opt-in.
- The optional **file-based evaluator is now implemented** in `audio.py`, with explicit
  upload consent, PCM16 WAV validation/resampling, a bounded assessment schema, and no tools.
  It is not automatically invoked by the planner or legacy mic loop.
- Full `thinkingmachines/inkling` is the primary audio reviewer with one bounded Small
  fallback for transient errors. An approved three-call/$0.10 synthetic check passed
  full text/audio and Small audio with reasoning disabled; both audio calls reported
  audio-token usage. [Evidence](audio-inference-check.json). The old timeout is historical,
  not proof of denied access; real-guitar accuracy/optimization remains unvalidated.
- The single-arm web loop now feeds source-bound local pitch/onset estimates to **both**
  Inkling and Kimi. v2 permits unknown/null scores and keeps timing uncertainty explicit.
  This revised contract was tested offline after the live v1 probe, not with another
  recording or paid call. See [AUDIO.md](AUDIO.md) for limits, commands and validation
  boundaries. ASR and fluent model feedback are not validated guitar critique.

## Files and the older scaffold

| File | Purpose |
|---|---|
| `baseten.py` | Shared .env loader and direct HTTP managed-API transport; no device imports |
| `../agent/backends/baseten.py` | Active planner adapter: native tools, argument validation, continuation |
| `../scripts/baseten_setup.py` | Status, catalog lookup, and synthetic connection check |
| `audio.py`, `../scripts/evaluate_audio.py` | Opt-in WAV evaluator; file normalization and structured feedback, no device access |
| `AUDIO.md`, `audio-inference-check.json` | Current grounded audio setup and successful, explicitly synthetic connectivity evidence; the older `audio-connection-check.json` timeout is retained as history |
| `connection-check.json` | Non-secret evidence of the live synthetic tool round trip |
| `MODEL_SELECTION.md` | Current quality-first selection and capability boundaries |
| `baseten_guitar_agent/` | **Inactive, unvalidated** Qwen2.5-7B custom Truss recipe retained for reference |
| `../agent/backends/baseten_custom.py` | Previous custom `/predict` contract; explicit `baseten-custom` backend only |

The old `/predict` contract is not native Chat Completions and is not used as a fallback.
Do not push that older recipe expecting it to deploy Kimi K3. Dedicated deployment is a
separate decision; the hackathon path is the already-hosted flagship API.

## Sources

- [Model APIs and supported models](https://docs.baseten.co/inference/model-apis/overview)
- [Reasoning parameters](https://docs.baseten.co/inference/model-apis/reasoning)
- [Native tool calling](https://docs.baseten.co/inference/function-calling)
- [Audio models and input requirements](https://docs.baseten.co/inference/model-apis/audio)

The live catalog listed Kimi K3 at $3/million input tokens and $15/million output tokens
at setup time; reasoning contributes to output usage. Prices/availability can change.
No dedicated idle GPU was provisioned.
