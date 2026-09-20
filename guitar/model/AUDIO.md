# Baseten audio review — Inkling plus local measurements

**Full Inkling is the primary evaluator; Inkling Small is the bounded fallback. All
hosted audio inference stays on Baseten.** Kimi remains the text/state planner. No new
model deployment, fine-tuning, camera or provider migration is needed.

## What is verified

The operator-approved **three-request / $0.10** synthetic diagnostic on 2026-09-20 passed:

| Request | HTTP | Elapsed | Audio input tokens |
|---|---:|---:|---:|
| Full Inkling, text control | 200 | 0.485s | 0 |
| Full Inkling, one-second generated WAV | 200 | 6.447s | 21 |
| Inkling Small, the same WAV | 200 | 3.272s | 21 |

Usage-based cost estimate: **$0.00175575**, using uncached catalog prices (not an invoice).
All requests used `reasoning_effort="none"`, bounded output, and a 90s diagnostic timeout;
none actually took 30s. **No fourth request** was made. [Sanitized live evidence](audio-inference-check.json).

This establishes current access and audio ingestion for those requests, not a definitive
cause of the older 30s timeouts. Reasoning depth, preview serving/routing and test time
all differed. The catalog's text/image-only metadata did **not** prevent audio inference.

**Quality remains limited:** the WAV contained two separated tones and no room noise.
Neither model accurately described the two events, and both mentioned room noise. The
old v1 coaching prompt also produced numeric scores despite having no performance target.
Do not use the model as a pitch detector, stopwatch or calibrated quality reward.

The subsequent **v2 grounding/null-score contract and runtime changes below are offline
verified**, not another live benchmark. This audio task used no real recording, microphone,
camera, robot, deployment or training, and made no server restart. Useful real-guitar optimization
still requires consented, supervised validation and the independent physical gates.

## Current single-arm flow

```text
completed take + validated browser WAV + plan + command telemetry
                              |
                  local acoustic estimates (v2)
                              |
        WAV + intended notes + estimates/uncertainty + capture quality
                              |
                   Inkling on Baseten
                   (one Small fallback on transient failure)
                              |
           uncertain assessment + local estimates + bounded history
                              |
                     Kimi proposes a revision
                              |
          local validation + separate operator-approved next Play
```

[`arm_controller/rehearsal.py`](../../arm_controller/rehearsal.py) passes the **same
source-bound estimates to both Inkling and Kimi**. A source-WAV SHA256 prevents attaching
another clip's measurements; nonfinite/oversized context is rejected before upload.
Local failure is disclosed as unavailable, not fabricated missed notes. The last three
attempts include compact, versioned acoustic summaries and reviewer identity, not old WAVs.

[`tap_audio_metrics.py`](../../arm_controller/tap_audio_metrics.py) detects energy rises
once across the clip and assigns them monotonically, one-to-one, using event identities.
It estimates independent monophonic pitch across several normalized-periodicity frames,
with sub-sample interpolation and abstention for clipping, short/unstable signals, weak
fundamental/octave ambiguity and semitone boundaries. Note identity is separate from
cents/tuning tolerance. Missing telemetry remains unknown and never removes planned rows.

These are **heuristics**, not a qualified guitar classifier or calibrated confidence.
Motor noise, overlapping/ringing strings and very quiet notes remain difficult. “Heard”
in stored compatibility fields counts attack candidates, **not verified guitar notes**;
the UI now labels them accordingly. “Clarity” is only level above estimated noise.

### Timing limits

Audio-relative onset positions/intervals are estimates within the recording. Browser,
server and input-device latency are **uncalibrated**. Encoder-ready offsets are not string
contact, rhythm error or command-to-sound delay. The current web plan has post-lift pauses,
not an intended acoustic beat schedule; it explicitly sends `timing_target_available=false`
even when DSP fails. Definitive timing-accuracy claims without that target are rejected.
`timing_error_ms`, absolute delay and the old “jitter” score remain null. No model or local
heuristic is permitted to invent a millisecond improvement or change mechanical limits.

## File interface and configuration

`model/audio.py` and `scripts/evaluate_audio.py` themselves open **no devices or motion tools**.
Selected input must be nonempty uncompressed PCM16 WAV, mono/stereo, at most **160s / 32 MiB**.
Common sample rates are supported; stereo is averaged and audio is polyphase-resampled to
16kHz mono for Baseten. The original file is not changed, played, trimmed or gain-normalized.
Source/upload hashes, processing, sample rates and separate signal estimates are recorded.

