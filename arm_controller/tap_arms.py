"""Symbolic key ownership, separate from hardware connection/trajectory authority.

Both roles are TAP arms, not fret+pick. The secondary owns rows 7–11 and is
available for planning ONLY when its own recorded keys exist AND its reviewed
lift-first paths compiled. No motor IDs, serial ports, poses, or execution are
inferred here; the drivers/registries provide those separately per arm.
"""
from __future__ import annotations

from typing import Literal

PRIMARY = "tap_primary"
SECONDARY = "tap_secondary"
ArmId = Literal["tap_primary", "tap_secondary"]
ROW_OWNERS = {PRIMARY: frozenset(range(1, 6)), SECONDARY: frozenset(range(7, 12))}


def owner_of_row(fret: int) -> ArmId:
    """The single arm that owns a fret row. Fret 6 has NO owner and is rejected."""
    for arm, rows in ROW_OWNERS.items():
        if fret in rows:
            return arm
    raise ValueError(f"fret row {fret} is not assigned to any arm (row 6 has no owner)")


def enabled_key_map(registry: dict) -> dict[str, set[tuple[int, int]]]:
    """assign()-ready ownership map from a registry snapshot.

    The secondary entry exists ONLY when the registry marks it available
    (recorded keys AND compiled reviewed paths); otherwise its notes are
    rejected rather than silently reassigned to the primary.
    """
    enabled = {PRIMARY: set(registry["keys"])}
    secondary = registry.get("secondary") or {}
    if secondary.get("available") and secondary.get("keys"):
        enabled[SECONDARY] = set(secondary["keys"])
    return enabled


def capabilities(primary_keys, *, primary_ready: bool, secondary_keys=(),
                 secondary_ready: bool = False, secondary_blocker: str | None = None) -> list[dict]:
    """Named arm capabilities for planners/UI. secondary_ready means the
    secondary's reviewed lift-first paths compiled; availability additionally
    requires recorded keys. unavailable_reason states exactly what is missing."""
    secondary_keys = set(secondary_keys)
    secondary_available = bool(secondary_keys) and bool(secondary_ready)
    if secondary_available:
        reason = None
    elif not secondary_keys:
        reason = secondary_blocker or ("no recorded contact keys for rows 7–11 "
                                       "(keyframes_arm1.json missing or empty)")
    else:
        reason = secondary_blocker or "paths not compiled"
    secondary = {"arm": SECONDARY, "role": "tap",
                 "available_for_planning": secondary_available,
                 "paths_reviewed": bool(secondary_ready), "live_hardware_state": "not_queried",
                 "rows": sorted(ROW_OWNERS[SECONDARY]),
                 "planned_strings": [1, 2, 3, 4, 5, 6],
                 "recorded_keys": [{"string": s, "fret": f} for s, f in sorted(secondary_keys)],
                 "string_order": "1=high E/rightmost, 6=low E/leftmost"}
    if reason is not None:
        secondary["unavailable_reason"] = reason
    return [
        {"arm": PRIMARY, "role": "tap", "available_for_planning": True,
         "paths_reviewed": primary_ready, "live_hardware_state": "not_queried",
         "rows": sorted(ROW_OWNERS[PRIMARY]),
         "recorded_keys": [{"string": s, "fret": f} for s, f in sorted(primary_keys)],
         "string_order": "1=high E/rightmost, 6=low E/leftmost"},
        secondary,
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
