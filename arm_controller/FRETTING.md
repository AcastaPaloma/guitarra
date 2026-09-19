# Fretting tools — v2 grid mapping and safety contract

`fret.py` is the tool layer for the fretting arm (IDs 7–11 + gripper 12 on
`FRET_PORT` — the port re-enumerates on replug, check `ls /dev/cu.usbmodem*`).
Backend-agnostic: `TOOLS` holds the schemas, `dispatch()` is the entry point,
no Baseten wiring yet by design.

## v2 mapping (2026-09-19) — supersedes the old fret map

The operator re-recorded keypoints because the old 110-pose map
(`guitar/robot/poses/fret_arm.json`) proved **inaccurate — do not fall back to
it or to the fretmap interpolation pipeline while this section stands.**

- Source of truth: `keyframes_arm2.json`, recorded with the keyframe GUI in
  **raw servo counts** (no unit conversion anywhere in v2).
- One keypoint per cell, named `pose-r{R}-c{C}`:
  - `r` = fret row, **only frets 1–3 are supported for now** (r4 was partially
    recorded and is deliberately skipped by the loader).
  - `c` = string, same convention as plucking: **1 = high E (rightmost) …
    6 = low E (leftmost)**, open notes E4 B3 G3 D3 A2 E2.
- `rest` is the recorded safe park pose and the transit hub.
- Loader quirks handled explicitly (see `--list` warnings): a duplicate
  `pose-r3-c5` (first recording wins — the second looked like a different
  spot) and out-of-range names are skipped with warnings, never silently.
- **Known gap: (string 6, fret 3) has no keypoint.** The skipped `pose-c3-r6`
  entry may be it, mislabeled/transposed — its shoulder_pan fits the r3 row
  trend. Operator to confirm and rename it `pose-r3-c6` (GUI Edit dialog),
  or re-record the cell.

## ⚠ Safety / interference — v2 contract

The v2 grid has no above/touch pairs, so there is **no hover surface** to
translate along. Until hover keypoints exist, **every transition routes
through `rest`**: press → rest → press. Slower than hovering, but it cannot
scrape strings or the neck, and it cannot drag the fingertip laterally while
in contact. If transit speed becomes a problem, record per-cell hover
keypoints and restore the LIFT→TRANSLATE→PRESS staging (implementation is in
this file's git history, commit d6f5d7f).

**The gripper (ID 12) is never commanded — not position, not torque.** It
permanently holds the fingertip tool at deliberately limited torque
(`grip_torque=180/1000`, just under the overload trigger — see
`config_astra_so101.py` and `guitar/CONNECT.md`). `MOTOR_IDS` in `fret.py`
simply doesn't contain 12.

## Press depth

v2 keypoints were recorded already pressed — there is no press_mm parameter
anymore. If a note buzzes, re-record that cell pressed slightly deeper via
the GUI (jog arrows on wrist/elbow), don't add offsets in code.

## Sustained-hold caveat (operator history)

Holds are continuous stall loads. The same overload protection that froze the
pluck arm's elbow (torque clamps to ~20% after a ~2 s stall past the trigger)
exists on these servos: if a press goes weak mid-hold, lift, cool, re-press.
Keep long holds bounded and watch temps (reg 63) during long passages.

## Tools

- `hold_fret(string, fret)` — press and HOLD until released/re-targeted.
- `release_fret()` — back to rest, string rings open.
- `get_fret_position(string, fret)` — exact raw targets + recorded cell list,
  no motion, works without hardware.
- `fret_rest()` — park.

Coordination (hold before pluck, release after decay) belongs in the backend
loop, not here.
