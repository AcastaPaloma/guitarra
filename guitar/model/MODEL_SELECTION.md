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
| Local audio estimates | Web DSP v2 supplies source-bound, uncertainty-aware pitch/onset estimates to Inkling and Kimi; legacy mic/scorer remains separate. These are heuristics, not verified contact or timing accuracy. |
| Raw-audio evaluator | **Inkling on Baseten remains primary; Small is a bounded fallback.** Both passed approved synthetic audio requests with audio-token usage. Real guitar critique/optimization remains unvalidated. See [live evidence](audio-inference-check.json). |

Full `thinkingmachines/inkling` (not Small) was initially selected for combined reasoning
and documented audio support, but both normal and streaming inference requests timed out.
Kimi K3 then returned native tool calls successfully. This was connectivity troubleshooting,
not an accuracy bake-off or proof of an entitlement denial. A later approved synthetic
probe succeeded for full Inkling text/audio and Small audio with reasoning disabled;
the old timeout cause remains unproven. The audio adapter now defaults to that reasoning
setting and permits one Small fallback for transient failures within a bounded review.
Kimi's planner choice is separate. The operator accepts fallback and wants all hosted
inference on Baseten; no replacement deployment is proposed.

Kimi K3 itself is not a raw-audio model on the current Baseten surface. The separate
[file-based evaluator](AUDIO.md) implements consented requests with no motion tools,
validates PCM16 WAV files and resamples them to the documented 16 kHz input. The active
single-arm web app captures/exports browser audio and ingests the assessment; the legacy
CLI remains separate. Local pitch/onset estimates now reach both models, and the six
original DSP failures are passing regressions. The v2 grounding/null-score contract was
verified offline after the live v1 probe; no fourth request or real guitar review was
made. Neither an accepted WAV nor a fluent explanation proves note-quality accuracy or
mechanical diagnosis.

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
