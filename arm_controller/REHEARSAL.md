# Single-arm web rehearsal: play → listen → review → approve

**Motion update:** [PATHS.md](PATHS.md) owns the active lift-first execution contract.
The real player no longer admits contact-only rest/row-hub paths. Its 25 current
contacts have no recorded key hovers or lift-first review, so Play is blocked—not
silently routed through neutral. Kimi receives arm ownership/reviewed travel costs;
local code enforces lift → hover travel → tap independently of audio. The second
tap arm (`arm1.py`, rows 7–11, strings 1–6 right-to-left) uses the SAME generalized
lift-first contract bound to its own body IDs; it unlocks only when
`keyframes_arm1.json` gains per-key hovers AND `calibration_arm1.json` holds a
current operator path review (today: 29 contacts, zero hovers → unavailable, with
the exact missing step reported). Mixed takes are strictly sequential — one arm
moves at a time, the idle arm parked at its own hover/rest — and force stop
freezes BOTH arms.

This is the **current single-arm web implementation**, separate from the older
`guitar/web` fake/two-arm orchestration console. It uses the working tap/fret arm
(IDs **7–11**). It never commands tool-gripper **12**, activates the retired pluck
arm, accesses a camera, or changes model weights. [AGENTS.md](../AGENTS.md) remains
authoritative for grip retention, the latest live limit **110**, and unresolved
thermal/protection qualification.

## Run / current blockers

From the repository root, using the existing environment:

```bash
guitar/.venv/bin/python arm_controller/webapp.py --port 8788
# Open http://127.0.0.1:8788
```

The launched tap console uses **8788**. The older fake console on **8787** and the
unrelated service on **8765** are left alone. Bind stays loopback-only. Startup,
page loading, and status/bootstrap do not open devices or call models.

Required runtime packages: Python 3.12+, FastAPI/Pydantic 2, Uvicorn, pyserial,
jsonschema, NumPy, SciPy, and the existing Python/Tk support used by `app.py`.
They are available in this checkout's `guitar/.venv`; no driver/environment was
recreated for this change. The old three-package `uv run` command alone is no
longer sufficient for the audio adapter.

**Current readiness limits (connectivity is separate from physical/acoustic qualification):**

1. The v4 `keyframes_arm2.json` contains **25 contact keys, zero per-key hovers**,
   and no lift-first qualification. Note planning is possible; motion is not.
   Record/review a small set of actual contact/hover pairs and directed transit
   paths with the operator after resolving physical/thermal gates. No backup,
   old fret map, arbitrary offset, interpolation, or XYZ estimate replaces that review.
2. **Inkling access now works:** an approved three-call/$0.10 synthetic check passed
   full-model text/audio and Small audio, with positive audio-input tokens. Estimated
   usage cost was $0.00175575. This does not establish accurate guitar critique: both
   models misdescribed the generated tones. Local DSP v2 now supports the model; the
   revised grounded feedback contract is offline-tested, not real-guitar-qualified.
   No real media was uploaded. See [audio setup/evidence](../guitar/model/AUDIO.md).

Before any physical test, resolve the applicable operator/thermal/stop gates and
check the actual serial-port mapping. This work does **not** qualify motion,
continuous gripping, body support, or hardware protection.

## Clean UI and ongoing sessions

The main **Play** screen stays minimal: song/notes, one Play button, current state,
and the latest concise review/diff. Technical detail is collapsed; per-take media
and body-support consent lives in a confirmation dialog, not a wall of checkboxes.
**Progress** is a separate tab for session selection, saved recordings, tuning versions,
review history, and a command-duration chart. Model output is always rendered as text.

Each attempted take gets an immutable plan/tuning ID and report. Completed recordings
are saved as WAV; received partial buffers on Stop/device failure are saved **locally
only**, clearly marked incomplete, and are never assessed or treated as bad notes.
Permission denial, no received samples, sudden tab/process loss, or a failed upload
can leave a take without a recording; the UI does not manufacture one.

A valid next proposal is **staged automatically**, but Play Next Take still requires an
operator click and fresh confirmation. There is no automatic physical rerun. You can
keep the previously performed tuning instead, or load any completed cached tuning
from Progress without calling the arrangement model again. This keeps a session going
across bounded three-attempt revision sets; continuing a new set is explicit supervision,
not an automatic budget reset. Each session is capped at 100 take records (no auto-delete).

