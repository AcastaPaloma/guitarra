"""Synthetic raw-count clearance fixtures. NEVER physical qualification data."""
import hashlib
import json

import fret
from tap_paths import (PROFILE, SCHEMA, ClearancePaths, calibration_digest, hover_name,
                       motion_contract)


def fixture_data(keys=((1, 1), (1, 2)), *, edges=None):
    rest = {j: 1000 for j in fret.MOTOR_IDS}
    entries = [{"name": "rest", "positions": {str(j): v for j, v in rest.items()}}]
    for s, f in keys:
        contact = {7: 1400 + 40 * s + 20 * f, 8: 1800 + 30 * f, 9: 2000, 10: 2300, 11: 1200}
        hover = {**contact, 8: contact[8] - 200}
        entries += [{"name": f"r{f}_{s}", "positions": {str(j): v for j, v in contact.items()}},
                    {"name": hover_name((s, f)), "positions": {str(j): v for j, v in hover.items()}}]
    raw = json.dumps(entries).encode()
    nodes = ["rest"] + [hover_name(k) for k in keys]
    edges = edges if edges is not None else [[a, b] for a in nodes for b in nodes if a != b]
    calibration = {"fixture": "synthetic, NOT hardware review"}
    calibration["qualified_profiles"] = {PROFILE: {
        "schema_version": SCHEMA, "keyframes_sha256": hashlib.sha256(raw).hexdigest(),
        "calibration_sha256": calibration_digest(calibration), "motion_contract": motion_contract(),
        "qualified_at": "offline-test-only", "keys": [list(k) for k in keys], "transit_edges": edges,
    }}
    return fret.load_map(entries=entries), raw, calibration


def path_registry(keys=((1, 1), (1, 2)), *, edges=None):
    snapshot, raw, cal = fixture_data(keys, edges=edges)
    paths = ClearancePaths.from_snapshot(snapshot, hashlib.sha256(raw).hexdigest(), cal)
    return {"keys": set(keys), "grid": (snapshot["cells"], snapshot["rest"], snapshot["warns"]),
            "row_rests": {}, "hovers": snapshot["hovers"], "paths": paths,
            "path_profiles": (PROFILE,), "path_blocker": None,
            "warnings": [], "fingerprint": "synthetic-clearance-fixture"}


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Bus:
    def __init__(self, pose):
        self.q = dict(pose)
        self.goals, self.torques = [], []
        self.block = False
        self.closed = False

    def ping(self, _sid):
        return True

    def read_pos(self, sid):
        return self.q[sid]

    def goto(self, sid, value, **kwargs):
        self.goals.append((sid, value))
        if not self.block:
            self.q[sid] = value

    def set_torque(self, sid, on):
        self.torques.append((sid, on))

    def close(self):
        self.closed = True


def fake_arm(monkeypatch, *, registry=None):
    registry = registry or path_registry()
    clock, bus = Clock(), Bus(registry["grid"][1])
    monkeypatch.setattr(fret, "time", clock)
    monkeypatch.setattr(fret, "FeetechBus", lambda *args, **kwargs: bus)
    arm = fret.FretArm(grid=registry["grid"], paths=registry["paths"])
    bus.goals.clear()
    moves, original = [], arm._move

    def record(pose, *args, **kwargs):
        moves.append(dict(pose))
        return original(pose, *args, **kwargs)

    arm._move = record
    return arm, bus, moves, clock