```dotenv
BASETEN_MODEL=moonshotai/Kimi-K3
BASETEN_AUDIO_MODEL=thinkingmachines/inkling
BASETEN_AUDIO_REASONING_EFFORT=none
BASETEN_AUDIO_TIMEOUT_S=30
```

Only the server/CLI reads `BASETEN_API_KEY` from ignored environment files. The audio-only
reasoning default is now **none**, matching the successful diagnostic; the planner's
reasoning setting is unchanged. Current audio output cap: **1,536 tokens**. No `.env`
credential/settings edit or live server restart was performed by this audio task.

One evaluation permits **at most two requests**: primary, then one Small fallback for a
transport failure or HTTP **408/429/500/502/503/504/529**. There is no same-model retry,
recursive fallback, alternate provider, or raw-audio routing to Kimi. Auth/billing/input
errors, invalid assessments and missing audio-token evidence do **not** trigger fallback.

The default per-request timeout is 30s. The evaluator has a **75s overall admission/result
budget**, further limited by the web manager's remaining review time; it reserves time
for fallback when capping a large configured timeout. Socket timeouts cannot cancel an
already-billed request. Stop/deadline checks block further requests and discard late
results, while the web watchdog remains independent. Each attempted model, failure class,
HTTP status where available, usage and elapsed time is recorded under `requests`; a
fallback report also has `model_fallback_from`. The UI shows the actual reviewer/fallback.
Startup does not make a health probe or display the old timeout as current provider status.

Baseten recommends clips under two minutes for Small; the 160s local cap is longer than
that best-results recommendation (not a claimed hard provider limit). Long-clip quality
and latency remain unvalidated. Keep real validation takes short; no automatic clip
chunking, extra requests or physical repeats are authorized by this software budget.

## CLI (repository root)

```bash
# Local validation only; no credentials, network, upload, playback or devices:
guitar/.venv/bin/python guitar/scripts/evaluate_audio.py --wav /path/to/take.wav --inspect

# Explicit upload/inference consent: primary plus at most one Small fallback.
guitar/.venv/bin/python guitar/scripts/evaluate_audio.py \
  --wav /path/to/take.wav --attempt-id take-001 \
  --expected 'Three A2 notes approximately one second apart' --allow-upload
```

The CLI does not invent telemetry-bound per-note metrics for an arbitrary file. It sends
file signal estimates plus the operator's intended phrase. The web manager supplies the
per-note metrics and explicitly reports the absence of an acoustic timing target.
Label generated clips `--source synthetic_fixture`. Default reports are ignored files
under `guitar/runs/audio/`; select a new `--output` when intentionally re-assessing a clip.
Existing reports are not overwritten. Never share recordings/reports without permission.

## v2 assessment contract

Required fields: `recording_quality`, `notes_match`, `timing_match`, `summary`,
`observations`, `limitations`, `score`, `suggestions`. `score` is now **integer 0–10 or
null**. Unusable/uncertain capture or both accuracy fields being unassessed requires null,
not zero. A non-null score is still an **uncalibrated model opinion**, not a reward or
proof of improvement. Prompts no longer instruct the model to prefer grading over uncertainty.

Only complete, tool-free, schema-valid JSON with positive audio-input-token usage is
accepted. Refusals, truncation, extra/duplicate keys, unsupported accuracy claims and
malformed responses produce `status: unavailable`, `assessment: null`. No compensating
motion follows an API or capture failure. The evaluator and planner must preserve
uncertainty and flag disagreements rather than automatically trusting either the model
or DSP. Mechanical diagnosis, grip/torque/calibration/clearance changes and automatic
replay remain prohibited. Human preference stays separate from model judgment.

See [investigation/history](AUDIO_INVESTIGATION.md), [current status](../STATUS.md),
[supervised rehearsal](../../arm_controller/REHEARSAL.md), [physical path gates](../../arm_controller/PATHS.md)
and [operator rules](../../AGENTS.md). Baseten references:
[audio](https://docs.baseten.co/inference/model-apis/audio),
[reasoning](https://docs.baseten.co/inference/model-apis/reasoning).
