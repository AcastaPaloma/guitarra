"""Device-free lift-first route compiler for the current raw-count tap arm.

Contact poses are NOT a clearance map. Only operator-reviewed contact/hover
pairs and directed hover edges are executable. No IK, generated waypoints,
model coordinates, global-rest fallback, or hardware access lives here.
"""
from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass

BODY_IDS = (7, 8, 9, 10, 11)  # tool clamp 12 is never part of a path
TRAVEL_SPEED = 400
PRESS_SPEED = 250
TAP_SPEED = 1200
TAP_DWELL_S = 0.12
ACC = 30
SETTLE_TOL = 30
PRESS_TOL = 90
SETTLE_TIMEOUT = 4.0
CLEARANCE_DWELL_S = 0.09  # continuous encoder arrival, NOT proof of string clearance
PROFILE = "lift_first"
SCHEMA = "guitarra.lift-first.v1"


def motion_contract() -> str:
    """Changing staging or its settings invalidates previously reviewed paths."""
    return hashlib.sha256(json.dumps({
        "schema": SCHEMA, "body_ids": BODY_IDS,
        "driver": "raw-goals-per-joint;release-then-shoulder-lift;lift-arrival-before-transit;no-rest-interior-v3",
        "travel_speed": TRAVEL_SPEED, "press_speed": PRESS_SPEED, "tap_speed": TAP_SPEED,
        "tap_dwell_s": TAP_DWELL_S, "acc": ACC, "settle_tol": SETTLE_TOL,
        "press_tol": PRESS_TOL, "settle_timeout": SETTLE_TIMEOUT,
        "clearance_dwell_s": CLEARANCE_DWELL_S,
    }, sort_keys=True).encode()).hexdigest()


def calibration_digest(calibration: dict) -> str:
    # Qualification metadata cannot hash itself. Everything else, including any
    # new reference/geometry, invalidates the operator's previous review.
    return hashlib.sha256(json.dumps(
        {k: v for k, v in calibration.items() if k != "qualified_profiles"},
        sort_keys=True, allow_nan=False,
    ).encode()).hexdigest()


def contact_name(key: tuple[int, int]) -> str:
    string, fret = key
    return f"key-r{fret}-c{string}"


def hover_name(key: tuple[int, int]) -> str:
    string, fret = key
    return f"hover-r{fret}-c{string}"


class PathUnavailable(ValueError):
    """Missing/stale clearance evidence; never an invitation to invent a route."""


def _pose(pose: dict) -> tuple[int, ...]:
    if (set(pose) != set(BODY_IDS)
            or any(type(v) is not int or not 0 <= v <= 4095 for v in pose.values())):
        raise PathUnavailable("Paths require complete recorded body poses (IDs 7–11 only)")
    return tuple(pose[j] for j in BODY_IDS)


def _key(value) -> tuple[int, int]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) is not int for v in value)
            or not 1 <= value[0] <= 6 or not 1 <= value[1] <= 5):
        raise PathUnavailable("Qualified keys must be [string, fret] integer pairs")
    return tuple(value)


