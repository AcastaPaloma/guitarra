"""Symbolic key ownership, separate from hardware connection/trajectory authority.

Both roles are TAP arms, not fret+pick. Secondary rows 7–11 are the operator's
future layout; no motor IDs, serial port, poses, or execution are inferred for it.
"""
from __future__ import annotations

from typing import Literal

PRIMARY = "tap_primary"
SECONDARY = "tap_secondary"
ArmId = Literal["tap_primary", "tap_secondary"]
ROW_OWNERS = {PRIMARY: frozenset(range(1, 6)), SECONDARY: frozenset(range(7, 12))}


def capabilities(primary_keys, *, primary_ready: bool) -> list[dict]:
    return [
        {"arm": PRIMARY, "role": "tap", "available_for_planning": True,
         "paths_reviewed": primary_ready, "live_hardware_state": "not_queried",
         "rows": sorted(ROW_OWNERS[PRIMARY]),
         "recorded_keys": [{"string": s, "fret": f} for s, f in sorted(primary_keys)],
         "string_order": "1=high E/rightmost, 6=low E/leftmost"},
        {"arm": SECONDARY, "role": "tap", "available_for_planning": False,
         "paths_reviewed": False, "live_hardware_state": "not_queried",
         "rows": sorted(ROW_OWNERS[SECONDARY]),
         "planned_strings": [1, 2, 3, 4, 5, 6], "recorded_keys": [],
         "string_order": "1=high E/rightmost, 6=low E/leftmost",
         "unavailable_reason": "Awaiting dedicated key/hover calibration, path review and connection commissioning"},
    ]


def assign(notes, enabled_keys: dict[str, set[tuple[int, int]]]) -> list[dict]:
    """Validate all assignments before dispatch; one sequential owner per event.

    Supplying capabilities is not an implementation of a second-arm executor.
    Unknown/disabled ownership is an error, never reassigned to the other arm.
    Parallel contact/travel requires a separately qualified shared workspace.
    """
    out = []
    for index, note in enumerate(notes):
        arm, key = note.arm, (note.string, note.fret)
        if arm not in ROW_OWNERS or note.fret not in ROW_OWNERS[arm]:
            raise ValueError(f"Note {index + 1}: {arm} does not own fret row {note.fret}")
        if arm not in enabled_keys:
            raise ValueError(f"Note {index + 1}: {arm} is not available; do not assign its keys to another arm")
        if key not in enabled_keys[arm]:
            raise ValueError(f"Note {index + 1}: key {key} has no current recording for {arm}")
        out.append({"index": index, "arm": arm, "string": key[0], "fret": key[1],
                    "wait_for_event": index - 1 if index else None,
                    "shared_workspace": "guitar", "overlap_authorized": False})
    return out
