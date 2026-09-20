# Single-arm web rehearsal: play → listen → review → approve

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

**Two blockers were found in the pulled checkout, not repaired by software tests:**

1. `keyframes_arm2.json` is **empty**. The calibration commit cleared it for
   re-recording. Record the current rest/keypoints with the operator; no automatic
   restore from `keyframes_arm2.backup-20260919.json`, old fret maps, interpolation,
   or XYZ estimates occurs. Planning/playback are blocked without a valid current grid.
2. The separate Baseten audio adapter targets `thinkingmachines/inkling` by default.
   Its last recorded live probe **timed out**; no successful live listening/guitar
   assessment is established. This integration has not made another paid probe or
   uploaded real media. Configuration alone is not endpoint verification. See
   [audio setup](../guitar/model/AUDIO.md).

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

The planner gets a bounded **last-three-attempt textual history**, not past raw WAVs
or private model reasoning. It can avoid repeating prior unhelpful choices; this is
context/plan refinement, not weight training. “★ preferred” is a persisted **human
judgment**, not automatic best-plan selection or physical qualification.

The chart compares command durations only for the same pitch order and calibration.
Audio judgments (notes/timing/recording quality) remain separate categorical assessments;
there is no invented numerical quality/improvement score or claim every take gets better.
Changed musical ordering/calibration is explicitly not time-compared against the baseline.

## Operator flow

1. **Convert to notes** makes one billed Kimi planner request using only currently
   recorded keys. The arrangement can have up to 64 notes. Select a short take of
   **up to four notes**; long songs are not automatically swept or chunk-replayed.
2. Review the selected notes/pauses. **Play + Listen / Play Next Take** opens a compact
   confirmation dialog with microphone + Baseten upload/inference consent and physical
   supervision/body support. Both reset each take. Loading the page never asks for a mic.
3. **Start Take** reserves the arm locally, asks for the browser device's mic,
   and waits for actual PCM samples **before submitting Play**. Denied, delayed,
   empty, interrupted, or unsupported capture does not silently fall back to
   unrecorded execution. The API's capture-ready fields are browser attestations,
   not independent proof of the source device.
4. The existing `rest → tap → rest` stages execute locally at the unchanged speeds
   and contact dwell. There is no per-note model request. The browser records through
   completion and a 350ms ringing tail, then closes **all** microphone tracks/context.
5. After normal disconnect, upload this attempt's mono PCM16 WAV to the local server.
   The existing adapter validates/resamples it to 16kHz and makes **one** consented
   Baseten audio request. No WAV/base64 is passed to Kimi or included in JSON logs.
6. If the assessment has usable/limited evidence, Kimi receives it explicitly as
   **untrusted data**, separately from command/encoder telemetry, and proposes at
   most one bounded adjustment. Unavailable/unusable/uncertain audio yields inspection
   or unavailable feedback, not a bad-note score or compensating movement.
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
| Positioning | Select one other **currently recorded key of identical pitch**. No joint/XYZ offsets, inverse kinematics, contact-depth changes, or new poses. The current 18-key fret-1–3 set has no alternate same-pitch locations, so this normally offers no positioning change. |
| Paths | Switch `path_profile` between **named, operator-qualified profiles only** (see below). `rest_hub` always exists; `row_hub` appears only after the operator runs `fret.py --qualify-row-hubs` and confirms. Direct A→B/hover shortcuts, waypoints, or any other invented path are **rejected**, not silently clamped or interpreted. |

Only **one category per attempt** can change. The model cannot change speed,
acceleration, dwell, gripper state/torque, protection, limits, calibration, the
path registry, or executable code. Baseline and proposed plans are stored separately.
No model output dispatches tools or bypasses the operator's next Play.

The pauses are **after the complete tap/lift cycle**, not acoustic inter-onset
intervals or a precise beat scheduler. Telemetry records server command windows
and encoder readiness, not verified contact or the moment sound began. The evaluator
is told that exact intended attack times are unspecified. This is not a demonstration
of millisecond timing correction, nor a guarantee of improvement.

### Path profiles: `rest_hub` and the qualified `row_hub`

`rest_hub` routes every tap press → global rest → press. `row_hub` stages via the
operator-recorded per-fret-row lifted hubs (`rest-r{N}` keyframes): lift to the
current row's hub, cross hubs only on a row change, press — much shorter travels
within a row. Both are fixed staging families executed by local code
(`fret.py`); a model can only *select* one from `allowed_path_profiles`, never
supply waypoints, joints, XYZ, or speeds.

`row_hub` becomes selectable ONLY through a human-in-the-loop qualification:
the operator runs `fret.py --qualify-row-hubs` (a slow supervised walk of every
hub, every press/lift in each row, and every hub-to-hub crossing), watches for
scrapes/interference, and types QUALIFIED at the local terminal. That records
the decision in `calibration_arm2.json` **bound to the sha256 of the exact
keyframe bytes** — any keypoint edit silently un-qualifies it. The web console
and the browser cannot set or forge this flag; the registry re-derives it from
disk on every read and the capability fingerprint covers it, so a mid-session
change expires outstanding proposals. Neither profile is presented as an
unconditional collision-free guarantee.

Hover/direct A→B shortcuts still do not exist: the derived XYZ layer has
unverified joint signs/offsets, and no audio explanation, endpoint pose, or
interpolation can certify swept clearance. Any future hover library needs its
own recorded transitions and a separate operator qualification of this same
shape before local code may name it as a profile.

## Capture, ownership, budgets, and failure behavior

- WebAudio + an AudioWorklet captures mono PCM16; echo cancellation, AGC, and noise
  suppression are *requested* off (browser/device support can vary). No speaker
  monitoring, camera input, server microphone, MediaRecorder WebM dependency, or
  ffmpeg process. The browser handles late permission grants by closing their tracks.
- Capture is bounded to **60s**. Four notes reserve three four-second encoder-stage
  timeouts per note, the existing 120ms dwell, and bounded post-lift pauses within
  a **55s** software execution budget. These are safety/time limits, not measured
  mechanics or a qualified thermal hold duration.
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
- **Web playback now disconnects with body-joint torque OFF**, before waiting for
  any model. **Support the body.** The old web implementation left it powered.
  Motor 12 is never commanded; no all-motors torque-off, grip opening, or grip
  reassertion is introduced. The standalone `fret.py` CLI default is unchanged.
- During network inference, Stop discards late results and blocks further requests
  or dispatch. It cannot cancel an already-billed provider request. No automatic
  provider/model retry/fallback. Default audio timeout is 30s; text revision uses
  60s. The audio adapter's environment timeout remains configurable; a late response
  beyond the local stage deadline is discarded rather than authorizing motion.
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

```bash
guitar/.venv/bin/python -m pytest arm_controller/tests guitar/tests -q
node --test arm_controller/tests/capture.test.mjs
# Optional Playwright + installed Google Chrome; all /api requests are mocked:
guitar/.venv/bin/python arm_controller/tests/browser_check.py
```

Current result: **188 Python checks passed** (67 new + 121 existing). Tests prevent
real serial/provider access and cover bounded proposals, schema rejection,
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

No real arm, camera, microphone, paid inference, deployment, or training was exercised
by this implementation verification. A consented live audio endpoint check and a
separately approved supervised physical take are still required.
