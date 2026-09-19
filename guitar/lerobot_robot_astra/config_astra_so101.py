from dataclasses import dataclass

from lerobot.robots.config import RobotConfig
from lerobot.robots.so_follower import SOFollowerConfig


@RobotConfig.register_subclass("astra_so101")
@dataclass
class AstraSO101Config(RobotConfig, SOFollowerConfig):
    """SO-101 follower whose servos may not sit at the stock IDs 1-6.

    Fret arm (IDs 7-12 on this rig) -> motor_id_offset=6. A stock 1-6 arm -> motor_id_offset=0.
    """

    motor_id_offset: int = 0

    # Gripper holds a tool (fingertip extension / pick) permanently: clamp at connect, never
    # release on calibrate/disconnect, ignore gripper actions.
    clamp_gripper: bool = False
    grip_torque: int = 180          # of 1000. Must stay under the servo overload trigger (~20-25%),
                                    # or protection kicks in after ~2 s and the grip fades or drops
    grip_squeeze_ticks: int = 200   # goal this far past the calibrated closed end, so it squeezes
