# Audio assessment and Inkling access investigation — 2026-09-20

**Initial investigation plus the approved follow-up below; not physical qualification.** Operator direction:
keep inference on **Baseten**, keep preview **Inkling as primary**, accept a bounded,
visible fallback when needed, and support its qualitative assessment with local
pitch/timing estimates. Imperfect model judgment is acceptable; fabricated precision
or confident conclusions from missing evidence are not. No new hosted model, training,
or GPU deployment is needed for the next step.

The initial investigation changed only documentation/evidence and offline regressions.
The later follow-up changes audio-review/DSP source; this audio task leaves credentials,
motors, capture and the live server untouched. Concurrent arm/planner/orchestration work is preserved.

## Follow-up: approved probe and software corrections

The operator approved **three synthetic calls within $0.10**. All succeeded with
`reasoning_effort=none`: full text **0.485s**, full audio **6.447s**, Small audio **3.272s**,
HTTP 200 throughout. Both audio responses reported **21 audio-input tokens** and passed
the then-current v1 schema. Usage-based cost estimate **$0.00175575** (uncached prices,
not an invoice); no fourth request. [Live evidence](audio-inference-check.json).

**Access works now.** The earlier timeout cause remains unproven; no controlled high/none
comparison was performed. The metadata omission did not block actual audio ingestion.
Quality was poor on event detail: the fixture had **two tones and no room noise**, but
neither model described both and both mentioned room noise. Their targetless scores were
also unjustified. This validates the need for local measurement/uncertainty, not a new
hosting platform or a claim that a successful response is useful guitar optimization.

Follow-up source changes (see [current interface](AUDIO.md)):

- Inkling remains primary, now defaulting to the successful `none` reasoning setting;
  audio output cap 1,536 tokens. A logged, at-most-one Small fallback handles transient
  transport/HTTP errors, not auth/billing/input/assessment failures. A 75s admission/result
  budget, caller's remaining deadline and Stop gate future requests and discard late results.
- Local DSP v2 detects energy rises once, assigns candidates monotonically one-to-one,
  preserves plan/event identity, and uses multiframe normalized periodicity with octave,
  boundary, clipping, length and stability guards. Note identity and tuning cents are
  separate. All six original expected failures below became ordinary passing regressions.
- Clip SHA-bound estimates and capture quality now reach **Inkling and Kimi**, with
  explicit unknowns/limitations. Compact versioned summaries also reach history. The web
  supplies `timing_target_available=false` even on DSP failure; unsupported timing accuracy
  is rejected. No absolute delay/rhythm-error/jitter score is fabricated.
- v2 permits null model scores and rejects scores on unassessable evidence. Prompts no
  longer force grading or unconditional trust in DSP. UI labels candidate attacks, model
  opinion and the actual reviewer/fallback, rather than treating them as ground truth.
  The hardcoded historical timeout warning was replaced with a truthful configuration notice.

**The new v2 request contract/feedback loop was tested offline only after those three
calls.** This audio task performed no fourth inference, real recording, device access,
deployment, training, server restart or physical optimization. Real tone/overlap/noise and calibrated timing
remain validation work. Current test results are recorded in [STATUS.md](../STATUS.md).

---

**Historical initial findings below describe the pre-fix source and pre-probe state.**
They explain the changes; pending-probe statements and strict-xfail counts below are not
current status. No original failure evidence was overwritten.

## 1. Access: what we initially established

[Sanitized access evidence](audio-access-check.json) records authenticated **GETs only**
to Baseten's inference catalog, management catalog, and existing model usage. No new
inference request, recording access/upload, microphone, camera, or hardware was used.

