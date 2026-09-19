# Lamp Teach dashboard

> **Separate lamp workstream.** This dashboard, device address, and torque procedure are
> not a UI or setup path for the guitar arms. Follow [guitar/DESIGN.md](guitar/DESIGN.md),
> [guitar/SETUP.md](guitar/SETUP.md), and [AGENTS.md](AGENTS.md) for the current guitar task.
> The existing lamp guide is otherwise retained.

Open [Teach on the lamp](http://192.168.0.226:8080/#teach) from a laptop on the
same network. The hostname alternative is
`http://lelamp-2rcpv9ad.local:8080/#teach`; the IP can change with DHCP. This uses
the existing dashboard pairing and CSRF protection. The dashboard is already
hosted by `lelamp-runtime.service`, including after a device reboot.

For beat-matched 30-second routines using your saved takes, see the separate
[Dance tab guide](DANCING.md). Dance retimes disclosed excerpts; Teach replay
continues to preserve full recordings and their original timing.

## Factory motion is disabled on this lamp

`config/local/robot.local.yaml` in the live runtime persistently disables idle,
boot motion, startup scenarios, automatic talking animation, and environment
entry scan motion. The configuration loader was checked against the device's
actual profile. Clearing idle in memory alone did not survive a robot restart.
The controller now enforces `idle_motion.enabled: false` for both static and
generated idle, rejecting later restore attempts; startup does not select a
fallback idle. Explicit taught actions and the saved neutral action still work.

The current process was stopped through the existing clear-idle/stop endpoints,
without releasing motor power or restarting it. The persistent configuration
and controller guard are loaded on its next normal restart. Re-enabling factory
motion requires deliberately changing the local configuration; no automatic
re-enable is performed by Teach.

## First use

The frontend is built and served. The running robot process still needs to load
the new backend. If the Teach tab displays **Load recorder update**, support the
head and arms, then click that button. It stops and starts the robot through the
existing dashboard controls; restart can release torque and cause startup motion.
The panel enables recording only after the backend advertises teaching UI version
2 (save-only capture plus neutral sequencing). No restart or physical movement was
initiated while adding neutral support.

Before your first replay, define the physical center—motor zero is not assumed:

1. Support the head and arms, click **Position by hand**, and confirm the release.
2. Place the lamp upright, centered, with room to move. Hold it still and click
   **Save current pose as neutral**. Saving does not enable motors; keep supporting
   it while they are released. A replacement requires confirmation.
3. Clear the path and click **Go to neutral** to power the motors and move to the
   saved pose. This action is also available independently of your recorded takes.

Then record and iterate:

1. Choose a gesture name or suggestion. Take numbers are automatic.
2. Support the lamp and click **Start recording**. It stops idle/playback, verifies
   torque release, and samples the joints through the existing runtime owner.
3. Guide the gesture, then click **End & save**. The motors remain released.
4. Click a saved take in **Your takes**, or **Replay selected**, to power the motors
   and run **neutral → recorded move → neutral**. Keep the movement path clear.
   **Stop replay** cancels the sequence and retains power; it does not return home.
5. Support the lamp again and click **Record again** for a new take. Previous
   takes remain in the bank. Idle remains off during the session.

The replay handoff first sets the holding target to the measured pose before
enabling torque. This prevents enabling with an old target after hand guidance.
It does not establish physical load-bearing performance; supervise the first
small recording and replay. UI and mocked motor tests cannot verify hardware
tracking or clearance around the lamp.

## Saved data and playback

The live robot pack stores takes at:

`/home/lelamp/lelamp-hackathon-2026/static/robots/lelamp_v1/pi5_feetech_r1/animations/factory_v1/teach_<gesture>_tNN.csv`

Each CSV retains measured joint values and actual capture timestamps. Saves
write a temporary file, flush it to disk, then publish the complete file without
overwriting an existing name. Failed writes retain the take in runtime memory
for a retry; unsaved data cannot survive a process restart. A stopped recorder
thread must finish before saving. The bank reads saved files from disk, so it
survives page reloads and process restarts.

The neutral pose is persisted atomically in `teaching_neutral.json` alongside the
CSVs. It includes all joint positions, robot/calibration identity, units, and save
time. Missing, invalid, or mismatched neutral poses block replay; recalibration
requires capturing neutral again. Neutral capture checks the complete stationary
pose for joint limits and self-collision without commanding movement.

Teaching replay validates the full route (including the return) for joint ranges,
speed and self-collision before powering motors. It moves from the current pose
to neutral, verifies neutral was reached using the runtime's existing per-joint
tolerances, gently moves to the recording's start, plays the original samples,
and gently returns to neutral. The final pose is verified too. Failure to reach
neutral prevents the recorded action. Stop, cancellation, or an execution error
prevents further phases; no automatic recovery movement is attempted.

Recorded targets and time intervals remain intact. No smoothing, amplitude
scaling or speed adjustment is applied to the recorded segment, and existing
CSVs are not rewritten. The neutral wrapper applies to `teach_*` playback even
through older controls, but not unrelated factory animations. Invalid paths are
rejected with a visible error. Encoder positions are playback targets, not a
guarantee of identical physical tracking or clearance from external obstacles.

## Source and validation

Implementation is in `/home/lelamp/lelamp-hackathon-2026`:

- Dashboard: `apps/dashboard/frontend/src/views/TeachingView.tsx`, its styles,
  naming helpers, API types/client, and the Teach navigation entry.
- Capture: `apps/robot_runtime/web/routes/recording.py`.
- Replay: `apps/robot_runtime/web/legacy_routes/animations.py`, the motion manager
  and controller, `modules/robot_base/control/teaching.py`, and the opt-in Feetech
  measured-pose holding handoff.
- Regression checks: `tests/unit/test_teaching.py`, frontend
  `tests/teaching.test.mjs`, and `tests/teaching_dom_smoke.cjs`.

`runtime-patches/teaching-ui.patch` preserves both Teach and Dance source changes in the guitarra
repository. Apply it only to a compatible runtime checkout where it is not
already applied, then rebuild the dashboard with `npm run build` in
`apps/dashboard/frontend`. Compiled assets are not included in the patch.

Run focused backend tests with the runtime environment:

```sh
.venv/bin/python -m pytest tests/unit/test_teaching.py tests/unit/test_idle_route.py tests/unit/test_sdk_gateway.py -q
```

The frontend unit tests require Node 22 or newer for TypeScript stripping.
The React interaction check runs with `node tests/teaching_dom_smoke.cjs
/path/to/node_modules/jsdom` (jsdom 26). It tests record/save/replay, error recovery,
numbered retakes, neutral lockout/save/go-to, remount persistence and the backend
version gate with simulated APIs; it never commands hardware. Neutral tests cover
persistence, calibration mismatch, failed saves, collision rejection before motor
activation, failure to reach neutral, and cancellation between phases or during
baseline reads. Chromium automation on this Pi timed out while
navigating even the existing dashboard, so visual browser verification remains
pending. The code retains the runtime's existing calibration and motion limits.
