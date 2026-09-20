# Optional file-based audio evaluator

**Inkling on Baseten is the primary audio evaluator; a bounded Inkling Small fallback is
acceptable to the operator.** Treat preview reliability separately from musical accuracy.
The old full-model `audio_url` probe timed out after 30s on a one-second synthetic WAV;
that was **not an access-denied response**. See [audio-connection-check.json](audio-connection-check.json).

The [2026-09-20 access investigation](AUDIO_INVESTIGATION.md) authenticated successfully,
confirmed **both models already added to the workspace**, and found existing Small token
usage. Public docs support audio, but the authenticated catalog currently omits audio from
both models' modality lists. These metadata checks do not settle the discrepancy or prove
successful guitar assessment. A bounded, budget-approved inference probe remains pending.
[Sanitized evidence](audio-access-check.json) contains no credentials or media. Kimi remains
the text/state planner; no new model deployment or provider migration is proposed.

**Single-arm web integration now exists:** [arm_controller/REHEARSAL.md](../../arm_controller/REHEARSAL.md)
uses a consented browser AudioWorklet to capture a bounded take, then calls this file
adapter and feeds a valid assessment to a bounded Kimi revision proposal. It never
replays automatically. Preliminary local pitch/onset metrics are computed first and fed
to the planner, but **not yet to Inkling**. They have six reproducible known defects; see
[the investigation and offline regressions](AUDIO_INVESTIGATION.md). The intended next step
is confidence-aware local measurements plus the clip in Inkling's context, not replacing
Inkling or treating deterministic estimates as infallible. No new live assessment or
user-media upload is claimed here. The older `guitar/web` fake console and legacy recorder
remain separate.

## The interface

`model/audio.py` reads **one operator-selected file**, validates it, converts it to a 16 kHz
mono WAV, and optionally submits it to Baseten. `scripts/evaluate_audio.py` is the CLI.
Neither module imports/opens robot drivers, cameras, microphones, or motion tools.

Accepted input: uncompressed **16-bit PCM WAV**, mono or stereo, nonempty and no longer
than 160 seconds / 32 MiB. Common rates including 16, 44.1, and 48 kHz are supported.
Other formats (M4A/MP3/float WAV/24-bit WAV) must be exported as PCM16 WAV first.
Stereo is averaged and sample rates are converted with an antialiasing polyphase filter.
There is no trimming, gain normalization, playback, or modification of the original file.

Preparation records source/upload hashes, sample rates, duration, preprocessing, and separate
local signal-level estimates. The loader does **not** verify when/where a clip was recorded
or whether its claimed attempt ID matches a real performance. Supply that provenance honestly.
The new web manager separately binds one clip to a completed attempt/capture ID and
stores browser sample-frame metadata. Its `browser_microphone` source label is a browser
attestation, not independent device/provenance or hardware-timebase verification.

## Commands (repository root)

```bash
# On another environment, install these CPU-only extras:
guitar/.venv/bin/python -m pip install 'jsonschema>=4.23,<5' 'numpy>=1.26,<3' 'scipy>=1.13,<2'

# Inspect a selected file locally. No .env reading, API request, or media upload.
guitar/.venv/bin/python guitar/scripts/evaluate_audio.py \
  --wav /path/to/take.wav --inspect

# Explicit consent to upload THIS recording; primary + at most one Small fallback.
guitar/.venv/bin/python guitar/scripts/evaluate_audio.py \
  --wav /path/to/take.wav \
  --attempt-id take-001 \
  --expected 'Three A2 notes, approximately one second apart' \
  --allow-upload
```

Use a short, already permissioned guitar recording (a hand-played clip is sufficient to
start; no robot run is required). Describe the intended notes/timing, not what you assume
actually sounded. Label generated inputs with `--source synthetic_fixture`.

The default report goes to ignored `guitar/runs/audio/<attempt-id>.json`; use `--output`
to choose a new JSON path. Existing reports are not overwritten. A full-model transport
failure can trigger one Small request, recorded as `model_fallback_from`; HTTP failures
and invalid assessments are not retried. To intentionally re-assess a clip, preserve its attempt ID
and choose a distinct output filename. Reports do not contain waveform/base64 bytes,
local file paths, credentials, or private model reasoning. They do contain the intended
phrase and assessment, so keep user-recording reports private unless sharing is approved.

## Separate configuration from the planner

```dotenv
# Existing planner stays unchanged:
BASETEN_MODEL=moonshotai/Kimi-K3

# Optional evaluator only. No capture or upload is enabled by these settings.
BASETEN_AUDIO_MODEL=thinkingmachines/inkling
BASETEN_AUDIO_TIMEOUT_S=30
```

Both use `BASETEN_API_KEY` from the ignored `.env`. The evaluator sends a non-streaming
request with high reasoning and a 4,096-token output budget. After a no-status transport
failure/timeout from full Inkling it can make **one additional request to Inkling Small**,
with the same timeout. This is existing source behavior, not a new change made by the
investigation. The returned report names the actual model and fallback origin. HTTP errors,
malformed assessments, and missing audio-token evidence do not currently trigger fallback.
It never routes raw audio to Kimi or another provider. Raising the timeout also requires
review of the web manager's total stage budget; do not silently outwait that deadline.

## Assessment contract

Successful, complete responses must satisfy a versioned JSON schema containing:

- `recording_quality`: usable / limited / unusable / uncertain.
- `notes_match`, `timing_match`: consistent / inconsistent / uncertain / not_assessed.
- `summary`, bounded `observations`, and mandatory `limitations`.
- `score` (integer 0–10) and `suggestions` are currently required by the source schema.
  This is an **uncalibrated model opinion**, not a deterministic quality score. The current
  prompt's pressure to grade even uncertain audio is an investigation finding, not a
  guarantee that a score is supported. Future contract work should permit abstention.

The request has **no tools**. Tool calls, refusals, truncation, malformed JSON, extra fields,
duplicate keys, and ratings from unusable audio are rejected. Positive audio-token usage
must also be reported before the client marks an assessment as received. Missing usage
keeps the audio path unverified rather than pretending the model heard the clip.

A successful report has `status: assessed`. This means a schema-valid model assessment was
received, **not** that the guitar performance succeeded. On network/provider/response failure:

```json
{"status": "unavailable", "assessment": null}
```

A timeout is not a negative music score and must not trigger a compensating motor action.
Reports have `motion_authority: false` and `is_physical_qualification: false`.

## What is still next

1. Run the bounded, approved Baseten diagnostic to distinguish preview access, request
   handling, and latency. Workspace addition/authentication are already confirmed;
   metadata alone is not an audio inference test.
2. Fix/qualify the local measurements, pass them to Inkling with uncertainty, then assess
   a short consented recording and review its usefulness with the operator.
3. Review the new single-arm web ingestion of assessments as **untrusted data**, with separate
   telemetry and explicit operator approval of locally validated proposals. It is not wired
   into the older CLI/two-arm runner and cannot automatically replay a robot.
4. Qualify the relevant physical subset and independently review protection/stop behavior
   before any real supervised web take; the current pulled keypoint file is empty.

This file adapter itself still opens no devices and executes no motor commands. Browser
capture/export and review orchestration live in `arm_controller/`, not in this module.
No live acoustic qualification or proven physical improvement is established. Camera remains off.
See [DESIGN.md](../DESIGN.md), [REHEARSAL_LOOP.md](../REHEARSAL_LOOP.md), and [AGENTS.md](../../AGENTS.md).

[Baseten audio request requirements](https://docs.baseten.co/inference/model-apis/audio)
