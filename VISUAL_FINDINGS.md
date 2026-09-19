# Lamp visual performance session — 2026-09-19 UTC

> **Separate lamp workstream / session evidence.** The camera findings, device state,
> candidate motion, and simulated guitar cues below do not define current guitar scope or
> qualify its physical hardware. See [guitar/DESIGN.md](guitar/DESIGN.md) and
> [guitar/STATUS.md](guitar/STATUS.md). This recorded evidence is retained unchanged below.

**Current update:** authenticated SDK commissioning and camera-supervised motion
are now working. See [SDK commissioning](SDK_COMMISSIONING.md) for subsequent
physical runs, the idle-clear fix, tracking limitations, and current state.
The section below is the historical first phase, before authentication repair.

**Status: software candidates implemented; physical improvement not demonstrated.**
The laptop camera and actual YouTube playback in Chrome were accessible. One
valid 12-second recording of existing idle was captured. No new motor command,
runtime restart, torque change, or idle-setting change was sent in this session.
The earlier 21 physical trials remain separate evidence, not trials of this code.

Starting guitarra commit: `ab8caee592a0f61de76a4348304c40baa8b3685d` (fetched from
`AcastaPaloma/guitarra`). Runtime source:
`fe874862b1ceaf151a6b37b184ab5ec12e09e6cd`.

## Access and actual blockers

- SSH to `lelamp@lelamp-2rcpv9ad` and HTTP via an SSH tunnel worked.
- Direct AVFoundation camera 0 provided an unmirrored view of the lamp, base,
  table and surrounding people. Photo Booth's preview was mirrored; it is not
  the recording reference. The robot's own camera is a separate device.
- Audience and future guitar direction have not been established physically.
  Simulation signs of +1 are placeholders, not stage calibration.
- `GET /api/sdk/v1/capabilities` still returns `unauthorized`: SDK token required
  but not configured. Authentication was not disabled. The dashboard's early
  acknowledgement route was not substituted for guarded clip execution.
- The runtime changed PID/start time during inspection: PID 47465 started at
  05:57:46 UTC, followed by PID 48989 at 06:01:31 UTC. Changes also appeared in
  `config/profiles/lights/raspberry_pi_neopixel.yaml`, with a `.bak` file. These
  were external changes and were preserved. A question requesting exclusive
  control during A/B trials remains unanswered. Restarts invalidate a stable
  experimental condition; their cause was not diagnosed.
- The runtime speaker route was Dummy Output. USB microphone capture from the
  Innomaker camera was available. The expected ReSpeaker USB array was absent,
  although a saved PipeWire input referred to an XVF3800. This supports previous
  configuration, not current direction sensing. Physical speaker installation
  is not the same as verified audible output. Perception was disabled.

Implementation commit: `f4afc86` (local). No code or footage was pushed.

No token was installed or runtime service restarted while concurrent control
remained unresolved. The remaining physical work needs a coordinated window,
an authenticated SDK, a chosen/checked stage pose, and a fresh clear camera view.

## Reference observations

These are **sampled screenshots during actual Chrome playback and paused
inspection**, not continuous frame-by-frame motion analysis. Player timestamps
below were visible in the player or checked after pausing. Stale accessibility
timestamps encountered during playback were not used to label unrelated images.
No audio timing or performer joint angles were measured. Some shots are edited,
cropped, blurred, or obstructed, limiting inference.

