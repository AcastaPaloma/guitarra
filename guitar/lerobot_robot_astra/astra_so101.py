import logging
import time

from lerobot.lerobot_types import RobotAction
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode
from lerobot.robots.so_follower import SOFollower

from .config_astra_so101 import AstraSO101Config

logger = logging.getLogger(__name__)

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
BODY = JOINTS[:-1]
GRIPPER = "gripper"


class AstraSO101(SOFollower):
    """Stock SOFollower behaviour (calibrate, configure, observe, act) on a shifted motor-ID map.

    With `clamp_gripper=True` the gripper is a tool holder, not a joint: it closes on the tool
    (fingertip extension or pick) at connect, keeps squeezing, ignores gripper actions, stays
    clamped through calibration and disconnect, and only the five body joints ever go limp.
    """

    config_class = AstraSO101Config
    name = "astra_so101"

    def __init__(self, config: AstraSO101Config):
        super().__init__(config)
        body = MotorNormMode.DEGREES if config.use_degrees else MotorNormMode.RANGE_M100_100
        self.bus = FeetechMotorsBus(
            port=config.port,
            motors={
                joint: Motor(
                    i + 1 + config.motor_id_offset,
                    "sts3215",
                    MotorNormMode.RANGE_0_100 if joint == GRIPPER else body,
                )
                for i, joint in enumerate(JOINTS)
            },
            calibration=self.calibration,
        )

    # -- gripper as a clamp ----------------------------------------------------------------
    def clamp_gripper(self) -> dict:
        """Close onto the tool and keep squeezing, without touching the other joints' torque.

        The goal is set `grip_squeeze_ticks` past the calibrated closed end, so the jaws stall
        on the tool and hold it at `grip_torque` instead of just resting against it. Never
        drops gripper torque, so a tool that is already held is never released.
        """
        b, g, cfg = self.bus, GRIPPER, self.config
        closed = self.calibration[g].range_min if g in self.calibration else b.read("Min_Position_Limit", g, normalize=False)
        target = max(0, closed - cfg.grip_squeeze_ticks)
        # EEPROM first, and re-lock BEFORE commanding: a Lock write right after Goal_Position
        # cancels the move (measured on the fret arm: torque on, zero load, jaws never closed).
        b.write("Lock", g, 0)                      # torque state untouched
        b.write("Min_Position_Limit", g, target, normalize=False)
        b.write("Lock", g, 1)
        b.write("Acceleration", g, 20)
        b.write("Torque_Limit", g, cfg.grip_torque)
        if not b.read("Torque_Enable", g):
            b.write("Goal_Position", g, b.read("Present_Position", g, normalize=False), normalize=False)
            b.write("Torque_Enable", g, 1)
            time.sleep(0.1)
        state = {}
        for _ in range(2):                         # one retry if the command didn't take
            b.write("Goal_Position", g, target, normalize=False)
            time.sleep(0.8)
            pos = b.read("Present_Position", g, normalize=False)
            load = b.read("Present_Load", g, normalize=False) & 0x3FF   # bit 10 is direction
            # squeezing = stalled pushing near the torque limit. Can't tell tool vs jaw-on-jaw:
            # the gripper's true fully-closed point was never calibrated (tool was in the jaws).
            holding = load >= 0.6 * cfg.grip_torque and pos > target + 25
            state = {"target": target, "stalled_at": pos, "load": load, "squeezing": holding}
            if holding:
                break
        (logger.info if state["squeezing"] else logger.warning)(f"{self} gripper clamp: {state}")
        return state

    def reassert_grip(self) -> None:
        """Re-arm the clamp in case overload protection eased off (cheap: two writes)."""
        target = self.bus.read("Min_Position_Limit", GRIPPER, normalize=False)
        self.bus.write("Torque_Enable", GRIPPER, 1)
        self.bus.write("Goal_Position", GRIPPER, target, normalize=False)

    # -- SOFollower overrides ----------------------------------------------------------------
    @property
    def is_calibrated(self) -> bool:
        if not self.config.clamp_gripper:
            return super().is_calibrated
        # the clamp lowers the gripper's Min_Position_Limit on purpose; don't call that a mismatch
        on_motor = self.bus.read_calibration()
        for m, cal in self.calibration.items():
            mc = on_motor[m]
            if (mc.homing_offset, mc.range_max) != (cal.homing_offset, cal.range_max):
                return False
            if m != GRIPPER and mc.range_min != cal.range_min:
                return False
        return True

    def connect(self, calibrate: bool = True) -> None:
        super().connect(calibrate)
        if self.config.clamp_gripper:
            self.clamp_gripper()

    def configure(self) -> None:
        if not self.config.clamp_gripper:
            return super().configure()
        # same as SOFollower.configure, but the gripper's torque is never dropped
        with self.bus.torque_disabled(list(BODY)):
            self.bus.configure_motors()
            for motor in BODY:
                self.bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
                self.bus.write("P_Coefficient", motor, self.config.position_p_coefficient)
                self.bus.write("I_Coefficient", motor, self.config.position_i_coefficient)
                self.bus.write("D_Coefficient", motor, self.config.position_d_coefficient)

    def calibrate(self) -> None:
        if not (self.config.clamp_gripper and GRIPPER in self.calibration):
            return super().calibrate()  # first calibration must record the gripper range once
        if self.calibration and input(
            f"Press ENTER to use provided calibration file for {self.id}, or type 'c' to recalibrate: "
        ).strip().lower() != "c":
            self.bus.write_calibration(self.calibration)
            return
        gripper_cal = self.calibration[GRIPPER]
        self.clamp_gripper()
        self.bus.disable_torque(list(BODY))
        for motor in BODY:
            self.bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
        input(f"Gripper stays clamped. Move the other joints of {self} to the MIDDLE of their range, then ENTER...")
        homing = self.bus.set_half_turn_homings(list(BODY))
        print("Move every joint except wrist_roll through its full range. ENTER to stop...")
        mins, maxes = self.bus.record_ranges_of_motion([m for m in BODY if m != "wrist_roll"])
        mins["wrist_roll"], maxes["wrist_roll"] = 0, 4095
        self.calibration = {
            m: MotorCalibration(id=self.bus.motors[m].id, drive_mode=0, homing_offset=homing[m],
                                range_min=mins[m], range_max=maxes[m])
            for m in BODY
        }
        self.calibration[GRIPPER] = gripper_cal
        self.bus.write_calibration({m: self.calibration[m] for m in BODY}, cache=False)
        self.bus.calibration = dict(self.calibration)  # set_half_turn_homings wiped the cache
        self._save_calibration()
        print("Calibration saved to", self.calibration_fpath)

    def send_action(self, action: RobotAction) -> RobotAction:
        if self.config.clamp_gripper:
            action = {k: v for k, v in action.items() if k != f"{GRIPPER}.pos"}
        return super().send_action(action)

    def disconnect(self) -> None:
        if not self.config.clamp_gripper:
            return super().disconnect()
        if self.config.disable_torque_on_disconnect:
            for m in BODY:  # one faulted servo (e.g. overload) must not stop the others releasing
                try:
                    self.bus.disable_torque(m, num_retry=3)
                except RuntimeError as e:
                    logger.warning(f"{self}: could not release {m}: {e}")
        self.bus.disconnect(disable_torque=False)  # gripper keeps holding the tool
        for cam in self.cameras.values():
            cam.disconnect()
        logger.info(f"{self} disconnected (gripper still clamped).")
