"""Fret map: joint poses for every (string, fret) from a few hand-recorded anchors. Pure functions.

Anchors are recorded in pairs at a few frets per string (default 1, 5, 9):
  above  tip ~HOVER_MM above the string, just behind the fret wire
  touch  tip lowered straight down until it just touches the string

Along a string, fret n sits at d(n) = 1 - 2**(-n/12) of the scale length from the nut, so frets
bunch up toward the body. Each joint is fitted as a polynomial in d through that string's anchors
(quadratic for 3 anchors), which follows the spacing instead of assuming frets are evenly spaced.
A string with no anchors is interpolated linearly between its recorded neighbours at each fret.
Pressing extrapolates along the recorded approach direction: press = touch + mm/HOVER_MM * (touch - above).
"""
import numpy as np

from .guards import JOINTS, Pose

HOVER_MM = 10.0
STRINGS = (6, 5, 4, 3, 2, 1)                 # 6 = low E ... 1 = high E
STANDARD_TUNING = {6: "E2", 5: "A2", 4: "D3", 3: "G3", 2: "B3", 1: "E4"}
ANCHOR_FRETS = (1, 5, 9)
MAX_FRET = 9
MAX_PRESS_MM = 8.0


def fret_pos(n: float) -> float:
    """Distance from the nut to fret n, as a fraction of the scale length."""
    return 1.0 - 2.0 ** (-n / 12.0)


def name(kind: str, string: int, fret: int) -> str:
    return f"{kind}_s{string}_f{fret}"


def anchor_key(string: int, fret: int) -> str:
    return f"s{string}f{fret}"


def _fit_string(anchors: dict[int, dict[str, Pose]], frets: range) -> dict[int, dict[str, Pose]]:
    """anchors: fret -> {"above": pose, "touch": pose} for one string."""
    known = sorted(anchors)
    d = np.array([fret_pos(f) for f in known])
    deg = min(2, len(known) - 1)
    out = {f: {"above": {}, "touch": {}} for f in frets}
    for kind in ("above", "touch"):
        for j in JOINTS:
            coeffs = np.polyfit(d, [anchors[f][kind][j] for f in known], deg)
            for f in frets:
                out[f][kind][j] = float(np.polyval(coeffs, fret_pos(f)))
    for f in known:  # recorded anchors are kept exactly
        out[f] = {k: dict(v) for k, v in anchors[f].items()}
    return out


def build(anchors: dict[str, dict[str, Pose]], max_fret: int = MAX_FRET) -> dict[str, Pose]:
    """anchors: {"s6f1": {"above": pose, "touch": pose}, ...} -> {"above_s6_f1": pose, "touch_s6_f1": pose, ...}"""
    by_string: dict[int, dict[int, dict]] = {}
    for key, pair in anchors.items():
        s, f = key[1:].split("f")
        by_string.setdefault(int(s), {})[int(f)] = pair
    by_string = {s: a for s, a in by_string.items() if len(a) >= 2}  # partial strings wait
    if not by_string:
        raise ValueError("no string has anchors at 2+ frets yet")
    frets = range(1, max_fret + 1)
    fitted = {s: _fit_string(a, frets) for s, a in by_string.items()}

    recorded = sorted(fitted)
    for s in STRINGS:  # fill strings without anchors from their recorded neighbours
        if s in fitted:
            continue
        lo = max((r for r in recorded if r < s), default=None)
        hi = min((r for r in recorded if r > s), default=None)
        if lo is None or hi is None:
            continue  # can't extrapolate past the outermost recorded string
        w = (s - lo) / (hi - lo)
        fitted[s] = {f: {k: {j: (1 - w) * fitted[lo][f][k][j] + w * fitted[hi][f][k][j] for j in JOINTS}
                         for k in ("above", "touch")} for f in frets}

    poses = {}
    for s, per_fret in fitted.items():
        for f, pair in per_fret.items():
            poses[name("above", s, f)] = {j: round(v, 2) for j, v in pair["above"].items()}
            poses[name("touch", s, f)] = {j: round(v, 2) for j, v in pair["touch"].items()}
    return poses


