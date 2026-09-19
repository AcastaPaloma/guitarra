"""LeRobot plugin for the astra-guitar SO-101 arms.

LeRobot auto-imports installed packages named `lerobot_robot_*`, which registers the
`astra_so101` robot type for every `lerobot-*` CLI (calibrate, teleoperate, record, ...).
"""

from .config_astra_so101 import AstraSO101Config
from .astra_so101 import AstraSO101

__all__ = ["AstraSO101", "AstraSO101Config"]