@dataclass(frozen=True)
class ClearancePaths:
    """Immutable named poses/edges, bound to an operator-reviewed local snapshot."""
    poses: tuple[tuple[str, tuple[int, ...]], ...]
    keys: frozenset[tuple[int, int]]
    edges: frozenset[tuple[str, str]]

    @classmethod
    def from_snapshot(cls, snapshot: dict, keyframes_sha256: str, calibration: dict):
        if snapshot.get("warns"):
            raise PathUnavailable("Resolve keypoint naming/duplicate warnings before reviewing paths")
        review = calibration.get("qualified_profiles", {}).get(PROFILE)
        if not isinstance(review, dict):
            raise PathUnavailable(
                "Lift-first playback needs recorded hover-r{fret}-c{string} poses and "
                "operator-reviewed lift/lower and hover-to-hover paths. No neutral fallback.")
        required = {"schema_version", "keyframes_sha256", "calibration_sha256", "motion_contract",
                    "qualified_at", "keys", "transit_edges"}
        if (set(review) != required or review["schema_version"] != SCHEMA
                or review["keyframes_sha256"] != keyframes_sha256
                or review["calibration_sha256"] != calibration_digest(calibration)
                or review["motion_contract"] != motion_contract()
                or not isinstance(review["qualified_at"], str) or not review["qualified_at"].strip()):
            raise PathUnavailable("Lift-first path review is missing/stale; inspect the current map and motion contract")
        if not isinstance(review["keys"], list) or not 1 <= len(review["keys"]) <= 30:
            raise PathUnavailable("Review a bounded subset of recorded contact/hover pairs first")
        keys = frozenset(_key(k) for k in review["keys"])
        if len(keys) != len(review["keys"]):
            raise PathUnavailable("Duplicate qualified key")
        poses = {"rest": _pose(snapshot["rest"])}
        for key in sorted(keys):
            if key not in snapshot["cells"] or key not in snapshot.get("hovers", {}):
                raise PathUnavailable(f"Missing recorded contact/hover pair for s{key[0]}f{key[1]}")
            contact, hover = _pose(snapshot["cells"][key]), _pose(snapshot["hovers"][key])
            # No yaw/roll retargeting during the lift or descent. Other joints
            # still require a reviewed swept path; endpoint math cannot certify it.
            if any(contact[BODY_IDS.index(j)] != hover[BODY_IDS.index(j)] for j in (7, 11)):
                raise PathUnavailable(f"{hover_name(key)} must retain its contact's yaw/roll (IDs 7 and 11)")
            if max(abs(a - b) for a, b in zip(contact, hover)) <= PRESS_TOL + SETTLE_TOL:
                raise PathUnavailable(f"{hover_name(key)} and contact have overlapping encoder-arrival regions")
            if hover == poses["rest"]:
                raise PathUnavailable("A key hover cannot be an alias of global rest")
            poses[contact_name(key)], poses[hover_name(key)] = contact, hover
        transit_nodes = {"rest"} | {hover_name(k) for k in keys}
        raw_edges = review["transit_edges"]
        if not isinstance(raw_edges, list) or not 1 <= len(raw_edges) <= 900:
            raise PathUnavailable("Review directed transit edges; endpoints alone do not qualify a crossing")
        edges = set()
        for edge in raw_edges:
            if (not isinstance(edge, list) or len(edge) != 2
                    or any(not isinstance(n, str) or n not in transit_nodes for n in edge)
                    or edge[0] == edge[1] or tuple(edge) in edges):
                raise PathUnavailable("Transit edges must be unique directed rest/hover pairs; no contact via-points")
            edges.add(tuple(edge))
        paths = cls(tuple(sorted(poses.items())), keys, frozenset(edges))
        # Each admitted key must have reviewed entry AND exit, including a
        # cooperative stop after any note. Missing between-note edges fail later
        # at whole-phrase admission, before opening the serial port.
        for key in keys:
            paths.route("rest", hover_name(key))
            paths.route(hover_name(key), "rest")
        return paths

    def pose(self, name: str) -> dict[int, int]:
        try:
            counts = dict(self.poses)[name]
        except KeyError:
            raise PathUnavailable(f"Unreviewed pose: {name}") from None
        return dict(zip(BODY_IDS, counts))

    def cost(self, source: str, target: str) -> int:
        poses = dict(self.poses)
        return sum(abs(a - b) for a, b in zip(poses[source], poses[target]))

    def route(self, source: str, target: str) -> tuple[str, ...]:
        """Shortest reviewed count-travel route, excluding rest between notes.

        Counts are a travel proxy, NOT mm, elapsed time, energy, or clearance.
        Rest is permitted ONLY as the requested entry/exit endpoint.
        """
        transit = {"rest"} | {hover_name(k) for k in self.keys}
        if source not in transit or target not in transit:
            raise PathUnavailable("Transit must start/end at a reviewed hover or the entry/exit rest")
        if source == target:
            return ()
        queue = [(0, 0, (source,))]
        visited = set()
        while queue:
            cost, hops, path = heapq.heappop(queue)
            node = path[-1]
            if node in visited:
                continue
            visited.add(node)
            if node == target:
                return path[1:]
            for a, b in sorted(self.edges):
                if a == node and b not in visited and (b != "rest" or target == "rest"):
                    heapq.heappush(queue, (cost + self.cost(a, b), hops + 1, path + (b,)))
        raise PathUnavailable(f"No reviewed hover route {source} → {target}; will not detour through neutral")

    def compile(self, keys) -> dict:
        """Admit the COMPLETE phrase and every possible post-note exit, no motion."""
        keys = tuple(_key(k) for k in keys)
        if not keys or len(keys) > 64:
            raise PathUnavailable("Compile 1–64 keys at a time")
        if any(key not in self.keys for key in keys):
            missing = sorted(set(keys) - self.keys)
            raise PathUnavailable(f"Unreviewed contact/hover pairs in this phrase: {missing}")
        location, travel, notes = "rest", 0, []
        for index, key in enumerate(keys):
            hover, contact = hover_name(key), contact_name(key)
            stages = []
            for node in self.route(location, hover):
                travel += self.cost(location, node)
                stages.append({"stage": "travel", "pose": node})
                location = node
            stages += [{"stage": "tap", "pose": contact}, {"stage": "lift_clear", "pose": hover}]
            travel += 2 * self.cost(hover, contact)
            notes.append({"index": index, "string": key[0], "fret": key[1], "stages": stages})
            # A repeated tap still lifts/re-attacks: this arm has no separate pick.
            self.route(hover, "rest")
        exit_route = self.route(location, "rest")
        for node in exit_route:
            travel += self.cost(location, node)
            location = node
        return {"path_profile": PROFILE, "notes": notes, "exit_route": list(exit_route),
                "neutral_visits_between_notes": 0, "joint_travel_proxy_counts": travel,
                "objective": "reviewed lift first, then minimum count travel, then lower/tap",
                "physical_clearance_verified_by_software": False,
                "cost_is_not_time_or_acoustic_quality": True}

    def model_context(self) -> dict:
        costs = []
        for a in sorted(self.keys):
            for b in sorted(self.keys):
                try:
                    route = self.route(hover_name(a), hover_name(b))
                except PathUnavailable:
                    continue  # unavailable is NOT permission for an invented edge
                nodes = (hover_name(a),) + route
                costs.append({"from": list(a), "to": list(b),
                              "travel_counts": sum(self.cost(x, y) for x, y in zip(nodes, nodes[1:]))})
        return {"profile": PROFILE, "qualified_keys": sorted(self.keys),
                "hover_transition_costs": costs, "neutral_between_notes": False,
                "cost_metric": "raw joint-count travel proxy; not elapsed time or clearance",
                "authority": "choose notes; local compiler alone selects reviewed paths"}