Saved sessions/tunings survive server/browser restarts. The page can stage a saved
preferred/last-performed tuning but never resumes a motor command, mic, or model request.
Reusing it creates a **new capture ID/take**, checks the current calibration fingerprint,
and still requires confirmation. Expired proposals and interrupted/faulted execution
cannot become resumable motion programs. A changed phrase can start a new session.

The planner gets a bounded **last-three-attempt textual history**, including compact
versioned acoustic summaries and reviewer identity, not past raw WAVs or private reasoning.
It can avoid repeating prior unhelpful choices; this is context/plan refinement, not weight training. “★ preferred” is a persisted **human
judgment**, not automatic best-plan selection or physical qualification.

The chart compares command durations only for the same pitch order and calibration.
Audio judgments and local acoustic estimates remain separate. A nullable 0–10 model
opinion is not a calibrated quality/improvement score or a claim every take gets better.
Changed musical ordering/calibration is explicitly not time-compared against the baseline.

## Operator flow

1. **Convert to notes** makes one billed Kimi planner request using only currently
   recorded keys and explicit arm ownership. When a reviewed hover graph exists,
   only its qualified subset and count-travel costs are offered. The arrangement
   can have up to 64 notes; the take must fit the local execution/capture budget.
   Long songs are not automatically swept or chunk-replayed.
2. Review the selected notes/pauses. **Play + Listen / Play Next Take** opens a compact
   confirmation dialog with microphone + Baseten upload/inference consent and physical
   supervision/body support. Both reset each take. Loading the page never asks for a mic.
3. **Start Take** reserves the arm locally, asks for the browser device's mic,
   and waits for actual PCM samples **before submitting Play**. Denied, delayed,
   empty, interrupted, or unsupported capture does not silently fall back to
   unrecorded execution. The API's capture-ready fields are browser attestations,
   not independent proof of the source device.
4. Whole-phrase lift-first admission runs before reservation/recording and again
   before connection. `tap A → hover A → reviewed hover route → hover B → tap B`
   executes locally at unchanged speeds/contact dwell; every lift must finish before
   travel. Global rest is only entry/final exit, never a between-note fallback.
   There is no per-note model request. Recording continues through completion and
   a 350ms ringing tail, then closes **all** microphone tracks/context.
5. After normal disconnect, upload this attempt's mono PCM16 WAV to the local server.
   Local DSP computes source-bound pitch/attack estimates with explicit unknowns. The
   adapter sends the 16kHz clip, expected phrase, capture quality and estimates to
   **Inkling, with at most one logged Small fallback** on a transient failure. No
   WAV/base64 is passed to Kimi or included in JSON reports.
6. Kimi receives the assessment as **untrusted data**, with local estimates, bounded
   history and separate command/encoder telemetry, and proposes at most one bounded
   adjustment. Unavailable/unusable audio produces no bad-note score or compensating
   movement. Uncertain evidence may reach the planner with a null score and caveats;
   it should prefer keep/inspect rather than invent precision. Estimates and model
   opinion can both be wrong; disagreements require inspection.
7. The page shows the actual clip, concise assessment, and exact proposed diff;
   full observations/limitations/telemetry are under Take details. The next proposal
   is staged. **Play Next Take** confirms that next plan; “keep the previous tuning”
   stages the performed version instead. Progress can replay clips, load a cached
   performed tuning, and save your preferred take. None of these starts robot motion.

A revision chain allows at most **three operator-started attempts**; the third can
be assessed but requests no further revision. A proposal expires in five minutes,
can produce only one child reservation, and must match the current keypoint +
calibration fingerprint and exact approved plan. You can explicitly start another
supervised set in the same session using a performed cached tuning. Previous reports
remain in the session and bounded planner context; there is no unattended budget reset.

## What revisions can actually do

| Category | Local admission rule |
|---|---|
| Timing | Change up to three post-lift pauses, by at most **100ms** each, on a **50ms** grid in 0–2000ms. The last, unused pause cannot be “optimized.” |
| Ordering | Swap one adjacent pair of existing events. The UI warns that this changes the musical arrangement; it is not a path-only optimization. No note insertion/deletion/duplication. |
| Positioning | Select one other **recorded same-pitch key owned by the same enabled arm**. No joint/XYZ offsets, IK, contact-depth changes, new poses, or transfer to an unavailable arm. The result still needs full path admission. |
| Paths | Only locally admitted `lift_first` is executable now. The compiler minimizes reviewed hover travel, never global-neutral detours between notes. `rest_hub`/`row_hub` remain historical schema values, not current execution authority. Invented waypoints, unreviewed edges and missing hovers are **rejected**. |

