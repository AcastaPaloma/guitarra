# Hand-guided lamp action library

> **Separate lamp workstream.** The recorded vocabulary and hand-guidance procedure below
> apply to that lamp, not the guitar's grippers or calibration. Current guitar requirements
> are [guitar/DESIGN.md](guitar/DESIGN.md); follow [AGENTS.md](AGENTS.md) for its tool-clamp
> and thermal rules. This documentation is preserved, not a guitar-training prerequisite.

The laptop-accessible [Teach tab](TEACHING_UI.md) provides start/end recording,
save-only behavior, automatic take numbering, a saved bank, and click-to-replay.
The separate [Dance tab](DANCING.md) composes beat-matched 30-second routines
from those recordings, with bounded faster/slower playback and five song presets.

## The saved vocabulary

Nine actual operator-taught takes are now archived in [assets/teaching](assets/teaching):
bounce, bow, look left, look right, two nods, and three sways. Raw CSV samples and
timestamps remain unchanged. The lamp's live animation directory remains the
source of truth for newly recorded takes; new takes are not automatically
committed to Git.

A saved upright neutral is a separate calibration-bound position, not a default
factory animation. Replays enter that pose first and return to it afterward.
Factory idle, startup movement, automatic talking animation and entry scanning
are disabled persistently on this lamp. Stop cancels remaining motion and retains
powered holding; it does not initiate a return or release the mechanism.

## Recording protocol

1. Coordinate a sole operator and clear the movement envelope. Support the
   head and arms before using **Position by hand** or **Start recording**.
2. Confirm torque release before hand guidance; never force powered joints.
   The existing runtime owner captures actual five-joint poses at a target
   30 Hz. Do not start a second serial/standalone recorder alongside it.
3. Demonstrate a small, comfortable gesture. Begin and end near the saved
   neutral. For a sway/bounce, two or more smooth cycles give the dance compiler
   a useful contiguous phrase. Use additional numbered takes for variations.
4. **End & save** writes the take without restoring power. Keep supporting the
   mechanism until a deliberate powered handoff. Failed saves retain frames
   in memory for retry; restarting before a successful save loses those frames.
5. Review the bank, clear the path, then choose **Replay selected** for the
   complete recording with neutral entry/exit. Speed or path violations reject
   playback; Dance may be able to use a valid slowed excerpt of a fast take.
6. Supervise actual tracking and clearance. Saved encoder coordinates are
   commanded targets, not a guarantee of identical physical motion under load.

Names such as head tilt, body roll, and a signature gesture remain useful ideas
for later recordings; they are not claimed as existing takes. No amplitude
multiplication, mirroring or improvised poses are added to the taught vocabulary.

See [TEACHING_UI.md](TEACHING_UI.md) for safe handoff, persistence, neutral setup,
restart instructions and tests; [DANCING.md](DANCING.md) for phrase selection,
retiming caps, audio/beat alignment and dance preflight results. Existing
calibration and hardware limits remain unchanged.
