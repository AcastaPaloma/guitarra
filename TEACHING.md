# Hand-guided action library

For the new laptop-accessible **Teach** tab, see [TEACHING_UI.md](TEACHING_UI.md).
It provides recording, save-only behavior, an automatically numbered take bank,
and click-to-replay. Its backend activation is a supervised one-time restart.

The installed runtime already records five joint coordinates and timestamps at
a target 30 Hz through its existing motor owner. No second serial process is
needed. The upstream [LeLamp control guide](https://github.com/humancomputerlab/LeLamp/blob/master/docs/5.%20LeLamp%20Control.md)
also documents recording and replay, but its standalone CLI must not be run
alongside this device's live runtime.

This is a teaching protocol, not a completed library. No hand-guided take has
been recorded in this continuation. Existing calibration stays unchanged.

## First takes

Teach small, comfortable movements first. Use the lamp's own left/right; record
that convention in each take. Start and finish discrete gestures at the same
agreed upright pose. For loops, demonstrate two cycles so a moving-to-moving
seam can be chosen from the middle instead of the hand placement at either end.

| Name | Demonstration | Intended use |
|---|---|---|
| `upright_neutral` | A comfortable upright stance, held briefly | Common reference pose |
| `look_left` / `look_right` | Turn attention each way, then return | Audience/partner cues |
| `nod_yes` | One gentle nod and return | Accent/acknowledgment |
| `head_tilt` | Curious side tilt and return | Expression |
| `body_sway` | Two flowing left/right cycles | Continuous dance loop |
| `body_bounce` | Two gentle rise/fall cycles | Beat accents |
| `body_roll` | Two coordinated body/head cycles | Groove variation |
| `dance_signature` | 8–12 seconds of a favorite whole-body groove | Main dance vocabulary |
| `ending_bow` | Controlled ending and return | Finish |

A dozen good takes can support many compositions. Every tempo/amplitude variant
still needs trajectory validation; multiplying amplitude is not automatically safe.

## First recording session

The live dashboard was checked on 2026-09-19. Open **Controls → Record
Animation** for hand-guided capture, or **Motion Animations** for existing clips.
The installed library already includes `nod`, `look_left`, `look_or_turn_left`,
`look_or_turn_right`, `dance`, `dance_2`, and `robot_dance`. The names below are
new recording names, not playable clips yet. None existed in the live library
at the time of the check. Check again before capture; the recorder can overwrite
an existing name. Use `t02`, `t03`, etc. for additional takes.

| Recording name | Demonstration | Role in a dance |
|---|---|---|
| `teach_upright_neutral_t01` | Hold a comfortable supported upright pose for 2–3 seconds | Reference for discrete gesture starts and finishes |
| `teach_nod_t01` | One gentle nod, then return | Beat or phrase accent |
| `teach_look_left_t01` | Look to the lamp's left, then return | Attention cue |
| `teach_look_right_t01` | Look to the lamp's right, then return | Attention cue |
| `teach_head_tilt_t01` | One small curious tilt, then return | Expression between phrases |
| `teach_sway_t01` | Two flowing left/right cycles | Repeating groove |
| `teach_bounce_t01` | Two gentle rise/fall cycles | Beat pulse |
| `teach_signature_t01` | 8–12 seconds of a comfortable coordinated groove | Main dance phrase |
| `teach_bow_t01` | Small controlled bow, then return | Ending |

Record at a comfortable pace and keep the original timing. Note the intended
beat count or metronome tempo if one is used; neither the file name nor the
dashboard's estimated duration establishes musical timing. For discrete
gestures, hold the reference pose briefly at each end. For loops, keep moving
through both cycles so a later edit can select a continuous seam.

The existing dashboard has two capture steps: **Record** releases motor torque;
**Start** begins sampling. Support the head and arms before pressing Record,
and confirm torque is actually released before guiding the lamp. The current
**Stop** saves the CSV and requests torque restoration; Stop during preparation
also requests torque restoration. Plan that powered handoff before beginning:
the UI currently has no save-only control, and powering the motors may resume
idle. Do not treat Stop as an inert save button. Use the supervised handoff
protocol below; the separate save-only runtime candidate is still undeployed.

Saved clips appear in **Motion Animations** after refresh. Selecting a clip
there commands playback. First review the recorded timestamps, joint ranges,
and entry/exit poses, then validate the trajectory and its entry before a
supervised replay. A recorded loop is not automatically safe to repeat, and
the dance composer does not yet import these takes or join them into a scene.

## Capture and replay handoff

1. Coordinate the sole operator, stop idle, inspect the camera, and support the
   head and arms before torque release. Never force powered joints.
2. Confirm release completed before hand guidance. The runtime recorder reads
   the actual five-joint pose while the operator guides it. Keep the raw take
   unchanged and use a unique name.
3. Save without automatically enabling torque or resuming idle. The runtime
   candidate adds `restore_torque: false` to `/api/recording/stop` and advertises
   `supports_save_without_torque_restore: true` in recording status. Verify this
   capability before starting; the old route silently ignores that option.
4. Keep supporting the mechanism after saving. Restoring powered holding is a
   separate supervised handoff; saving alone does not make it safe to let go.
5. Store robot/calibration identity, units, actual timestamps, label, direction
   convention, intended tempo, start/end poses, and whether a loop seam was
   verified. Do not infer timing from frame count alone.
6. Smooth/resample a copy, check ranges, derivative limits and collision geometry,
   and match position plus velocity/acceleration at joins. Compile the complete
   composition before uploading one SDK clip. Verify a short replay on camera.

The installed recorder's old Stop action enables torque and can resume idle.
The candidate fixes capture admission when torque release fails and adds the
explicit save-only option. These changes are tested in an isolated runtime
checkout, **not deployed**. They do not yet establish a physically verified
manual-to-powered handoff. No recording or torque release has been initiated.

Recorded motions solve authoring and direction mapping; they do not by themselves
solve loaded tracking error or make arbitrary clip joins continuous.