| Check | Observed result | What it does / does not establish |
|---|---|---|
| Configuration | `BASETEN_API_KEY` comes from `guitar/.env`; no conflicting credential found; full Inkling and 30s audio timeout selected | Checks current file/environment resolution, not the running server's in-memory environment. Keys were never printed. |
| Running web app | Bootstrap reports key present, full Inkling selected/supported, and “unverified; last recorded live probe timed out” | **That status string is hardcoded**, not a current provider health/entitlement check. No session tokens or attempt details were printed/saved. |
| Inference catalog | Authenticated request succeeded; full Inkling and Small listed | This credential can authenticate and see the catalog. Listing alone is not an end-to-end inference/access test. |
| Workspace catalog | Both models already added; full limit 15 RPM / 100k TPM, Small 120 RPM / 500k TPM | No evidence that the workspace simply forgot to add either model. Limits differ; no current rate-limit error was observed. |
| Existing workspace usage | Full: 8 requests, 0 input/output tokens recorded. Small: 9 requests, 11,201 input / 8,336 output tokens | In the queried window starting 2026-09-19 13:00 UTC. Workspace-wide, not attributable solely to this app. Small has actual token usage; these aggregates do not distinguish audio from text or explain individual errors. |
| Modality metadata | Both authenticated catalog entries say text/image, while public docs explicitly support audio for both | A real documentation/metadata discrepancy; potentially stale preview metadata, **not proof** audio is forbidden. |
| Prior local probe | Full Inkling timed out after 30.08s on a one-second synthetic WAV | [Old evidence](audio-connection-check.json) is a transport timeout, **not HTTP 401/403**. It does not establish lack of access or global provider downtime. |

**Conclusion:** “we do not have access” is not established. Authentication and workspace
addition work. Full-model serving is still unverified in this client. Preview availability,
account-specific entitlement/routing, request handling, and excessive response latency
remain distinguishable hypotheses; do not pick one without a real response.

### Why this client can look broken even with an active model

- The web bootstrap's endpoint warning is a constant old-probe message. It is not
  refreshed from current requests and cannot establish that Inkling is down/disabled.
- Audio uses a **30s, non-streaming request**, `reasoning_effort="high"`, and a 4,096-token
  output budget. Baseten documents that higher reasoning increases latency. This is a
  possible explanation, not a measured cause of the timeout.
- `model/baseten.py` groups connection failures and timeouts into one exception; it
  deliberately suppresses arbitrary provider error bodies. Current records lack the
  request IDs and structured provider error detail needed for a definitive escalation.
- `model/audio.py` already tries **Inkling Small once** after a no-HTTP-status transport
  failure. An offline mock confirmed two calls and `model_fallback_from` in the report.
  It does **not** fall back for HTTP 429/5xx/529, schema errors, or missing audio-token usage.
  Older “one audio request / no fallback” documentation was stale. The operator now
  explicitly accepts fallback; make the actual model/failure visible rather than hiding it.
- A response can arrive yet still be rejected: malformed/truncated JSON, mandatory
  score/suggestions absent, forbidden tool calls, or absent positive audio-token usage.
  Those are contract/verification failures, not necessarily a network or permission failure.

### Bounded next probe (approval requested, not run)

Maximum **three** tiny requests on Baseten, budget **$0.10**, no retries/deployments/devices
or user recordings. Use fresh synthetic PCM16/16kHz audio and a small output cap. Probe
full Inkling with low/no reasoning first to isolate serving from the coaching contract;
a short text control and Small audio control can distinguish modality-specific failure
from full-model failure. Stop on auth/billing errors or exhausted budget.

Record the actual model, HTTP status, safe provider request ID/error code, elapsed time,
finish reason, and usage/audio tokens. Never log credentials, request headers, base64,
private reasoning, or arbitrary provider bodies. Use a bounded longer diagnostic timeout
without changing the active rehearsal deadline. A timeout is still inconclusive; send a
sanitized request ID/time/model/error packet to Baseten rather than repeatedly retrying.

Do **not** just raise `BASETEN_AUDIO_TIMEOUT_S` in the live app: review currently has its
own 100s stage deadline, so full + fallback waits must fit that budget. Long Small clips
also need review: the adapter permits 160s, but Baseten recommends **under two minutes**
for Small (a best-results guideline, not a claimed hard rejection limit).

## 2. The audio path is already partly deterministic

Current single-arm source:

```text
validated saved WAV + plan + command telemetry
                    |
          tap_audio_metrics.measure_take
             /                  \
  saved/UI measurements       planner context (Kimi)

same WAV + expected phrase -> Inkling (or Small) -> assessment -> planner
```

Relevant files:

