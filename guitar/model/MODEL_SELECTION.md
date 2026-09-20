# Model decision — quality-first hackathon planner

## Use Kimi K3 now

**`moonshotai/Kimi-K3` on Baseten Model APIs, with `reasoning_effort=high`.**
The operator requested a powerful model immediately, not a small-model cost experiment
or a benchmarking program. The previous Qwen2.5-7B recommendation is superseded.

Kimi K3 is our flagship choice available through Baseten's current managed catalog. Native
tool calls, reasoning, and the tool-result continuation path were verified live; see
[connection-check.json](connection-check.json). There is no claim it universally beats
all other models or is already qualified to operate this guitar.

Using an already-hosted Model API avoids building/downloading a large custom checkpoint,
GPU provisioning, and unnecessary deployment latency. There is **no private deployment ID**
to find or create. Use `BASETEN_MODEL=moonshotai/Kimi-K3`, not `BASETEN_MODEL_ID`.

## What it is for

- Propose supported notes/phrases and qualified tool/profile choices.
- Reason over goal, arm state, capabilities, past tool results, and attempt feedback.
- Interpret local audio summaries or a future evaluator's textual assessment.
- Request inspection or stop when observations/capabilities are insufficient.

It does not own raw motor paths, millisecond scheduling, calibration, grip settings,
safety limits, or executable code. Local code remains authoritative. There is no fine-tune.

## Modalities are separate from model strength

| Role/input | Current choice/status |
|---|---|
| Text/state planner | **Kimi K3, live synthetic tool round trip verified** |
| Camera | Off by default and unnecessary. Kimi supports optional images, but this was not exercised. |
| Local audio estimates | Existing mic/scorer may provide text summaries; not raw-audio understanding. |
| Raw-audio evaluator | Inkling on Baseten remains primary; Small is an accepted bounded fallback. Single-arm web integration exists; acoustic quality remains unverified. The old full-model probe timed out, but current authenticated metadata confirms both models are already in the workspace. See [investigation](AUDIO_INVESTIGATION.md). |

Full `thinkingmachines/inkling` (not Small) was initially selected for combined reasoning
and documented audio support, but both normal and streaming inference requests timed out.
Kimi K3 then returned native tool calls successfully. This was connectivity troubleshooting,
not an accuracy bake-off or proof of an entitlement denial. The **audio adapter now has
one Small fallback after a full-model transport timeout**; Kimi's planner choice is separate.
The operator explicitly accepts that fallback and wants all hosted inference on Baseten.
No replacement deployment is proposed by the current audio investigation.

Kimi K3 itself is not a raw-audio model on the current Baseten surface. The separate
[file-based evaluator](AUDIO.md) implements consented requests with no motion tools,
validates PCM16 WAV files and resamples them to the documented 16 kHz input. The active
single-arm web app captures/exports browser audio and ingests the assessment; the legacy
CLI remains separate. Preliminary local pitch/onset estimates reach Kimi, not yet Inkling,
and have documented regression failures. Neither an accepted WAV nor a fluent explanation
proves accurate note-quality assessment or a mechanical diagnosis.

## Evidence and limits

- Baseten's authenticated catalog listed Kimi K3, reasoning, tool support, and a 1,048,576-token
  context window. This client requests at most 8,192 output/reasoning tokens by default.
- The synthetic `look` → result → `done` round trip took **2.27 seconds across two requests**.
  This is one connectivity check, not a latency benchmark or physical execution measurement.
- The schema/finish-state checks reject malformed, unknown, or multiple tool calls before
  dispatch. Existing camera-off/fake-motion regression suites passed offline.
- Raw-audio, visual reasoning, coordinated two-arm playing, musical improvement, and thermal
  qualification are **not** established by the connection check.

## Sources

- [Baseten model catalog and feature support](https://docs.baseten.co/inference/model-apis/overview)
- [Reasoning controls](https://docs.baseten.co/inference/model-apis/reasoning)
- [Audio models](https://docs.baseten.co/inference/model-apis/audio)

Follow [DESIGN.md](../DESIGN.md) for requirements and [STATUS.md](../STATUS.md) for outstanding
hardware/coordination/evaluation work. No more model comparison is required to start building
the local tool interface against this working planner.
