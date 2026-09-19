"""Deduce & extrapolate fingertip XYZ (and servo counts) for ANY (string, fret).

The recorded grid gives 18 anchor cells with known joint counts and FK-derived
XYZ. The fretboard is (nearly) a ruled surface in (string, fret-position), so
each quantity is fit with a bilinear model over the grid:

    v(s, f) = a0 + a1*s + a2*u + a3*s*u,   u = 12 * (1 - 2^(-f/12))

u is the real guitar fret-position law (spacing shrinks by 2^(1/12) per
fret), scaled so u ≈ f near the nut. With anchors only at frets 1-3 both a
linear and log basis fit equally, but the log law extrapolates up the neck
with the correct shrinking spacing.

per XYZ component and per motor. That lets us:
  - predict the fingertip XYZ of unrecorded cells (e.g. fret 4+) — the
    "map a few points, infer the rest" idea from CALIBRATION.md
  - predict approximate servo counts for those cells (a starting pose a
    planner or operator can refine)
  - measure trustworthiness: leave-one-out (LOO) error — refit without each
    recorded cell and predict it — is honest extrapolation error, reported
    per cell so outliers (mis-recorded poses) stand out.

Pure Python, no numpy. CLI:
  python gridfit.py --report            # fit quality + per-cell LOO residuals
  python gridfit.py --predict 3 5      # string 3, fret 5 (extrapolated)
"""
import json
import math
import re
from pathlib import Path

KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm2.json"
MOTOR_IDS = [7, 8, 9, 10, 11]

_CELL = re.compile(r"pose[-_]?r(\d+)[-_]?c(\d+)$")


def load_cells(path=KEYFRAMES_PATH):
    """-> {(string, fret): {"counts": {sid: int}, "xyz": (x, y, z)}} for every
    recorded grid cell that carries an xyz_cm block."""
    cells = {}
    for k in json.loads(Path(path).read_text()):
        m = _CELL.fullmatch(k["name"].strip().lower())
        if not m or not k.get("xyz_cm"):
            continue
        f, s = int(m.group(1)), int(m.group(2))
        cells[(s, f)] = {
            "counts": {int(sid): int(v) for sid, v in k["positions"].items()},
            "xyz": (k["xyz_cm"]["x_cm"], k["xyz_cm"]["y_cm"], k["xyz_cm"]["z_cm"]),
        }
    return cells


def _solve4(A, b):
    """Gaussian elimination with partial pivoting for the 4x4 normal equations."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            g = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= g * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))) / M[r][r]
    return x


def _u(fret):
    """Fret number -> physical position coordinate (guitar fret law)."""
    return 12.0 * (1.0 - 2.0 ** (-fret / 12.0))


def _fit(points):
    """points: [((s, f), value)] -> bilinear coeffs [a0, a1, a2, a3]."""
    X = [[1.0, s, _u(f), s * _u(f)] for (s, f), _ in points]
    y = [v for _, v in points]
    XtX = [[sum(X[r][i] * X[r][j] for r in range(len(X))) for j in range(4)]
           for i in range(4)]
    Xty = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(4)]
    return _solve4(XtX, Xty)


def _eval(coef, s, f):
    return coef[0] + coef[1] * s + coef[2] * _u(f) + coef[3] * s * _u(f)


def fit_models(cells):
    """-> {"xyz": {axis: coeffs}, "counts": {sid: coeffs}} from recorded cells."""
    keys = sorted(cells)
    xyz = {ax: _fit([(k, cells[k]["xyz"][i]) for k in keys])
           for i, ax in enumerate("xyz")}
    counts = {sid: _fit([(k, cells[k]["counts"][sid]) for k in keys
                         if sid in cells[k]["counts"]])
              for sid in MOTOR_IDS}
    return {"xyz": xyz, "counts": counts}


def predict(models, string, fret):
    """-> {"xyz_cm": {...}, "counts": {sid: int}} for any (string, fret)."""
    x, y, z = (_eval(models["xyz"][ax], string, fret) for ax in "xyz")
    return {"xyz_cm": {"x_cm": round(x, 2), "y_cm": round(y, 2), "z_cm": round(z, 2)},
            "counts": {sid: int(round(_eval(c, string, fret)))
                       for sid, c in models["counts"].items()}}


def loo_residuals(cells):
    """Leave-one-out: refit without each cell, predict it. -> {(s,f): err_cm}."""
    out = {}
    for k in sorted(cells):
        rest = {c: v for c, v in cells.items() if c != k}
        models = fit_models(rest)
        p = predict(models, *k)["xyz_cm"]
        dx = p["x_cm"] - cells[k]["xyz"][0]
        dy = p["y_cm"] - cells[k]["xyz"][1]
        dz = p["z_cm"] - cells[k]["xyz"][2]
        out[k] = round(math.sqrt(dx * dx + dy * dy + dz * dz), 2)
    return out


def report(path=KEYFRAMES_PATH):
    cells = load_cells(path)
    if len(cells) < 6:
        return {"error": f"only {len(cells)} recorded cells — need at least 6 to fit"}
    models = fit_models(cells)
    loo = loo_residuals(cells)
    fit_err = []
    for k, v in cells.items():
        p = predict(models, *k)["xyz_cm"]
        fit_err.append(math.sqrt((p["x_cm"] - v["xyz"][0]) ** 2 +
                                 (p["y_cm"] - v["xyz"][1]) ** 2 +
                                 (p["z_cm"] - v["xyz"][2]) ** 2))
    rms = math.sqrt(sum(e * e for e in fit_err) / len(fit_err))
    loo_rms = math.sqrt(sum(e * e for e in loo.values()) / len(loo))
    return {"cells": len(cells), "fit_rms_cm": round(rms, 2),
            "loo_rms_cm": round(loo_rms, 2),
            "loo_worst": sorted(loo.items(), key=lambda kv: -kv[1])[:5],
            "loo_per_cell": {f"s{s}f{f}": e for (s, f), e in sorted(loo.items())}}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--predict", nargs=2, type=int, metavar=("STRING", "FRET"))
    a = ap.parse_args()

    if a.report:
        print(json.dumps(report(), indent=2))
    if a.predict:
        cells = load_cells()
        models = fit_models(cells)
        s, f = a.predict
        out = predict(models, s, f)
        out["recorded"] = (s, f) in cells
        if out["recorded"]:
            out["recorded_xyz"] = cells[(s, f)]["xyz"]
            out["recorded_counts"] = cells[(s, f)]["counts"]
        print(json.dumps(out, indent=2))
