# Sensing — existing measurements and optional model assessment

Current scope is [model-guided guitar rehearsal](../DESIGN.md), not a newly trained sound
classifier. Use camera observations and, when enabled with consent, real attempt recordings.
A pretrained audio-capable evaluator can critique a clip; the planner can revise its next
approved plan without changing either model's weights.

## 1. What is implemented

| File | Actual behavior |
|---|---|
| [`camera_relay.py`](camera_relay.py) | Opens an OpenCV camera and serves localhost MJPEG/JPEG/health endpoints. Has top-level device startup; do not import it as a test helper. |
| [`camera.py`](camera.py) | Fetches relay health and one reduced JPEG from `/astra.jpg`, rejecting an old frame according to its age check. The route name is historical, not provider-specific. |
| [`mic.py`](mic.py) | 44.1 kHz mono ring buffer plus local level/onset/YIN-pitch estimates; not an audio-language model or trained guitar classifier. |

`mic.py` and `camera.py` already exist. Old references to missing `sense/calibrate.py`,
separate `onsets.py`, `timing.py`, or a completed multi-strum packet pipeline are not the
current implementation. The agent sends a snapshot and text/tool feedback, not a continuous
raw video/audio stream. Its recorder saves JSONL and JPEGs, not per-attempt WAV files.

## 2. Existing acoustic heuristic versus the proposed evaluator

`score()` currently estimates `rang`, level above the noise floor, onset count, first onset
relative to a command reference, pitch, and target. `wait_for_pluck()` supports the single
fretting-role loop waiting for someone to pluck.

These are useful development measurements, but their explanatory strings are hypotheses:

- A low level does not prove the pick missed; the input may be wrong, quiet, stale, or noisy.
- One onset does not prove a clean note; several peaks do not count strings or prove snagging.
- A pitch mismatch does not determine which mechanical adjustment is safe.
- The old six-string “5–6 onsets means clean” rule is not a validated guitar metric.

The proposed **audio-model evaluator** is a separate integration: encode/export a consented
attempt clip, supply the intended phrase/rubric, call a verified audio-capable endpoint,
and retain its observations/uncertainty. It does not require training a classifier first.
The current Qwen2.5-VL/Baseten scaffold accepts images/text, not raw audio; its client has
no audio field. Do not claim the planner listened to a recording when it only received a
local score summary.

## 3. Minimum new evaluator contract

Inputs: the real clip, expected phrase/notes, attempt ID, relevant capture metadata, and a
fixed comparison rubric. Outputs: recording usability, bounded observations about the
attempt, uncertainty, and a short comparison with previous attempts where supported.

The evaluator has **no motion tools**. It must not instruct arbitrary pressure, joint,
grip, or calibration changes. A missing note may justify inspection, not a confident
mechanical diagnosis. The planner chooses only actions that the local controller permits.

If an audio-capable endpoint also accepts images, test the exact combined request before
using it; support for each modality individually is not proof the combination works.
Camera/video alone cannot establish acoustic quality or contact force. ASR is not a
substitute for judging guitar sound.

## 4. Capture and timing gaps to address

- Select and verify the real input device/permissions; a nonempty array is not sufficient.
- The current mic callback uses host callback-arrival time and ignores ADC timing/status.
  Measure the timebase/input latency; do not subtract an assumed fixed latency value.
- `capture()` waits for future data without an independent timeout and does not validate
  retained history bounds. Add stale/dropout/overflow/window checks before autonomous use.
- The current `t_cmd`/duration fields can omit an initial base phase and do not identify
  physical pick contact or encoder-settled arrival. Keep intended onset, command timing,
  sensor capture, and model assessment timestamps separate.
- Persist attempt clips only with consent, with enough provenance to prevent evaluating
  the wrong or replayed recording. Label synthetic/replay/operator evidence explicitly.
- Keep capture/DSP/network work off the local control/watchdog path. A dead microphone or
  evaluator must not leave an indefinite physical hold or start an automatic retry.

These are pending code requirements, not fixes made by rewriting documentation.

## 5. Practical first validation

Use consented, safely obtained short guitar recordings to check capture and evaluator
behavior before hardware integration. Include usable notes and unclear/noisy recordings;
verify that uncertainty is reported rather than fabricated detail. This is an inference
smoke/evaluation exercise, not a fine-tuning dataset prerequisite.

When measuring precise pitch/onset performance, use separately validated signal processing
or a suitable reference measurement. Report an audio model's rating as an assessment, not
ground truth or proof of millisecond timing accuracy. Ordinary human listening can review
results without being relabeled automatic sensing.

The legacy [transcriber](../Note%20Transcriber/README.md) is a separate reference input tool,
not this rehearsal evaluator or a required runtime dependency. See
[REHEARSAL_LOOP.md](../REHEARSAL_LOOP.md) for the full feedback flow and
[STATUS.md](../STATUS.md) for current source limitations.
