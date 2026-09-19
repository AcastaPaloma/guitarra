# Five songs, your recorded moves

Open [Dance on the lamp](http://192.168.0.226:8080/#dance) from your laptop on
the same network (or `http://100.95.68.2:8080/#dance` through Tailscale).
The existing paired dashboard hosts it; no extra service or serial owner.

## Play a 30-second dance

1. If **Load dance update** appears, support the head and arms before clicking
   it. This restarts the robot process and can release motor holding. The new
   frontend is already served; the new backend needs this supervised restart.
   Factory idle, boot movement, and startup scenarios remain disabled.
2. Keep your saved upright neutral, or set it in [Teach](TEACHING_UI.md).
3. Pick a song, then **Prepare dance**. This validates and previews the plan
   without moving the lamp or changing motor power. **Remix** changes its order
   and choice of takes. Previews expire after three minutes.
4. **Hear audio only** previews sound without motor commands. A built-in
   metronome works immediately. For the actual song, **Attach audio**, choose
   an excerpt start, and **Analyze beats**, then prepare again. Files stay in
   this browser's memory, are never uploaded, and need reattaching after reload.
5. Clear the movement path and press **Start 30s dance**. It safely enters the
   saved neutral, counts in, and schedules laptop audio and the lamp together.
   Keep the tab visible and supervise playback. Entry/count-in are additional
   to the 30-second choreography, not taken out of the excerpt.
6. **Stop** cancels remaining commands and sound while retaining motor holding.
   It does not release power or command a return home. Leaving/hiding the tab
   stops its dance; a missing heartbeat cancels commands within four seconds.

No original song recordings or lyrics are bundled. The ready-to-use beat tracks
are metronomes, not substitutes for the songs. Use audio you have permission to
play. The audio analyzer estimates onset timing near the chosen tempo; it does
not guarantee the correct downbeat, meter, or tempo of every recording. Preview
and adjust the excerpt/tempo, especially for intros, live versions, or jazz.

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
`guitarra-beat-matched-dances` branch. Its source changes are preserved here in
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
.venv/bin/python -m pytest tests/unit/test_dancing.py tests/unit/test_teaching.py \
  tests/unit/test_idle_route.py tests/unit/test_sdk_gateway.py tests/unit/test_robot_registry.py -q
node tests/dancing_dom_smoke.cjs /path/to/node_modules/jsdom
node tests/teaching_dom_smoke.cjs /path/to/node_modules/jsdom
```

The DOM checks use jsdom 26, real React components, fake APIs and fake audio.
They cannot command hardware. Frontend unit tests use Node 22's TypeScript
stripping: `node --experimental-strip-types --test tests/*.test.mjs` from the
frontend directory. `npm run build` type-checks and builds production assets.
The guitarra regression suite is `python3 -m unittest discover -s tests`.

Verification on 2026-09-19: all 251 runtime unit tests passed (`tests/unit`),
28 frontend tests passed, both React DOM interaction checks passed, production
build passed, and all 45 guitarra tests passed. No hardware rehearsal is claimed.
