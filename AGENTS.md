# Operator instructions: robot grippers

- **NEVER loosen/open the gripper hands as part of normal motion, return-to-rest,
  disconnect, script exit, or routine shutdown.** The grippers hold the fingertip
  extensions/picks and must remain clamped. This applies to both arms.
- Release body-joint torque only during normal disconnect. Do not use an
  all-motors torque-off operation for routine cleanup.
- `release()` means lift the fingertip off the guitar string, NOT open the hand.
- Opening or loosening a gripper requires an explicit operator request.
- Safety exception: an emergency, over-temperature condition, or electrical fault
  may require removing gripper power. Never defeat thermal protection to preserve
  the grip. Warn the operator to support the tool and explain what was released.
- A D1 hold in this session reported gripper temperature 75 C; the connected
  gripper (motor 12) was subsequently powered off. Do not assume sustained clamp
  operation is thermally verified, raise torque to cure slipping, or run an
  unattended full-key sweep before investigating that event.
- Motor 12 was re-tightened at a reduced `grip_torque=100` (previously 180):
  squeeze feedback confirmed and temperature stayed at 47 C over a 10-second
  check. It was left clamped, with body torque off. This is not a sustained
  thermal qualification. The plugin's existing default is still 180; do not
  inadvertently restore it via normal connection setup without reviewing the
  thermal issue and explicitly selecting the lower limit.
- Latest operator-requested adjustment: gripper torque limit increased 10% from
  100 to **110**, with the existing closing goal unchanged. After a 10-second
  check, load feedback was 110, temperature 46 C, and status 0. Gripper torque
  remains on; body torque remains off. Treat 110 as the current live setting,
  not as a calibrated grip-force measurement or sustained thermal qualification.

## Current guitar scope and document precedence

- Read `guitar/DESIGN.md` (requirements), `guitar/STATUS.md` (source/status gaps), then
  `guitar/SETUP.md` and `guitar/REHEARSAL_LOOP.md`. The operator rules above retain priority.
- Same two physical guitar arms; defined qualified tools; pretrained planner; optional
  pretrained audio evaluator; bounded revision of plans/context between attempts.
  **Fine-tuning is not required or on the current implementation path.**
- `guitar/FINETUNING.md` explains that distinction. Material under `guitar/research/` is
  deferred research, not authorization to build a training pipeline or launch GPU jobs.
- Root lamp/band architecture, teaching/dancing/commissioning files, and the old vision
  handoff prompt are separate reference work. Do not follow them as current guitar tasks,
  add performers, run their hardware commands, or inherit their commit/push instructions.
- The old simulator/transcriber and the other repository's Baseten prototype are reference
  material, not drop-in dependencies. Preserve their code and all unrelated/uncommitted work.
- Numerical scheduling, path validation, resource ownership, and stop/thermal behavior stay
  local. Models cannot change grip settings, calibration, safety limits, or executable control.
- No unattended rehearsal/data sweeps until the operator resolves the connection-default
  mismatch, grip reassertion/protection behavior, and sustained thermal limits.
- No physical RL, large step-response probes, or fake/simulator timing labels presented as
  real mechanics. An encoder-ready state is not proof of string contact or a clean note.
- Keep telemetry, acoustic heuristics, audio-model assessments, and human judgments distinct.
  A video-capable model does not automatically accept raw audio; test each actual endpoint.
- Baseten is the intended inference platform, but current CLI defaults and incomplete server
  glue must be documented honestly. Do not claim a deployment or evaluator exists because
  a YAML file or provider class exists. Astra/Claude requests are separate provider traffic.
- Device/media access, live model calls, deployments, and training require their applicable
  approval and budgets. Never print keys or include them in prompts/logs/screenshots.
- Documentation cleanup does not fix runtime behavior. Update status when code changes,
  run relevant offline checks, and do not commit/push unless requested.