Only **one category per attempt** can change. The model cannot change speed,
acceleration, dwell, gripper state/torque, protection, limits, calibration, the
path registry, or executable code. Baseline and proposed plans are stored separately.
No model output dispatches tools or bypasses the operator's next Play.

The pauses are **after the complete tap/lift cycle**, not acoustic inter-onset
intervals or a precise beat scheduler. Telemetry records server command windows
and encoder readiness, not verified contact or the moment sound began. The evaluator
is told that exact intended attack times are unspecified. This is not a demonstration
of millisecond timing correction, nor a guarantee of improvement.

### Lift-first paths, not hub-only motion

The earlier rest/row-hub family moved lift and lateral joints together. It could
not enforce the required lift-before-travel ordering. That code path and its
qualification sweep are retired. The real executor accepts only recorded/reviewed
contact↔hover pairs and directed hover crossings, with whole-phrase preflight and
arrival/fault gates. Models receive named capabilities, not authority to invent
paths. `POST /api/trajectory` previews every named stage without devices/inference.

See [PATHS.md](PATHS.md) for recording names, review fingerprints, the no-neutral
shortest-path compiler, CLI preview, and minimal two-key qualification. No existing
poses or approval records were fabricated. Current hovers are absent, so playback
is blocked even though note planning is available. Encoder readiness/endpoint
coordinates/audio cannot establish swept clearance or resolve the thermal gates.

## Capture, ownership, budgets, and failure behavior

- WebAudio + an AudioWorklet captures mono PCM16; echo cancellation, AGC, and noise
  suppression are *requested* off (browser/device support can vary). No speaker
  monitoring, camera input, server microphone, MediaRecorder WebM dependency, or
  ffmpeg process. The browser handles late permission grants by closing their tracks.
- Current pulled limits are **160s capture**, **150s local execution**, up to 64
  notes subject to the duration estimate, and four-second encoder-stage timeouts.
  These limits were not increased by the lift-first fix. They are software bounds,
  not measured mechanics or permission for long/unattended holds. Compiled route
  travel is a count proxy, not a new physical timing measurement.
- Each reservation has a unique attempt ID and capture ID. The server accepts a
  single matching WAV only after **completed** playback, checks sample counts/rate,
  sample-frame markers, duration/coverage, and upload size. Frame continuity/input
  interruptions are checked in the browser. Browser/server alignment remains
  approximate; this is not an ADC/hardware timestamp calibration or proof of provenance.
- One reservation owns playback/review at a time. Calibration connection and
  reservations share a lock; keypoint writes are blocked during the attempt.
  The plan uses an immutable local pose snapshot, with freshness checks before
  connection and revision admission. Another process/GUI must still stay off the
  exclusive serial port; no cross-process motion arbitrator has been built.
- **Stop is cooperative, not an emergency stop.** A current bounded tap/lift can
  finish before further taps are blocked. A missing browser heartbeat (8s), page
  exit, device/capture failure, or time budget requests cancellation. Do not rely
  on browser networking or this watchdog for thermal/electrical motor protection.
- Failed encoder arrival now **raises**, instead of returning an ignored `False`
  and continuing into the next press. Faults/uncertain state cause no automatic
  rest/recovery move, audio compensation, or replay.
- The pulled web player's clean/cooperative-stop path parks once via a reviewed
  final exit and **holds body torque**; force stop holds frozen goals. Faults release
  body torque without recovery motion (**support the body**). Failed exit is now a
  fault, not a successful take. These existing hold semantics remain unqualified for
  sustained thermal use. Motor 12 is never commanded: no all-motors torque-off, grip
  opening, or grip reassertion. The standalone close default is unchanged.
- During network inference, Stop discards late results and blocks further requests
  or dispatch. It cannot cancel an already-billed request. Audio defaults to no extra
  reasoning, 30s per request, and at most one Small fallback for transient errors,
  within a 75s admission/result budget further capped by the remaining review stage.
  Auth/billing/input/assessment failures do not trigger fallback. Every attempted
  model/failure is recorded and the UI names the reviewer. Text revision uses 60s.
  No API failure or late result authorizes motion. See [AUDIO.md](../guitar/model/AUDIO.md).
