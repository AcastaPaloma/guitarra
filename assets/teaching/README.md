# Operator-authored movement vocabulary

These nine unmodified CSV takes were recorded by hand on this lamp on
2026-09-19. They contain joint positions and timestamps, not music. The stored
`reference_neutral.json` documents the capture device/coordinate identity. It
is provenance, **not a neutral pose to install automatically on another lamp**.
Set neutral on the actual device, and retain its calibration and safety limits.

Dance composition extracts a contiguous 3.2-second phrase from each long take
(up to 4.5 seconds for bows), choosing an active window. The preview discloses
the source window and source hash. It linearly retimes a copy, samples the result
at the controller rate, and validates the complete neutral-entry/action/return
path. No source CSV is overwritten and no mirrored or amplified pose is added.

Some takes exceed the velocity ceiling at their original timing. Dance playback
computes a rate cap from the source's worst joint velocity and a 65% budget of
the runtime's calibrated limit; this can require slowing below 1×. A source
file's existence does not establish safe playback at 1× or physical clearance.
