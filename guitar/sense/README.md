# Sensing — existing measurements and optional model assessment

Current scope is [model-guided guitar rehearsal](../DESIGN.md), not a newly trained sound
classifier. **Camera input is off by default and is not needed for this plan.** Use known
arm state and available audio feedback. A pretrained audio-capable evaluator can critique
a consented real attempt recording; the planner revises its next approved plan without
changing either model's weights. Vision is an optional diagnostic, not a required model capability.

## 1. What is implemented

| File | Actual behavior |
|---|---|
| [`camera_relay.py`](camera_relay.py) | Optional utility; explicitly running it opens a selected local camera and serves localhost MJPEG/JPEG/health. The agent never starts it. Has top-level startup; do not import as a test helper. |
| [`camera.py`](camera.py) | Optional relay client; called by the agent only with explicit `--camera`/`use_camera=True`. Default sessions never probe it. `/astra.jpg` is a historical route name, not a provider requirement. |
| [`mic.py`](mic.py) | 44.1 kHz mono ring buffer plus local level/onset/YIN-pitch estimates; not an audio-language model or trained guitar classifier. |
| [`../model/audio.py`](../model/audio.py) | Separate opt-in file evaluator: PCM16 WAV validation/resampling, upload, structured assessment. No capture/devices/tools; live Inkling endpoint remains unavailable. |

`mic.py` and `camera.py` already exist. Old references to missing `sense/calibrate.py`,
separate `onsets.py`, `timing.py`, or a completed multi-strum packet pipeline are not the
current implementation. Default agent requests contain text/state and available local audio
estimates, with no images or video. JPEGs can be attached/recorded only for opted-in snapshots;
the recorder does not yet export per-attempt WAV files for a pretrained audio evaluator.

### Explicit camera diagnostic mode

`--camera` opts the guitar agent into snapshot requests from a separately started relay.
`--no-camera` explicitly keeps the default off state; the two flags are mutually exclusive.
`Toolbox` also defaults to no camera, and `look()` returns arm state only in that mode.
Prompts/specs do not claim visual observations when the camera is disabled. These flags do
not stop other camera programs or turn an absent relay into a running capture service.
The relay's index-1/Camo-iPad setting is a historical device choice, not a guaranteed camera
identity on every machine or a setup requirement.

Microphone capture is separate and still enabled by the old CLI unless `--no-mic` is passed.
That default has not changed; use `--no-mic` for offline runs. The prompt/tool output reports
missing audio explicitly instead of suggesting the camera can judge sound.

## 2. Existing acoustic heuristic versus the proposed evaluator

`score()` currently estimates `rang`, level above the noise floor, onset count, first onset
relative to a command reference, pitch, and target. `wait_for_pluck()` supports the single
fretting-role loop waiting for someone to pluck.

These are useful development measurements, but their explanatory strings are hypotheses:

- A low level does not prove the pick missed; the input may be wrong, quiet, stale, or noisy.
- One onset does not prove a clean note; several peaks do not count strings or prove snagging.
- A pitch mismatch does not determine which mechanical adjustment is safe.
- The old six-string “5–6 onsets means clean” rule is not a validated guitar metric.

An explicit **file-based audio evaluator** now exists outside the capture path. It accepts
one selected PCM16 WAV with upload consent, converts it to 16 kHz mono, supplies a fixed
rubric and expected phrase, and validates the returned assessment. See [AUDIO.md](../model/AUDIO.md).
Inkling still timed out on a synthetic audio request; successful raw-audio processing and
musical assessment are not yet established. No model fine-tuning or classifier training is involved.
The active Kimi planner still receives text/state, not recordings. No report is automatically
fed into the rehearsal loop yet. Do not claim the planner listened when it received a summary.

## 3. Minimum new evaluator contract

Inputs: the real clip, expected phrase/notes, attempt ID, relevant capture metadata, and a
fixed comparison rubric. Outputs: recording usability, bounded observations about the
attempt, uncertainty, and a short comparison with previous attempts where supported.

The evaluator has **no motion tools**. It must not instruct arbitrary pressure, joint,
grip, or calibration changes. A missing note may justify inspection, not a confident
mechanical diagnosis. The planner chooses only actions that the local controller permits.

No image input is required for the audio evaluator. If an explicitly requested future
vision experiment combines modalities, test that exact request separately; it does not
change the default camera-off policy. Camera/video cannot establish acoustic quality or
contact force. ASR is not a substitute for judging guitar sound.

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
