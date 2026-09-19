# Arm Calibration — baseline pose, geometry, and the XYZ layer

**Scope:** the single working tap/fret arm, motor IDs 7–11 (gripper 12 holds
the fingertip tool, never commanded). Recorded 2026-09-19 from the live rig.

## Why

Keypoints used to be raw servo counts only. That plays back fine, but a
model can't reason about them spatially. The XYZ layer gives every pose a
coordinate in ONE fixed world frame: however a planner chooses to approach a
point in 3D, the same joint pose always lands the fingertip at the same
(x, y, z) — so a model can later say "2 cm toward the nut, 0.3 cm above the
strings" instead of guessing counts. Raw counts stay the played source of
truth; degrees + XYZ ride along as derived views.

## Baseline (reference) pose — captured, do not lose

Snapshotted from the physical arm on **2026-09-19T17:37:11**, committed in
`calibration_arm2.json`:

| motor | joint       | ref count |
|-------|-------------|-----------|
| 7     | base yaw    | 2058      |
| 8     | shoulder    | 2000      |
| 9     | elbow       | 2195      |
| 10    | wrist_flex  | 2970      |
| 11    | wrist_roll  | 1099      |

Physical configuration at capture (operator's measurements, see
`~/Downloads/IMG_7734.JPG` for the rig photo):

- link1 (motor 8 → 9) **straight**, continuing the base column
- link2 (motor 9 → 10) at **90°** to link1, horizontal toward the guitar
- link3 (motor 10 → tip) at **90°** again, reaching straight down,
  rubber fretting tip at its end

All joint angles are defined as **0° in this pose**; degrees in keyframes
are signed offsets from it. Re-capture ONLY if the rig is re-assembled
(re-run the snapshot: read all positions, `kinematics.save_reference()` —
or SET REFERENCE on the webapp's `/calibrate` page).

## Measured geometry (constants in `calibration_arm2.json`)

| constant        | value   | meaning                                  |
|-----------------|---------|------------------------------------------|
| `shoulder_z_cm` | 10.0    | motor 8 axis height above ground         |
| `l1_cm`         | 14.0    | link1: motor 8 → motor 9                 |
| `l2_cm`         | 13.0    | link2: motor 9 → motor 10                |
| `l3_cm`         | 18.0    | link3: motor 10 → rubber fingertip       |
| `strings_z_cm`  | 13.5    | guitar string height above ground        |

## World frame

Origin on the base-yaw (motor 7) axis **at ground level**. +x from the base
toward the guitar at reference yaw, +y follows positive yaw sweep, +z up.
Units cm. In the baseline pose the fingertip is at **(13.0, 0.0, 6.0)** and
`above_strings_cm = −7.5`.

Model: planar 3-link chain (joints 8, 9, 10) swung about base yaw (7);
servo counts → degrees at 4096 counts/rev. Motor 11 (wrist_roll) spins the
tip about link3's axis, so it gets a degree readout but doesn't move the
tip point. Implementation: `kinematics.py` (self-test: `python kinematics.py`).

## What we're estimating / still to verify

- **Joint direction signs** (`signs` in `calibration_arm2.json`, all +1 for
  now): each assumes increasing counts = positive model angle. First time a
  recorded pose's XYZ looks mirrored on an axis, flip that joint's sign to
  −1. Verify by jogging one joint and watching XYZ.
- **Axis offsets** the model ignores: shoulder axis is assumed to intersect
  the yaw axis; link lengths are tape-measure accurate (~±0.5 cm). Good
  enough for relative reasoning; a few mapped keypoints with known real
  positions (string/fret intersections at `strings_z_cm`) can correct the
  residuals later — that's the "map a few points, infer the rest" plan.
- **Strings plane**: `above_strings_cm ≈ 0` should hold for every touch
  pose; a consistent bias there measures the model's z error directly.

## Extrapolation results (2026-09-19, full 18-cell grid)

`gridfit.py` fits bilinear models over (string, fret-position) — the fret
axis uses the real guitar law `u = 12·(1 − 2^(−f/12))` — for each XYZ
component and each motor's counts. On the recorded grid:

- fit RMS **1.94 cm**, leave-one-out RMS **2.59 cm**
- worst cells: s6f1 (5.2 cm), s6f2 (4.8 cm), s5f2 (4.4 cm) — the low-string
  fret-1/2 poses were likely recorded with a wrist tilt the planar FK
  doesn't model; re-record to improve the fit
- spot-check against stray hand-recorded anchors: keyframes named "2" and
  "3" sit 0.7 / 1.3 cm from the predicted low-E fret-2/3 cells; "5" is
  1.5–2 cm from a fret-5 prediction. Anchors "7" and "10" don't match any
  prediction (7–13 cm) — unexplained, possibly different wrist configs.

Verdict: XYZ is consistent enough for **relative spatial reasoning and
neighbor-cell extrapolation (±~2.5 cm)**; predicted counts are a starting
pose to refine, not a playable target. Recording one or two anchor poses
at frets 5/7 would pin down the up-neck extrapolation properly.

Tools: `estimate_position` (any string, fret 1-9) in `fret.py`'s TOOLS;
CLI `python fret.py --estimate S F`, `python gridfit.py --report`.

## Files & schema

- `calibration_arm2.json` — ref counts + signs + geometry (committed).
- `keyframes_arm2.json` — keypoints, cleared 2026-09-19 for re-recording
  (old 18-cell grid preserved in `keyframes_arm2.backup-20260919.json`).
  Entry schema (extra keys ignored by `fret.py` playback):

```json
{
  "name": "pose-r1-c1",
  "time": "…",
  "positions": {"7": 2058, "8": 2000, "9": 2195, "10": 2970, "11": 1099},
  "degrees":   {"7": 0.0, "8": 0.0, "9": 0.0, "10": 0.0, "11": 0.0},
  "xyz_cm":    {"x_cm": 13.0, "y_cm": 0.0, "z_cm": 6.0, "above_strings_cm": -7.5}
}
```

Recording tools: the tkinter GUI (`app.py`, enriches on every save/edit and
logs counts/degrees/xyz to stdout) or the webapp's `/calibrate` page — both
write the same file. Grid names `fret.py` plays: `pose-r{fret}-c{string}`
(string 1 = high E … 6 = low E, frets 1–3) plus one `rest`.