- [`../../arm_controller/tap_audio_metrics.py`](../../arm_controller/tap_audio_metrics.py):
  10ms RMS frames, whole-clip 20th-percentile noise floor, independent per-command
  search windows, one 250ms autocorrelation pitch estimate, ±80-cent matching.
- [`../../arm_controller/rehearsal.py`](../../arm_controller/rehearsal.py), `_review`:
  computes local metrics **before** the audio request, saves them, and passes them to
  `propose_revision`. A failed audio request still blocks the planner revision.
- [`audio.py`](audio.py), `evaluate_file`: receives the clip and expected phrase, **not
  the per-note metrics or even the loader's signal-quality estimates in its prompt**.
- [`../../arm_controller/tap_plans.py`](../../arm_controller/tap_plans.py): sends the
  metrics to Kimi and tells it to trust them over the audio assessment. Reproducibility
  alone does not justify that blanket priority while the estimator has known errors.
- [`../../arm_controller/tap_history.py`](../../arm_controller/tap_history.py): previous
  attempt context contains model judgments and command durations, not prior local
  acoustic metrics. Numerical acoustic A/B comparisons are not wired through history.

The legacy `guitar/sense/mic.py` is a separate heuristic path, not the current web DSP.
Neither the old transcriber nor a fine-tuning pipeline is a prerequisite.

## 3. Reproduced estimator problems

All examples below are generated waveforms and fabricated command telemetry, **not
measurements of the robot or real guitar recordings**. Controls pass; six desired-behavior
regressions are strict `xfail` until fixed:

[`../../arm_controller/tests/test_tap_audio_metrics.py`](../../arm_controller/tests/test_tap_audio_metrics.py)

| Synthetic condition | Current result | Problem |
|---|---|---|
| One sustained 220Hz tone begins before three command windows, with no new attacks | 3/3 notes heard, 3 pitch matches, approximately **5ms jitter** | Above-floor energy is treated as an onset. A ringing tail can look like three well-timed taps. |
| One attack within two overlapping search windows | 2/2 notes heard | No one-to-one event assignment; the same attack is used twice. |
| Three expected notes, absent telemetry | 0 notes planned, no note rows | Plan length is inferred from telemetry rather than preserved; missing evidence disappears. |
| Only telemetry event index 2 arrives | Assigned to note 0 and its expected pitch | Event identity is ignored in favor of enumeration order. |
| Tone 60 cents above A3 | Detected A#3, about +66 cents, but `pitch_match=true` for A3 | ±80 cents overlaps neighboring semitones; tuning tolerance is conflated with note identity. |
| 110Hz fundamental with dominant 220Hz harmonic | A3, +1194 cents from expected A2, definite mismatch | Octave ambiguity is not reported; a single autocorrelation maximum is brittle. |

Additional source issues: missing tap timing becomes `heard=false` / “missed,” not
unknown. “Clarity” is merely level above an estimated noise floor, not timbral quality.
Energy events, periodic motor noise, valid notes, and verified contact are not equivalent.

## 4. Recommended division of work

**Local DSP estimates numerical facts; Inkling listens for qualitative character and
interprets the estimates with uncertainty. Both remain inputs to bounded, locally
validated, separately operator-approved proposals.**

### Deterministic measurements first

1. Keep source-WAV/capture identity and versioned parameters. Check silence, clipping,
   interruption/coverage and noise-floor quality. Unusable capture is not a bad-note score.
2. Detect actual attack candidates using changes in energy/spectral flux with local noise
   estimates and duplicate suppression—not merely the first high-energy frame.
3. Estimate pitch over several post-attack frames with a confidence/periodicity-gated
   YIN or normalized-periodicity method, interpolation, stability checks, and octave
   ambiguity. Estimate independently of the requested note; **do not snap to the target**.
4. Match candidate events to planned event IDs monotonically and at most once. Retain
   unmatched/extra/ambiguous events. Missing telemetry/capture produces unknown rows.
5. Report note name **with octave**, frequency, cents error, note identity separately
   from tuning tolerance, confidence/ambiguity, onset position and relative intervals.
   “Key” here means the expected individual note, not estimating the song's tonal key.
