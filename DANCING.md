# Five songs, your recorded moves

Open [Dance on the lamp](http://192.168.0.226:8080/#dance) from your laptop on
the same network (or `http://100.95.68.2:8080/#dance` through Tailscale).
The existing paired dashboard hosts it; no extra service or serial owner.

## Play a 30-second dance

1. Refresh [Dance on the lamp](http://192.168.0.226:8080/#dance). The live backend
   is already version **3**; this stored-audio update needs **no robot restart**.
   Factory idle, boot movement, and startup scenarios remain disabled.
2. Keep your saved upright neutral, or set it in [Teach](TEACHING_UI.md).
3. Pick a song. Its **Saved audio clip** loads automatically from lamp storage,
   with its analyzed tempo and beat grid. Wait for **fully loaded and ready**.
   No YouTube player, internet connection, or upload is needed for these presets.
4. Press **Prepare dance** to validate and preview without moving the lamp or
   changing motor power. **Remix** varies the order and takes. Previews expire
   after three minutes. **Hear audio only** previews the song without movement;
   **Test laptop audio** plays three test tones. Check laptop mute and volume.
5. Clear the movement path and press **Start 30s dance**. The lamp first enters
   its saved neutral, then the fully decoded song and dance body share a future
   start time. The excerpt and choreography each last 30 seconds, followed by
   verification of final neutral. Keep the tab visible and supervise playback.
   An emergency-stop latch blocks Start and is never cleared automatically.
6. **Stop** cancels commands and sound while retaining motor holding. It does
   not release power or command a recovery move. Leaving/hiding the tab stops
   its dance. Lost heartbeats cancel remaining commands within four seconds.

### Where the music is saved

The five actual 30-second, stereo 48 kHz WAV clips are on this lamp at
`/home/lelamp/lelamp-hackathon-2026/static/media/dance-clips/` (about 29 MB).
They survive page refreshes and robot restarts and are available to other paired
laptops. The dashboard fetches a selected clip over the local connection and
finishes decoding it before Start is enabled. No music-service request is made
during playback. Sound comes from the **laptop**, not the lamp's Dummy Output.

Source recordings and selected starts are recorded in the runtime's
`static/dances/audio_clips.json`, along with analyzed beat times and SHA-256
checksums. Each excerpt starts near 30 seconds into its source, shifted onto
an estimated beat. The downloader was used only during installation; no full
songs, cookies, streaming previews, or downloader service are part of this UI.
The local WAVs are ignored by Git and are not bundled into the source patch.
Back up those five files separately if moving/reinstalling the lamp.

| Preset | Source recording | Excerpt BPM |
|---|---|---:|
| Waterloo | [ABBA / AbbaVEVO](https://www.youtube.com/watch?v=Sj_9CiNkkn4) | 146.8 |
| Superstition | [Stevie Wonder](https://www.youtube.com/watch?v=ftdZ363R9kQ) | 98.75 |
| Around the World | [Daft Punk](https://www.youtube.com/watch?v=K0HSD_i2DvA) | 120.35 |
| Seven Nation Army | [The White Stripes](https://www.youtube.com/watch?v=0J2QdDbelmY) | 125.15 |
| Take Five | [The Dave Brubeck Quartet](https://www.youtube.com/watch?v=ryA6eHZNnXY) | 171.9 |

These are estimated beats, not a verified score or downbeat transcription.
Motor limits and pose amplitudes remain unchanged.

### Optional custom clips

**Choose audio file**, set its excerpt start, optionally **Analyze beats**, then
**Save 30s clip**. Alternatively, expand the direct-download field and use a
downloadable HTTPS audio-file URL; CORS restrictions may require choosing a local
file instead. Downloads are bounded to 15 seconds and 25 MB.

Custom clips are trimmed to a 30-second PCM WAV and saved, with beat metadata, in
this laptop browser's IndexedDB. Save confirms the transaction committed; a failed
replacement preserves the previous file. Reload restores the custom clip in
preference to the preset. Custom files are not uploaded to the lamp and are
specific to this browser/dashboard address. Keep the originals: clearing site
data, private browsing, or browser eviction can remove that custom copy. The
on-lamp presets are unaffected.

**Beat track only (test)** is an explicit optional metronome, never an automatic
fallback for a missing or failed song. Missing/failed audio cannot start a silent
dance.

### Synchronization and failure handling

The local audio buffer is decoded before Start. Start unlocks laptop audio,
requests neutral entry, and then schedules Web Audio against the backend's
future count-in timestamp using measured server-clock offset. It acknowledges
that exact timestamp before the dance body is admitted. A slow connection, missed
deadline, suspended audio context, or missing readiness fails visibly and cancels
playback; it never speeds motors up to chase delayed music.

This is browser/network synchronization, not a guarantee of sample-accurate
physical tracking or audible speakers. **Test laptop audio** checks the physical
output. The audio-ready acknowledgement confirms scheduling, not actual sound.

Decode, storage, download, Prepare, Start, and heartbeat operations have explicit
timeouts. Errors, completion, Stop, and lost connections release UI ownership
instead of leaving the page in Starting/Dancing. The old **Starting YouTube**
wait is removed entirely; refresh if it still appears.

Earlier failures also included the event bus cancelling its behavior subscriber
after 30 seconds because entry/count-in were inside the dance handler. Admission
now returns promptly and completion is handled separately; the global event-bus
timeout and motor limits were not raised. Final neutral is checked before success.
Errors and Stop cancel commands without releasing torque, clearing safety, or
scheduling an automatic recovery move.

### If the saved WAV opens but Start is disabled

Chromium at a 44.1 kHz output rate decoded the exact 30-second/48 kHz WAV as
**29.99997732426304 seconds** (1,322,999 frames). The original strict duration
check rejected that one-frame rounding loss with “Audio needs at least 30 seconds,”
leaving no loaded clip and Start disabled. A normal audio player still played it.

The frontend now adds silence only for a resampling gap of at most one millisecond,
giving subsequent checks and playback an exact 30-second buffer without changing
any existing sample or motor timing. Genuinely short files still fail. Refresh;
no robot restart is needed. Text beneath Start now names its blocking condition,
and **Retry saved audio** retries a failed load without restarting anything.

The real-Chromium regression uses the actual five WAV files at 44.1 and 48 kHz,
clicks Prepare → Start, verifies 30-second Web Audio scheduling and acknowledgement,
and clicks Stop. All robot APIs are intercepted and browser output is muted; this
tests real decoding and the UI, not physical motor tracking or speaker audibility.

After deployment, a separate operator-started Waterloo run was observed through
read-only status checks progressing from `playing` to `completed`, with
`audio_mode: laptop_file`, `audio_ready: true`, and no backend error. The agent
did not issue its Start or any movement command. Readiness confirms browser
scheduling, not acoustic audibility at the listener.

### If you previously saw “405 Method Not Allowed”

Refresh the dashboard to load the corrected frontend. The older robot backend
returns 405 (rather than 404) for new Dance URLs because its generic API route
only supports OPTIONS. The UI now recognizes both responses and displays
**Load dance update**, with playback disabled until the new backend is ready.
It retries read-only readiness checks through temporary startup errors; it never
restarts automatically. Support the lamp before confirming the restart.

The fix was tested against the actual running legacy backend with the GET-only
`tests/dancing_legacy_backend_smoke.cjs` check, as well as simulated 404/405 and
temporary 503 startup responses. HTML error pages are no longer dumped into the
dashboard. The frontend build and all 29 frontend tests passed after this fix.

### If Prepare briefly loaded and then disappeared

Refresh the page for the preview-persistence fix; no robot restart is needed.
The runtime correctly returned a prepared dance, but its idle status contained
`id: null`. The UI incorrectly matched that against its own empty playback ID
and cleared the preview every half-second. Only an actual owned playback can
now consume a preview, and delayed status responses from before Start/Stop are
ignored. The header says **Ready to dance** when preparation succeeds.

The regression test now uses the real null-valued idle response and verifies
the preview survives several polls, including a delayed pre-start response.
`tests/dancing_live_prepare_smoke.cjs` also exercises the actual runtime and
React Prepare flow, retaining the choreography and enabled Start button across
multiple idle polls. That probe permits only GETs and non-moving preparation;
it cannot start sound, move the lamp, or restart it.

### Lamp-speaker availability

Dance audio currently plays on the laptop. A read-only device check on this lamp
on 2026-09-19 found only PipeWire's **Dummy Output**: no USB playback device,
no known Bluetooth speaker, and both HDMI connectors disconnected. A saved
ReSpeaker input preference exists, but that USB device is not enumerated.
Speaker playback cannot be verified until a real audio output is connected;
the device configuration and output routing have not been changed.

## Five presets

These are approximate tempo references, not analysis of a bundled master.
The selected excerpt's estimated beat times can replace each fixed grid.

| Song | Genre | Nominal BPM | Meter |
|---|---|---:|---|
| [Waterloo — ABBA](https://songbpm.com/@abba/waterloo) | Pop | 148 | 4/4 |
| [Superstition — Stevie Wonder](https://songbpm.com/@stevie-wonder/superstition) | Funk | 100 | 4/4 |
| [Around the World — Daft Punk](https://songbpm.com/@daft-punk/around-the-world) | House | 121 | 4/4 |
| [Seven Nation Army — The White Stripes](https://songbpm.com/@the-white-stripes/seven-nation-army) | Garage rock | 124 | 4/4 |
| [Take Five — The Dave Brubeck Quartet](https://songbpm.com/@dave-brubeck/take-five) | Jazz | 174 | 5/4 |

Each has a distinct preferred order and pace: bounce-led pop, nod/bounce funk,
sway-led house, deliberate rock gestures, and five-beat jazz phrases. A dance
must contain at least two different valid takes. Remix rotates order and take
variants; it does not invent or enlarge poses.

## How the recorded actions become speed-adjustable

The nine original CSVs are archived unchanged in [assets/teaching](assets/teaching).
The live compiler reads the robot's saved `teach_*.csv` bank. It selects a
contiguous energetic 3.2-second phrase (4.5 seconds for bows) from a long take,
or the whole take when shorter. The preview shows exactly which take and source
window are used. Teach replay still plays full takes at their original timing.

Dance playback changes the **clock**, not the pose amplitude or calibration:

- Maximum average playback rate is 2×. Each action also has a tighter derived
  cap from its steepest joint-position change and the robot's configured speed
  limit. The first/last 10% of each phrase ease its clock to rest; the extra
  peak rate of that easing is included in the cap.
- All five joints share that clock. Samples are interpolated at the controller
  rate; raw recordings are never rewritten. An overly fast recorded action
  can therefore be slowed down into a valid dance phrase.
- The dance budget is **65% of the configured velocity ceiling**: on this lamp,
  195 of 300 normalized units/s, not degrees/s or a measured physical speed.
  The entry to neutral uses the existing bounded neutral connector.
- Entry, gesture, and exit boundaries snap to beats, with whole phrases spanning
  complete bars. A big action occupies more beats instead of accelerating past
  its cap. Remaining time holds neutral so the routine is exactly 30 seconds.
- Every phrase goes **neutral → recorded phrase → neutral** with eased
  connectors. Motor feedback verifies arrival before the next phrase and at
  the finish using the existing per-joint tolerances.
- Complete paths are checked for position limits, velocity and modeled
  self-collision, including transitions. Missing neutral/calibration, changed
  source files, stale previews, unsafe paths and unavailable feedback fail closed.
- A late frame cannot trigger overspeed catch-up. More than 180 ms of timeline
  lag stops the dance. A missed/slow network count-in stops rather than starting
  audio late. Error/Stop never schedules an extra recovery movement.

These are command-side safeguards, not a guarantee of actual motor tracking,
load capacity, external clearance, or exact acoustic synchronization. No motor
speed/torque settings, calibration, or existing arrival tolerances were raised.
Supervise the first physical rehearsal with an unobstructed movement envelope.

## Source, deployment, and reproducible checks

The live runtime source is `/home/lelamp/lelamp-hackathon-2026`, on its local
`guitarra-dance-start-readiness` branch. Its source changes are preserved here in
[runtime-patches/teaching-ui.patch](runtime-patches/teaching-ui.patch), now
including both Teach and Dance. This targets original runtime commit `2fb7457`;
do not reapply it to the already-patched lamp. For another compatible checkout,
first use `git apply --check`, then apply and build the dashboard with
`npm run build` in `apps/dashboard/frontend`. The patch includes the persistent
idle-disable configuration, shared song catalog, API/compiler, UI, and tests;
compiled assets are built rather than embedded in the patch.

Never copy the archived reference neutral onto a different calibration. Saved
takes use this device's normalized coordinates and require validation against
the destination robot's geometry and calibration before use.

Read-only preflight (no motor controller is created or connected):

```sh
/home/lelamp/lelamp-hackathon-2026/.venv/bin/python tools/validate_taught_dances.py \
  --runtime /home/lelamp/lelamp-hackathon-2026
```

[Saved preflight results](evidence/taught-dances-preflight-2026-09-19.json) cover
all five songs at three variations using all nine available takes, the live
calibration, neutral, and collision model. All 15 routines passed at 30 seconds;
maximum commanded peak was 185.25 normalized units/s. These are offline checks,
not evidence of a physical rehearsal. No restart or movement was performed to
test this addition; the running lamp was last checked stationary with idle off.

Runtime backend checks:

```sh
.venv/bin/python -m pytest tests/unit/test_dancing.py tests/unit/test_dance_lifecycle.py tests/unit/test_teaching.py \
  tests/unit/test_idle_route.py tests/unit/test_sdk_gateway.py tests/unit/test_robot_registry.py -q
DANCE_REALTIME_TEST=1 .venv/bin/python -m pytest \
  tests/unit/test_dance_lifecycle.py::test_full_30_second_dance_survives_default_bus_timeout -q
node tests/dancing_dom_smoke.cjs /path/to/node_modules/jsdom
node tests/dancing_storage_dom_smoke.cjs /path/to/node_modules/jsdom /path/to/node_modules/fake-indexeddb
node tests/dancing_audio_assets_smoke.cjs --live
node tests/dancing_audio_browser_smoke.cjs /path/to/node_modules/playwright-core
DANCE_AUDIO_RATE=48000 node tests/dancing_audio_browser_smoke.cjs /path/to/node_modules/playwright-core
node tests/teaching_dom_smoke.cjs /path/to/node_modules/jsdom
```

The DOM checks use jsdom 26, real React components, fake APIs and fake audio.
They cannot command hardware. Frontend unit tests use Node 22's TypeScript
stripping: `node --experimental-strip-types --test tests/*.test.mjs` from the
frontend directory. `npm run build` type-checks and builds production assets.
The guitarra regression suite is `python3 -m unittest discover -s tests`.

Latest stored-audio checks on 2026-09-19: **39 frontend tests**, the production
build, React Teach/Dance/storage interaction checks, the live non-moving Prepare
probe, and all **45 guitarra tests** passed. The storage check includes transaction
abort/replacement, refresh/remount, selected-song re-click, default preset loading,
scheduled 30-second playback, completion/Stop, and stalled-request handling.

The device-local asset probe checks all five actual WAV durations, hashes and HTTP
delivery, then prepares each actual beat grid at three variations without movement.
[Saved results](evidence/stored-dance-audio-2026-09-19.json) are not evidence of a
physical rehearsal. The backend suite also passed **280 tests** (two optional
real-time tests skipped), and the separate full 30-second local-audio/fake-motor
regression passed in 35.49 seconds. No Python backend changes are required for
stored audio.

The DOM checks use fake audio and cannot confirm your speakers. The physical lamp
was not restarted or moved, and its idle, torque, and safety state were not changed
by this update. Removed YouTube frontend/player tests remain recoverable in Git;
backend YouTube compatibility is retained for older clients but unused by this UI.