- Browser refresh/server restart never resumes a take or pairs it with an old clip.
  Another page can explicitly request Stop but does not adopt the recording lease.

There is still **no independently qualified thermal/electrical monitor or hardware
E-stop** in this raw-serial app. Bypassing the legacy plugin avoids its connection-time
grip default write in this path; it does **not** resolve the historical 75°C event,
qualify live grip 110, or fix that plugin's reconnect/reassertion behavior elsewhere.

## Local records / privacy / API boundary

Records are ignored by Git:

```text
guitar/runs/tap_rehearsal/<attempt UUID>/
  attempt.json   # consent, baseline/current plan, calibration fingerprint,
                 # command telemetry, capture provenance, assessment, proposed diff
  capture.wav    # completed, explicitly uploaded browser recording
  capture.partial.wav  # if available on interruption; local-only, never evaluated

guitar/runs/tap_rehearsal/sessions/<session UUID>.json
                 # title, baseline plan, ordered take IDs, operator-preferred take
```

Files are private to the local user (0600; attempt directories 0700). They persist
until the operator deletes them; **no automatic retention cleanup** is implemented.
The live page also offers its own recording via a temporary browser blob URL. Progress
loads archived audio with the current local session token; media is not exposed as an
unauthenticated cross-origin embed. UUID/path/symlink checks restrict reads to saved
reports/clips. The API accepts no arbitrary filesystem path/upload filename. Session
selection lists the 30 most recently modified session files; older artifacts are retained.
Do not share recordings/reports without permission; acoustic surroundings can be private.

Only the server reads `BASETEN_API_KEY` from ignored environment files. Browser
requests never receive it. The app checks loopback Host/same Origin, uses a random
per-server session token for every mutation (including calibration), limits actual
streamed request bytes, rejects extra plan fields, and renders model text as text.
This is a **single-user local console**, not authenticated multi-user infrastructure.
Do not tunnel or bind it to the LAN without a separate security review.

## Offline verification (not a physical or model-quality qualification)

Latest combined source check after audio v2: **340 Python tests passed**, three Node
capture checks and JS syntax checking passed. Six former DSP expected failures are now
ordinary regressions. The three approved **live synthetic v1 API calls** are separate
connectivity evidence, not validation of the revised v2 contract or real guitar playing.
The original browser/implementation fixture results below are retained as history;
[STATUS.md](../guitar/STATUS.md) distinguishes subsequent motion and audio work.

```bash
guitar/.venv/bin/python -m pytest arm_controller/tests guitar/tests -q
node --test arm_controller/tests/capture.test.mjs
# Optional Playwright + installed Google Chrome; all /api requests are mocked:
guitar/.venv/bin/python arm_controller/tests/browser_check.py
```

Original implementation result: **188 Python checks passed** (67 new + 121 existing).
Those tests prevent real serial/provider access and cover bounded proposals, schema rejection,
recording identity/completeness, no replay, late-result cancellation, source
freshness, ownership/lease/attempt budgets, local HTTP consent/security, gripper
exclusion, body-only cleanup, encoder-timeout propagation, persistent sessions/favorites,
bounded prior-attempt context, cached tuning admission after restart, local-only partial
clips, comparison honesty, and private audio/path/symlink boundaries. Three additional
Node fixtures passed for PCM16 encoding, contiguous startup readiness, and rejection
of post-readiness audio-render gaps/missing input.

Six browser cases passed: two consecutive reviewed takes plus cached tuning/favorite/history
and reload (without resuming capture/motion), mic denial, late permission after Stop, Stop
during playback, provider-unavailable feedback, and microphone disconnect. Stop/disconnect
retained local-only partial clips; the success case exercised token-authenticated playback.
They use an oscillator-generated MediaStream, a real browser AudioWorklet/WAV encoder,
**mocked API/motor/model results**, and extra Chromium fake-device flags. All tracks
ended; no JavaScript errors or desktop/mobile horizontal overflow. Evidence/screenshot:
`guitar/runs/tap-browser-check.json` and `tap-browser-check-{play,history}-{1100,390}.png`. These are labeled **offline fixtures**, not
robot audio, Baseten assessments, or physical timing measurements.

Those original implementation fixtures used no real arm, camera, microphone, paid
inference, deployment or training. The later approved synthetic API check established
current Inkling/Small access, not useful guitar optimization. The revised v2 contract
and a consented real recording still need end-to-end acoustic validation; any physical
take separately requires the operator/path/thermal gates.
