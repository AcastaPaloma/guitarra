#!/usr/bin/env python3
"""Read-only preflight of the five dances; never creates or connects motors."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime.resolve()
    sys.path.insert(0, str(root))
    from modules.robot_base.robots.factory import create_robot_runtime
    from modules.robot_base.control.runtime import MotionController
    from modules.robot_base.control.dance import SONGS, compile_dance, load_actions

    calibration = root / 'lelamp.json'
    platform = create_robot_runtime('lelamp_v1_pi5_feetech_r1', physical_hardware=True)
    controller = MotionController(
        motor=None, executor=None,
        safety=platform.create_safety_filter(calibration_path=calibration),
        platform=platform, idle_enabled=False,
        calibration_identity=hashlib.sha256(calibration.read_bytes()).hexdigest())
    info = controller.safe_motion_info()
    neutral = controller.teaching_neutral()
    if neutral is None:
        raise ValueError('This device needs its own saved, calibration-matched neutral')
    actions, rejected = load_actions(controller.recording_animations_dir(), info, controller._validate_self_collision)
    reports = []
    for song in SONGS:
        for variation in range(3):
            plan, report = compile_dance(song['id'], actions, neutral, info,
                variation=variation, collision_check=controller._validate_self_collision)
            assert abs(plan.duration_ms - 30000) < .001
            assert plan.waypoints[0].positions == plan.waypoints[-1].positions == neutral['positions']
            assert report['peak_speed'] <= report['speed_budget'] + 1e-6
            assert len({cue['name'] for cue in report['cues']}) >= 2
            reports.append({key: value for key, value in report.items() if key != 'preview'})
    print(json.dumps({
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'validation': 'offline geometry, calibration, velocity, timing, and neutral endpoints',
        'physical_rehearsal_performed': False,
        'hardware_connected_by_validator': False,
        'robot_id': info['robot_id'], 'calibration_id': info['calibration_id'],
        'units': info['units'], 'source_actions': [a['name'] for a in actions],
        'rejected': rejected, 'dances': reports,
    }, indent=2))


if __name__ == '__main__':
    main()
