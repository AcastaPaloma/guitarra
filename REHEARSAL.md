# Rehearsal commands and remaining commissioning

Run from the guitarra checkout with Python 3.10 or newer. The harness uses the
standard library. Profiles use JSON syntax, a YAML 1.2 subset. No model call is
made in the motion timeline.

## Compile and check without moving hardware

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 -m band.rehearsal.runner --preset restrained --output rehearsal-runs/restrained
python3 -m band.rehearsal.runner --preset accented --output rehearsal-runs/accented
python3 -m band.rehearsal.runner --preset accented --head-phase-beats 0 --output rehearsal-runs/phase-a
python3 -m band.rehearsal.runner --preset accented --head-phase-beats 1 --output rehearsal-runs/phase-b
python3 -m band.rehearsal.runner --preset restrained --support-scale 1 --output rehearsal-runs/support-a
python3 -m band.rehearsal.runner --preset restrained --support-scale 0.25 --output rehearsal-runs/support-b
```

Each output directory must be new. It contains `scene.csv`, `beat.wav`, and
`manifest.json` with trajectory hash, exact landmarks, preset and stage record.
Changing tempo may reject a curve against the declared dynamic limits; that is
an intended failure, not a request to silently clip or retime it.

**The bundled stage is simulation-only. Its zero pose must never be sent to the
lamp.** `execute.py::load_scene()` explicitly rejects it before connecting.
Its offset and derivative bounds are demonstration inputs, not hardware
calibration. Derivative units are normalized units/s, /s² and /s³.

## Capture read-only external evidence

Create the HTTP tunnel through an authenticated SSH session:

```sh
ssh -N -L 127.0.0.1:18081:127.0.0.1:8081 lelamp@lelamp-2rcpv9ad
```

Use a local ffmpeg executable with AVFoundation support. Enumerate cameras,
select the physical camera, inspect its full view, and verify mirroring before
capture. The session used `0:none` (MacBook Pro Camera, no microphone).

```sh
ffmpeg -hide_banner -f avfoundation -list_devices true -i ''
python3 -m band.rehearsal.observe --base-url http://127.0.0.1:18081 --seconds 12 --ffmpeg /absolute/path/to/ffmpeg --camera 0:none --output rehearsal-media/idle-01
```

The observer sends only HTTP GETs. Request times bracket HTTP calls; they are
not encoder acquisition times. Frame PTS and log receipt times are saved
separately. A process exit code of zero alone is not successful capture.
Long rehearsal captures should use 60–90 seconds to include runtime entry and
settling. This recorder's current video-only output does not provide an audio
reference; audio/video delay calibration and beat recording remain to implement.

## Supervised hardware execution — not yet exercised

Before the first trial, coordinate exclusive motion/service control and clear
the visible workspace. Configure an SDK token through the robot's existing
protected environment configuration, retaining authentication, in that coordinated
window. Do not print the token or commit it. Restarting the service was deferred
because another operator/process restarted it during this session.

Establish a stable planned stage pose, physically label audience/guitar and bow
directions, and check small paths with the existing collision guards and camera.
Keep the runtime as the only serial owner. Record exact `robot_id` and
`calibration_id` from authenticated `/api/sdk/v1/joints`, a local pose-specific
envelope, and evidence run IDs in a separate stage JSON. Never derive a universal
elbow correction from the reconnaissance errors. Successful SDK collision
validation covers the model, not people, cables or the table environment.
The full-scene executor requires `hardware_verified: true` and traceable
`verification_runs` in that record; only set them after those small physical
trials establish the specific envelope. Fabricating a run ID does not commission
a stage. Initial small supervised probes are separate from full-scene playback.

Then compile with that commissioned stage and start the external observer in a
separate terminal. This command **will command the robot** once its preconditions
pass; it is provided for the pending supervised trial:

```sh
python3 -m band.rehearsal.runner --preset accented --stage /absolute/path/to/device-stage.json --output rehearsal-runs/device-accented
python3 -m band.rehearsal.execute --scene rehearsal-runs/device-accented --camera-log rehearsal-media/trial-01/camera-log.jsonl --output rehearsal-runs/device-trial-01
```

`LELAMP_SDK_TOKEN` must be securely set in the invoking environment. No token is
accepted on the command line. HTTP credential transport is limited to localhost
for an SSH tunnel; other hosts require HTTPS. Redirects are rejected.

The executor verifies the scene hash and recomposition, device/calibration,
fresh joint telemetry, advertised capability and collision checking. It uploads
one complete clip and waits for its action's terminal result. It logs states and
feedback and requests cancellation on a polling/camera fault. A failed cancel is
reported as unknown state needing inspection. `system.stop` is deliberately not
used as a pause because the inspected runtime releases torque there.

Existing runtime entry happens before the authored 40 seconds and can change
with the live starting pose. `beat.wav` begins at authored musical zero; the
executor does not yet schedule it or know physical musical zero. Do not press
play on the beat at HTTP acknowledgement and call that synchronized. A complete
physical A/B needs an audio reference, measured time uncertainty and actual
entry completion. Scheduled execution or an exposed start event should only be
added after the experiment demonstrates that need.

Use a unique output directory and trial key for each intended trial. The SDK
client's ledger rejects reusing a key for changed payloads or another session.
A lost submission response stays pending; reconcile that action instead of
submitting another trial. A new trial directory is not a recovery mechanism
for an uncertain old action.

Record baseline and variant under the same stage, camera, lighting, tempo and
audio conditions. Repeat both styles after the one-factor trials. Compare
commanded and measured paths only after establishing entry/musical time, and
keep visual judgments separate from encoder accuracy. Confirm restoration of
normal idle after successful completion; on a fault inspect/hold instead of
automatically resuming movement. No restoration claim is made for this new
client until a physical run verifies it.