| ID / source | Video time | What was actually visible | Candidate interpretation, not a measured rule |
|---|---|---|---|
| R1 — [White Stripes, Jolene](https://www.youtube.com/watch?v=yXlULkwhgrc) | 00:22; 01:23; 03:28; 03:36 | Wide shot separates drummer and singer/guitarist. At 01:23 the singer stays near the mic with an inclined head. At 03:28 his head is lowered near the mic. At 03:36 a raised drumstick is visible; end cards obscure part of the picture. | Give attention and phrase accents readable destinations. This edited sequence does not establish motion velocity or cue timing. |
| R2 — [Stapleton / Timberlake, CMA](https://www.youtube.com/watch?v=3Nl2rdaddKw) | 03:57; 04:19; 07:05; 07:40 | Stapleton looks across/away from the microphone; the paused 04:19 face is turned toward image-left. Timberlake has a sideward gaze at 07:05. The 07:40 wide shot shows the audience standing, with performers small. | A sustained partner-facing pose may read more clearly than repeated short turns. The audience shot does not prove a particular cue caused a reaction. |
| R3 — [Civil Wars, Tiny Desk](https://www.youtube.com/watch?v=HamYmjllE6A) | 02:47; 03:45; 03:50 | At 02:47 the woman's face angles toward the guitarist. At 03:45 both faces are raised with rounded/open mouths; at 03:50 both smile while the guitarist looks down. | Separate performing, acknowledging the ending, and release. Do not infer exact musical boundaries from these sparse views. |
| R4 — [Rodrigo y Gabriela, Tiny Desk Home](https://www.youtube.com/watch?v=PMpGjox3TBs) | 01:15; 11:31; 22:02; 22:37; 22:41 | Seated pair, busy hands and comparatively restrained torsos. At 11:31 both look down at their instruments. Both are still playing at 22:37. At 22:41 one turns her head sideways while the other tilts his head back. | Supporting motion can be smaller while preserving attention. Fret positions and hand activity alone do not establish who is soloing. |
| R5 — [Bruno Mars, Treasure](https://www.youtube.com/watch?v=nPvuNsRccVw) | 00:57–01:02; 01:55–02:03 | Playback advanced through these passages. At 00:57 the lead has bent knees and an offset torso; at 01:02 the foreground performers lean their upper bodies forward. Wide ensemble samples at 01:55 and 02:03 show whole-body poses and changed orientation; strong light effects obscure details. | Supports the user's request for coordinated body movement as a design direction. It does not supply measured phase offsets, amplitudes, or a transferable human skeleton. |

The five-axis mapping is an authored interpretation: base yaw supplies body
turn, motor 2/base pitch supplies waist pulse, elbow pitch supplies opposing
rise/recoil, wrist roll supplies upper-body sway, and wrist pitch supplies a
smaller head accent. The chosen phase offsets are hypotheses for A/B testing.
No claim is made that every human joint continuously rotates, or that greater
amplitude alone makes a dance better.

## External baseline and timing limitations

`idle-baseline-02` began at **05:50:54.236480 UTC**, recorded 360 encoded frames
over 12 seconds and collected 69 position samples. Both status snapshots showed
`current_idle=idle`, `idle_playing=true`, `idle_paused=false`, no current animation,
and no last error. No beat track or command trajectory accompanied this run.

At nominal recording times 00:00, 00:02, 00:04, 00:06, 00:08 and 00:10, contact-sheet
samples show a changing head roll and lower-arm silhouette. The earlier views
are more folded, with the head visually nearer the base; later views are more
open. These are observations of existing idle, not proof of contact, sag, jerky
motion, or an interrupted performance. The view/framing was not calibrated or
stabilized for pixel displacement measurement.

HTTP request round-trip median was **26.3 ms**, maximum **197.8 ms**. The diagnostic
camera-PTS-to-log-receipt difference had median **63.3 ms**, range **54.1–128.7 ms**.
That calculation assumes comparable clocks; it does **not** calibrate physical
camera latency. Encoder capture timestamps and physical audio latency are
unknown. No claim about millisecond beat error is supported.

Position ranges, in normalized units, are saved in
[`evidence/visual-session-2026-09-19.json`](evidence/visual-session-2026-09-19.json).
Ranges are not commanded-minus-measured tracking errors.

`idle-baseline-01` was a capture failure: ffmpeg returned zero but encoded zero
frames because the original timestamp options did not reset the recording
timeline. It is excluded from visual evidence. `observe()` now uses
`-copyts -start_at_zero` and checks actual encoded-frame counts. A regression
test rejects a nominally successful zero-frame recording.

Media stays local in `/tmp/guitarra-rehearsal-20260919/`. No audience footage is
committed or published. A new A/B session must fix the camera and lighting and
record an audible beat reference; this baseline cannot substitute for that.

## Observation → implementation → verification

| Finding / hypothesis | Exact change | Software evidence | Physical result / limitation |
|---|---|---|---|
| User reports head-heavy movement and requests all five DOF; R5 suggests coordinated body participation | `band/performance/primitives.py::Wave`, `scene()`; `composer.py::wave_value`, `wave_bounds`, `compose()` | Both groove and supporting-solo intervals move all five axes. Waist and elbow use opposite signed amplitudes and different phases. Continuous sine turns retain curvature; C3 fades join the phrase to its held offset. | Zero candidate hardware runs. Selected amplitudes/dynamics are simulation planning values, not approved device calibration. |
| R2/R3/R4 suggest partner attention and phrase release | `scene()` primitives `yield_spotlight`, `support_solo`, `acknowledge_ending`; `profiles/{restrained,accented}.yaml` | Partner gaze remains a planned offset; support motion scales to 0.25. No sensor direction is inferred. | Partner sign, bow sign, readability and naturalness remain unverified. |
| Existing SDK adds an entry per clip; repeated clips could create phrase gaps | `composer.py::compose()` and `rehearsal/runner.py::build()` emit one 64-beat clip | Exact phrase landmarks preserved; 40 seconds at 96 BPM. No per-phrase API calls. | Initial entry remains runtime-controlled. This is prevention by composition, not a measured runtime defect or a removal of the safe entry. |
| Dashboard acknowledges before completion; SDK has a real action lifecycle | `band/adapters/lamp/client.py::connect`, `observe`, `upload_scene`, `play_clip`, `wait`, `cancel` | Tests distinguish accepted/running/succeeded, require checked completion, reject stale telemetry and unavailable capabilities, persist trial-key hashes, prevent replay across sessions, and confirm cancellation state. | Source-compatible adapter, not a successful live SDK trial. Success means executor completion, not endpoint accuracy. |
| Timestamp/capture failure during first baseline | `band/rehearsal/observe.py::observe`, `camera_result` | Nonzero frame count required; failed startup/capture is logged; request and receipt timestamps separated. | One subsequent successful 12-second capture. No physical latency calibration. |
| Need reviewable repeatable trials | `rehearsal/runner.py::build`, `execute.py::load_scene`, `execute` | Fixed beat WAV, cues, hashes, phase/support overrides, simulation-pose rejection, content verification, action/telemetry logs, cancellation on stale recorder or polling failure. | Executor is unscheduled; beat WAV is not automatically aligned or played. Other controllers are not excluded by this adapter. |

The full authored curve is checked for finite values, exact joint ownership,
position envelopes, conservative continuous velocity/acceleration/jerk bounds,
and C3 rest-boundary joins. Invalid plans are rejected without clipping or
shifting musical landmarks. Runtime CSV resampling and the servos are different
systems: these mathematical bounds do not prove physical jerk limits.

No runtime source was changed. There was no controlled reproduction justifying
changes to fusion, interpolation, entry transitions, scoped ownership, scheduled
execution, gains, tolerances, or elbow compensation. One complete clip avoids
between-phrase idle restoration; restoration after the clip and interference
from another controller still need a physical test.

## Rehearsal and controlled comparison

At 96 BPM the 40-second scene is: listen 0–2.5s, audience 2.5–5s, prepare/count-in
5–7.5s, five-axis groove 7.5–17.5s, accent 17.5–20s, cue guitarist 20–22.5s,
support solo 22.5–32.5s, acknowledge 32.5–35s, bow 35–37.5s, listen 37.5–40s.
Attention/ending phrases deliberately contain holds; continuous five-axis
oscillation applies to the performing phrases. Guitar and audience cues are
simulated. Singing and physical sound localization are not implemented.

`restrained` uses an 8-beat wave period; `accented` uses a 4-beat period and larger
but still provisional offsets. Preset contrast changes several parameters and
must not be reported as a one-factor experiment.

The prepared one-factor phase comparison keeps tempo, amplitudes, stage,
waveforms, cues and phrase durations fixed, changing `head_phase_beats` from 0
to 1. A separate support comparison changes only `support_scale` from 1 to 0.25.
Use repeated A/B and reversed-order B/A trials once physical preconditions hold.
Score continuity, readable intent, repetition and silhouette separately from
measured tracking and beat alignment. Predefine acceptable tracking thresholds
from commissioned pose trials; do not increase tolerances to make a run pass.

| Evidence item | Count / result |
|---|---|
| Valid external idle recordings | 1 (12 seconds); 1 earlier zero-frame failure |
| Physical runs of either new style | **0** |
| Controlled physical A/B pairs | **0** |
| Tracking-error or audible-beat improvement | **Not measured** |
| Subjective before/after naturalness score | **Not assigned** |
| Regression checks | **23 passing**, Python standard-library unittest |
| Logical runtime changes | **0** |

The last read-only status check still reported normal idle playing, idle not
paused, torque enabled, and no last runtime error. This is a state observation,
not a restoration test: this session did not change those settings.

Exact replay and execution prerequisites are in [`REHEARSAL.md`](REHEARSAL.md).
The original handoff's physical acceptance criteria remain outstanding.