def press_pose(above: Pose, touch: Pose, press_mm: float) -> Pose:
    k = press_mm / HOVER_MM
    return {j: touch[j] + k * (touch[j] - above[j]) for j in JOINTS}


def available(poses: dict) -> dict[int, list[int]]:
    """string -> frets that have both an above and a touch pose."""
    out: dict[int, list[int]] = {}
    for key in poses:
        if key.startswith("touch_s"):
            s, f = key.removeprefix("touch_s").split("_f")
            if name("above", int(s), int(f)) in poses:
                out.setdefault(int(s), []).append(int(f))
    return {s: sorted(v) for s, v in sorted(out.items(), reverse=True)}


def anchor_warnings(anchors: dict[str, dict[str, Pose]], roll_tol_deg: float = 5.0) -> list[str]:
    """Human-recording mistakes that a clean build can't reveal.

    - the approach (above -> touch) should be a ~10 mm straight drop: flag drops much smaller or
      larger than the typical one (hover recorded too low / too high)
    - the fingertip must not twist while lowering: wrist_roll change within a pair
    - one wrist angle for every anchor: a rolled tip contacts the string off-centre
    """
    body = [j for j in JOINTS if j != "gripper"]
    size = {k: max(abs(p["touch"][j] - p["above"][j]) for j in body) for k, p in anchors.items()}
    if not size:
        return []
    typical = float(np.median(list(size.values())))
    roll_typical = float(np.median([p["touch"]["wrist_roll"] for p in anchors.values()]))
    out = []
    for k in sorted(size):
        p = anchors[k]
        roll = p["touch"]["wrist_roll"] - p["above"]["wrist_roll"]
        if abs(roll) > roll_tol_deg:
            out.append(f"{k}: wrist rolled {roll:+.1f} deg while lowering - keep the tip angle fixed")
        elif size[k] < 0.5 * typical:
            out.append(f"{k}: ABOVE is too close to the string ({size[k]:.1f} deg vs typical {typical:.1f}) - lift ~10 mm")
        elif size[k] > 2.5 * typical:
            out.append(f"{k}: ABOVE is too far from the string ({size[k]:.1f} deg vs typical {typical:.1f})")
        elif abs(p["touch"]["wrist_roll"] - roll_typical) > 2 * roll_tol_deg:
            out.append(f"{k}: fingertip turned to wrist_roll {p['touch']['wrist_roll']:.1f} vs {roll_typical:.1f} "
                       "on the other anchors - the tip lands on a different spot; keep one wrist angle")
    return out


# Spot names: string letter + fret, e.g. "A5". Low E is "e", high E is "E" (case matters only
# for those two); A D G B may be typed in either case.
STRING_LETTERS = {"e": 6, "A": 5, "D": 4, "G": 3, "B": 2, "E": 1}


def parse_spot(text: str) -> tuple[int, int]:
    """'A5' -> (5, 5), 'e1' -> (6, 1), 'E9' -> (1, 9). Raises ValueError with a readable message."""
    t = text.strip()
    if len(t) < 2 or not t[1:].isdigit():
        raise ValueError(f"'{text}': expected a string letter then a fret number, e.g. A5, e1, E9")
    letter = t[0] if t[0] in "eE" else t[0].upper()
    if letter not in STRING_LETTERS:
        raise ValueError(f"'{text}': string must be one of e A D G B E (e = low E, E = high E)")
    fret = int(t[1:])
    if not 1 <= fret <= MAX_FRET:
        raise ValueError(f"'{text}': fret must be 1-{MAX_FRET}")
    return STRING_LETTERS[letter], fret


def spot_name(string: int, fret: int) -> str:
    return {v: k for k, v in STRING_LETTERS.items()}[string] + str(fret)