6. Keep validated local evidence available even when the cloud assessment is unavailable.
   Do not manufacture a model review or replay the take to cure an API failure.

This is a monophonic/mostly isolated-tap starting point. Overlapping ringing strings,
strong harmonics, motor noise, clipping and short low notes require abstention or a
separately validated richer method. Deterministic does not mean infallible.

### Three different kinds of timing

- **Audio-to-audio intervals:** measurable within the recording, with detector uncertainty.
- **Rhythm error:** requires an actual intended onset schedule. Present `pause_ms` values
  are post-lift pauses, **not** the intended acoustic inter-onset intervals. Without a
  target rhythm, report intervals/consistency, not “late by X ms.”
- **Command-to-sound latency:** requires calibrated mapping from command clock to audio
  sample time. Current browser dispatch marks plus server elapsed time do not remove
  network/thread/buffering/input-device latency. The reference also uses tap **encoder
  readiness**, not the moment the press command or string contact occurred. Label any
  current offset as approximate; a 10ms hop is not a 10ms absolute-accuracy guarantee.

Do not fit away real latency using the same detected attacks and then call the resulting
alignment an independent delay measurement. Cloud request latency is separate from all
three musical/mechanical measurements.

### Feed evidence to Inkling, not only the planner

Supply **the actual audio + expected notes + versioned local estimates + capture/timebase
limitations** to the evaluator. Keep target, measurement, model opinion, and human review
separate in storage/UI. Its job is bounded commentary on attack consistency, audible
ringing, muted/harsh/buzzy sound, noise interference and overall phrase quality—not exact
frequency/timestamp extraction or mechanical diagnosis. Flag disagreements for inspection.

The current prompt says to prefer grading over abstaining and requires a numeric score
and suggestions even for uncertain audio. A supportive tone is fine, but permit unknown
findings / an unassessed score when evidence is weak. A 0–10 model judgment is not a
calibrated quality metric. Never assert numerical improvements from prose or force a
revision just because a review exists. All existing motion/thermal/operator gates remain.

Keep **Inkling primary → explicitly labeled Inkling Small fallback**, all on Baseten.
No new hosting/provider migration is proposed. Select fallback policy explicitly and
record each attempted model and failure class within the per-take request/time budget.

## 5. Verification and remaining work

```bash
# Pure fixtures; no devices, media files, keys or model calls:
guitar/.venv/bin/python -m pytest arm_controller/tests/test_tap_audio_metrics.py -q -rx

# Existing integration suites, with provider/device mocks:
guitar/.venv/bin/python -m pytest guitar/tests/test_audio_evaluator.py \
  arm_controller/tests/test_rehearsal.py arm_controller/tests/test_tap_plans.py -q
```

At the initial inspection: new DSP cases **5 passed, 6 expected failures**. Existing
selected suites **64 passed, 2 failed** before any runtime changes: the old 61-second
rejection test no longer matches the 160-second cap, and the mock “valid” assessment
omits now-required `score`/`suggestions`. These are test/contract drift, not access
errors or evidence of a model's hearing quality. Concurrent unrelated source edits
continued during the investigation; these counts are snapshots, not a blanket current
suite qualification. No DSP defect was fixed by adding `xfail` cases.

After the approved connectivity probe, wire the evidence packet and fix the estimator
against these regressions. Then use a **small, consented, human-reviewed** set of actual
short guitar clips (correct/wrong notes, silence/noise, single/double attacks, ringing,
muted/clipped audio) to validate usefulness and uncertainty. This is evaluation of
pretrained models/signal processing, not training, a physical sweep, or permission to
record/upload anything now.

## Sources

- [Baseten audio request shape, models, sample rate, length recommendations and audio tokens](https://docs.baseten.co/inference/model-apis/audio)
- [Baseten reasoning controls and latency trade-off](https://docs.baseten.co/inference/model-apis/reasoning)
- [Baseten model/workspace detail](https://docs.baseten.co/reference/management-api/model-apis/gets-a-model-api-by-name)
- [Baseten usage endpoint and its scope](https://docs.baseten.co/reference/management-api/model-apis/gets-model-apis-token-usage)
- [Baseten error classes, including rate limiting and serving overload](https://docs.baseten.co/inference/errors)
