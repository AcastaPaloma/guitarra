# Arm Controller

Minimal GUI to drive the fretting arm and capture keyframes. Talks raw Feetech
STS protocol over the Waveshare bus servo adapter — no lerobot install needed.

## Run

```bash
cd arm_controller
uv run --with pyserial python app.py
```

(or `pip install pyserial && python app.py`)

## Hardware assumptions

- Port `/dev/cu.usbmodem5B8E1128501` at 1,000,000 baud (edit `PORT`/`BAUD` in `app.py`)
- Motor IDs bottom → top: **5, 6, 1, 2, 7, 3** (STS3215, verified responding 2026-09-19)

## Usage

- Torque starts **OFF**: pose the arm by hand, then press **★ Keyframe current pose**
  to save the position of all six joints to `keyframes.json`.
- **Torque ON** enables the sliders for direct joint control and **Go to** for
  replaying a saved keyframe (moves at a conservative speed).
- Closing the window disables torque — support the arm so it doesn't fall.
