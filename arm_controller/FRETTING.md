# Fretting tools — design notes and the safety contract

`fret.py` is the tool layer for the fretting arm (IDs 7–12 on
`/dev/cu.usbmodem5B790163191`). Like `pluck.py`, it is backend-agnostic:
`TOOLS` holds the schemas, `dispatch()` is the single entry point, and no
Baseten wiring exists yet by design.

## Where the mapping comes from (existing, NOT re-recorded)

- `guitar/robot/poses/fret_arm.json` — 110 poses: `above_s{s}_f{f}` and
  `touch_s{s}_f{f}` for strings 1–6 × frets 1–9, plus `rest` and `ready`.
  Recorded/fitted by the repo's fret-map pipeline (`guitar/robot/fretmap.py`)
  from hand-recorded anchors at frets 1/5/9 per string.
- `guitar/robot/calibration/fret_arm.json` — per-joint raw-count ranges and
  motor IDs (shoulder_pan=7, shoulder_lift=8, elbow_flex=9, wrist_flex=10,
  wrist_roll=11, gripper=12).
- String convention matches plucking exactly: **1 = high E (rightmost) …
  6 = low E (leftmost)**, per `fretmap.STANDARD_TUNING`.

## Unit conversion (the subtle part)

Pose values are LeRobot-normalized: body joints −100…100 across
`[range_min, range_max]`, gripper 0…100 (`use_degrees` is off). LeRobot wrote
each servo's homing offset into EEPROM at calibration time, so raw bus counts
already live in the offset-adjusted space — conversion is pure range math
(`fret.py:_to_raw`). **Verify on first powered run:** read present positions
at the parked pose and check they convert to ≈ the `rest` pose values; if
they're wildly off, the EEPROM offsets were cleared and everything must halt.

## Press depth

`press = touch + (mm / 10) · (touch − above)`, capped at **8 mm** — anchors
were recorded hovering 10 mm above the string (`fretmap.HOVER_MM`,
`MAX_PRESS_MM`). Default `press_mm = 4`. Tune by ear: buzzing = press deeper;
muted thud = check the fret map before pressing harder.

## ⚠ Safety contract (the fretting analog of the plucking interference rule)

Translating while touching the strings scrapes them (noise) and side-loads the
fingertip. Every action follows **LIFT → TRANSLATE → PRESS**:

1. **LIFT** — from a held fret, straight up to that fret's own `above` pose.
2. **TRANSLATE** — between `above` poses on the 10 mm hover surface. Long
   moves (>2 strings or >3 frets, or from an unknown start) route via `ready`
   for extra clearance, because joint-space interpolation between two distant
   hover poses can sag below the hover surface mid-path.
3. **PRESS** — straight down, slowly (`PRESS_SPEED`), only at the target.

`hold_fret` HOLDS until `release_fret` or the next `hold_fret` — holding is
the whole point (the plucking arm sounds the note while this arm holds).

**The gripper (ID 12) is never commanded — not position, not torque.** It
permanently holds the fingertip tool at deliberately limited torque
(`grip_torque=180/1000`, just under the servo overload trigger — see
`config_astra_so101.py` and `guitar/CONNECT.md`). Commanding it, or "restoring"
its torque limit the way the pluck arm's elbow gets restored, would either
drop the tool or trip overload protection. `fret.py` filters it out of every
raw target dict.

## Sustained-hold caveat (operator history)

`AGENTS.md`/`CONNECT.md` record thermal concerns on sustained grips/presses.
A hold is a continuous stall load on shoulder/elbow. Until qualified: keep
holds to a few seconds, watch servo temps (reg 63) during long passages, and
prefer `release_fret` between phrases. The overload protection that froze the
pluck arm's elbow (torque clamps to ~20% after ~2 s stall over the trigger)
exists on these servos too — if a press goes weak mid-hold, that's what
happened: lift, cool, re-press.

## Status / open items

- The fret-arm bus was **unpowered** at build time (2026-09-19): tools compile
  and pose math is verified, but no motion has run. First powered steps:
  scan IDs 7–12, the EEPROM-offset sanity check above, then `--hold 3 5` with
  a hand near the arm.
- Both arms on one machine: each tool layer owns its own port, so pluck and
  fret tools run simultaneously — but close the GUI controller bound to the
  same port first.
- Coordination (hold before pluck, release after decay) belongs in the
  backend loop, not in these tools.
