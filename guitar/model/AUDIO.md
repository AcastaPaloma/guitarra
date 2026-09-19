# Optional file-based audio evaluator

**Implementation is ready for explicit file uploads; live audio inference is still blocked.**
Full `thinkingmachines/inkling` timed out on the documented `audio_url` request with a
one-second synthetic PCM16/16 kHz WAV. See [audio-connection-check.json](audio-connection-check.json).
That probe did not upload user media, open a device, or move a robot. It does not demonstrate
successful audio ingestion or guitar assessment. Kimi K3 remains the working planner.

**Single-arm web integration now exists:** [arm_controller/REHEARSAL.md](../../arm_controller/REHEARSAL.md)
uses a consented browser AudioWorklet to capture a bounded take, then calls this file
adapter and feeds a valid assessment to a bounded Kimi revision proposal. It never
replays automatically. That integration passed offline mocked/synthetic checks only;
no new live endpoint result or user-media upload is claimed. The older `guitar/web`
fake console and legacy agent recorder remain separate.

## The interface

`model/audio.py` reads **one operator-selected file**, validates it, converts it to a 16 kHz
mono WAV, and optionally submits it to Baseten. `scripts/evaluate_audio.py` is the CLI.
Neither module imports/opens robot drivers, cameras, microphones, or motion tools.

Accepted input: uncompressed **16-bit PCM WAV**, mono or stereo, nonempty and no longer
than 60 seconds / 32 MiB. Common rates including 16, 44.1, and 48 kHz are supported.
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

# Explicit consent to upload THIS recording and make ONE billed API request.
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
to choose a new JSON path. Existing reports are not overwritten, and failures aren't
silently retried. To intentionally re-assess an existing clip, preserve its attempt ID
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

Both use `BASETEN_API_KEY` from the ignored `.env`. The evaluator sends a single non-streaming
request with high reasoning and a 4,096-token output budget. It refuses to route audio to
Kimi. No automatic provider/model fallback is configured.

## Assessment contract

Successful, complete responses must satisfy a versioned JSON schema containing:

- `recording_quality`: usable / limited / unusable / uncertain.
- `notes_match`, `timing_match`: consistent / inconsistent / uncertain / not_assessed.
- `summary`, bounded `observations`, and mandatory `limitations`.

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

1. Resolve the Inkling endpoint timeout/access issue and verify a real audio response.
2. Assess a short consented recording and review its usefulness/uncertainty with the operator.
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
