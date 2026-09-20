"""Local, uncertainty-aware acoustic estimates. No devices, models or motion.

Detect energy *rises* once across the capture, assign them one-to-one to command
windows, and estimate independent monophonic pitch across several frames. This
is not a validated guitar classifier: motor knocks, ringing/overlap and weak
fundamentals can be ambiguous. Encoder readiness is not an intended beat or
contact time. Absolute delay and rhythm-error fields remain unavailable.
"""
from __future__ import annotations

import hashlib
import io
import math
import wave

import numpy as np
from scipy.signal import resample_poly

VERSION = "guitarra.local-acoustics.v2"
FRAME_S = 0.010
ONSET_PRE_S, ONSET_POST_S = 0.30, 0.55
ONSET_OVER_FLOOR_DB, ONSET_RISE_DB = 10.0, 6.0
MIN_LEVEL_DBFS = -65.0
MIN_ATTACK_GAP_S = 0.08
PITCH_WINDOW_S = 0.25
PITCH_MIN_HZ, PITCH_MAX_HZ = 70.0, 1000.0
PITCH_RATE = 8000
TUNING_TOLERANCE_CENTS = 35.0  # separate from discrete note identity
MAX_CANDIDATES = 512
_SEMIS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _hz(name):
    midi = 12 * (int(name[-1]) + 1) + _SEMIS.index(name[:-1])
    return 440.0 * 2 ** ((midi - 69) / 12)


def _name(hz):
    midi = round(69 + 12 * math.log2(hz / 440.0))
    return f"{_SEMIS[midi % 12]}{midi // 12 - 1}"


def _db(value):
    return 20 * math.log10(max(float(value), 1e-9))


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def _tap_time_s(event):
    """Approximate tap ENCODER-ready time, never expected acoustic onset."""
    base = event.get("server_elapsed_s")
    result = event.get("result")
    stages = result.get("stages") if isinstance(result, dict) else None
    if not _finite(base) or not isinstance(stages, list) or not stages:
        return None
    if not all(isinstance(s, dict) and _finite(s.get("encoder_ready_s")) for s in stages):
        return None
    times = [s["encoder_ready_s"] for s in stages]
    taps = [s for s in stages if s.get("stage") == "tap"]
    if len(taps) != 1 or times != sorted(times):
        return None
    reference = base - times[-1] + taps[0]["encoder_ready_s"]
    return reference if reference >= 0 else None


def _pitch_frame(frame):
    """Normalized periodicity peaks with sub-sample interpolation and octave guard."""
    x = frame - frame.mean()
    energy = np.r_[0.0, np.cumsum(x * x)]
    if energy[-1] <= 1e-12:
        return None
    lo, hi = int(PITCH_RATE / PITCH_MAX_HZ), math.ceil(PITCH_RATE / PITCH_MIN_HZ)
    corr = np.correlate(x, x, mode="full")[len(x) - 1:len(x) + hi + 1]
    lag = np.arange(len(corr))
    denom = np.sqrt(np.maximum(energy[len(x) - lag] * (energy[-1] - energy[lag]), 1e-20))
    corr = corr / denom
    peaks = []
    for i in range(lo, hi + 1):
        a, b, c = corr[i - 1:i + 2]
        if b < 0.85 or not (b > a and b >= c):
            continue
        shift = float(np.clip(0.5 * (a - c) / (a - 2 * b + c), -0.5, 0.5)) if a - 2 * b + c else 0
        strength = float(np.clip(b - 0.25 * (a - c) * shift, 0, 1))
        peaks.append((i + shift, strength))
    if not peaks:
        return None
    period, strength = peaks[0]
    # A materially stronger double-period candidate means the first peak may
    # be a strong second harmonic. Do NOT snap the estimate to the target note.
    ambiguous = any(abs(other / period - 2) < 0.08 and score > strength + 0.002
                    for other, score in peaks[1:])
    return PITCH_RATE / period, strength, ambiguous


def _pitch(chunk):
    frame_n, step = int(0.08 * PITCH_RATE), int(0.02 * PITCH_RATE)
    out = {"detected_pitch": None, "detected_hz": None, "pitch_confidence": "unknown",
           "periodicity": None, "voiced_frames": 0, "pitch_reason": "insufficient_stable_periodicity"}
    if len(chunk) < frame_n + step:
        return {**out, "pitch_reason": "too_short_for_multiframe_pitch"}
    frames = [chunk[i:i + frame_n] for i in range(0, len(chunk) - frame_n + 1, step)]
    levels = [float(np.sqrt(np.mean(x * x))) for x in frames]
    results = [_pitch_frame(x) for x, level in zip(frames, levels)
               if level >= max(max(levels) * 0.25, 10 ** (MIN_LEVEL_DBFS / 20))]
    voiced = [p for p in results if p is not None]
    out["voiced_frames"] = len(voiced)
    if not voiced:
        return out
    out["periodicity"] = round(float(np.median([p[1] for p in voiced])), 4)
    if any(p[2] for p in voiced):
        return {**out, "pitch_reason": "octave_ambiguous"}
    frequencies = np.array([p[0] for p in voiced])
    center = float(np.median(frequencies))
    spread = float(np.max(np.abs(1200 * np.log2(frequencies / center))))
    if len(voiced) < 2 or len(voiced) < len(results) / 2 or spread > 30:
        return out
    semitones = 69 + 12 * math.log2(center / 440)
    if abs(abs(semitones - round(semitones)) - 0.5) < 0.05:
        return {**out, "pitch_reason": "near_semitone_boundary"}
    return {**out, "detected_pitch": _name(center), "detected_hz": round(center, 2),
            "pitch_confidence": "supported_estimate", "pitch_reason": None}


def _assign(centers, candidates):
    """Order-preserving sequence alignment. Each event may be assigned at most once."""
    n, m = len(centers), len(candidates)
    costs = np.full((n + 1, m + 1), np.inf)
    steps = np.zeros((n + 1, m + 1), dtype=np.int8)
    costs[:, 0], costs[0, :] = np.arange(n + 1), np.arange(m + 1) * 0.2
    for i, center in enumerate(centers, 1):
        for j, candidate in enumerate(candidates, 1):
            delta = candidate["onset_s"] - center
            match = costs[i - 1, j - 1] + abs(delta) / ONSET_POST_S if -ONSET_PRE_S <= delta <= ONSET_POST_S else np.inf
            choices = [costs[i - 1, j] + 1, costs[i, j - 1] + 0.2, match]
            steps[i, j] = int(np.argmin(choices))
            costs[i, j] = min(choices)
    pairs = {}
    i, j = n, m
    while i and j:
        step = steps[i, j]
        if step == 2:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif step == 0:
            i -= 1
        else:
            j -= 1
    return pairs


def measure_take(wav_bytes: bytes, telemetry: list[dict], dispatch_frame: int,
                 expected_pitches: list[str]) -> dict:
    """Bounded PCM16 input -> JSON-safe estimates; missing evidence stays unknown."""
    if len(wav_bytes) > 32 * 1024 * 1024:
        raise ValueError("WAV exceeds measurement limit")
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        rate, count, channels = reader.getframerate(), reader.getnframes(), reader.getnchannels()
        if (reader.getsampwidth() != 2 or channels not in (1, 2) or reader.getcomptype() != "NONE"
                or rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000}
                or not 0 < count <= 160 * rate):
            raise ValueError("Measurement requires bounded, nonempty PCM16 WAV")
        pcm = reader.readframes(count)
        if len(pcm) != count * channels * 2:
            raise ValueError("Truncated WAV")
    if type(dispatch_frame) is not int or not 0 <= dispatch_frame < count:
        raise ValueError("Dispatch frame outside capture")
    if len(expected_pitches) > 64:
        raise ValueError("Too many expected notes")
    targets = [_hz(name) for name in expected_pitches]
    raw = np.frombuffer(pcm, dtype="<i2").reshape(-1, channels)
    clipped = np.any(np.abs(raw.astype(np.int32)) >= 32767, axis=1)
    samples = raw.astype(np.float64).mean(axis=1) / 32768
    hop = max(1, round(rate * FRAME_S))
    usable = len(samples) // hop * hop
    rms = (np.sqrt(np.mean(samples[:usable].reshape(-1, hop) ** 2, axis=1))
           if usable else np.array([], dtype=float))
    floor = float(np.percentile(rms, 20)) if len(rms) else 0.0
    floor_db = _db(floor)
    levels = 20 * np.log10(np.maximum(rms, 1e-9))
    peak = float(np.max(np.abs(samples)))
    signal_usable = len(rms) >= 2 and _db(peak) >= MIN_LEVEL_DBFS
    candidates = []
    for i in range(1, len(rms)):
        prior = float(np.median(levels[max(0, i - 3):i]))
        onset = i * hop / rate  # actual sample clock, not i * nominal FRAME_S
        if (levels[i] >= max(MIN_LEVEL_DBFS, floor_db + ONSET_OVER_FLOOR_DB)
                and levels[i] - prior >= ONSET_RISE_DB
                and (not candidates or onset - candidates[-1]["onset_s"] >= MIN_ATTACK_GAP_S)):
            candidates.append({"onset_s": onset, "level_over_floor_db": round(float(levels[i] - floor_db), 1)})
    excessive_events = len(candidates) > MAX_CANDIDATES
    if excessive_events:
        candidates = []  # reject ambiguous evidence rather than quietly truncating it
        signal_usable = False
    divisor = math.gcd(rate, PITCH_RATE)
    pitch_samples = resample_poly(samples, PITCH_RATE // divisor, rate // divisor) if rate != PITCH_RATE else samples
    for j, candidate in enumerate(candidates):
        start = candidate["onset_s"] + 0.015  # skip the initial percussive transient
        end = min(candidate["onset_s"] + PITCH_WINDOW_S,
                  candidates[j + 1]["onset_s"] if j + 1 < len(candidates) else count / rate)
        estimate = _pitch(pitch_samples[round(start * PITCH_RATE):round(end * PITCH_RATE)])
        if np.any(clipped[int(start * rate):int(end * rate)]):
            estimate.update(detected_pitch=None, detected_hz=None, pitch_confidence="unknown", pitch_reason="clipped_window")
        candidate.update(estimate)
        candidate["onset_s"] = round(candidate["onset_s"], 6)

    events = {}
    for event in telemetry:
        if isinstance(event, dict) and event.get("event") == "note_end" and type(event.get("index")) is int:
            events.setdefault(event["index"], []).append(event)
    per_note, valid_indices, centers = [], [], []
    last_center = -1.0
    for index, (name, hz) in enumerate(zip(expected_pitches, targets)):
        rows = events.get(index, [])
        reference = _tap_time_s(rows[0]) if len(rows) == 1 else None
        center = dispatch_frame / rate + reference if reference is not None else None
        valid = signal_usable and center is not None and last_center < center < count / rate
        row = {"index": index, "expected_pitch": name, "expected_hz": round(hz, 2),
               "heard": None, "onset_status": "unknown", "onset_s": None,
               "onset_offset_ms": None, "timing_error_ms": None,
               "command_to_sound_delay_ms": None, "clarity_db": None,
               "detected_pitch": None, "detected_hz": None, "pitch_match": None,
               "in_tune": None, "cents_off": None, "pitch_confidence": "unknown",
               "reason": "missing_invalid_alignment_or_unusable_signal"}
        if valid:
            valid_indices.append(index)
            centers.append(center)
            last_center = center
            row.update(heard=False, onset_status="not_detected", reason="no_unique_attack_in_search_window")
        per_note.append(row)
    assignments = _assign(centers, candidates)
    for position, candidate_index in assignments.items():
        row, candidate = per_note[valid_indices[position]], candidates[candidate_index]
        row.update({k: candidate[k] for k in ("onset_s", "detected_pitch", "detected_hz", "pitch_confidence",
                                               "periodicity", "voiced_frames", "pitch_reason")})
        row.update(heard=True, onset_status="candidate_matched", reason=None,
                   onset_offset_ms=round((candidate["onset_s"] - centers[position]) * 1000),
                   clarity_db=candidate["level_over_floor_db"])
        if row["detected_hz"] is not None:
            cents = 1200 * math.log2(row["detected_hz"] / targets[row["index"]])
            row.update(cents_off=round(cents, 1), pitch_match=row["detected_pitch"] == row["expected_pitch"],
                       in_tune=abs(cents) <= TUNING_TOLERANCE_CENTS)
    matched = [r for r in per_note if r["heard"] is True]
    unknown = [r["index"] for r in per_note if r["heard"] is None]
    summary = {
        "notes_planned": len(per_note), "notes_heard": len(matched), "onsets_matched": len(matched),
        "pitch_assessed": sum(r["pitch_match"] is not None for r in per_note),
        "pitch_matched": sum(r["pitch_match"] is True for r in per_note),
        "mean_clarity_db": round(float(np.mean([r["clarity_db"] for r in matched])), 1) if matched else None,
        "onset_jitter_ms": None,  # no intended onset schedule or calibrated command/audio alignment
        "noise_floor_dbfs": round(floor_db, 1),
        "missed_indices": [r["index"] for r in per_note if r["heard"] is False],
        "unknown_indices": unknown,
        "unassigned_attack_candidates": len(candidates) - len(assignments),
        "matched_inter_onset_intervals_ms": [round((b["onset_s"] - a["onset_s"]) * 1000, 1)
                                            for a, b in zip(matched, matched[1:])],
        "method": "Energy-rise candidates, monotonic one-to-one assignment, multiframe normalized periodicity; "
                  "heard counts candidate attacks, not verified guitar notes. Clarity is only level above estimated noise.",
    }
    return {
        "schema_version": VERSION,
        "status": "limited" if unknown or excessive_events or any(r["pitch_match"] is None for r in per_note) else "measured",
        "source_sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "parameters": {"onset_rise_db": ONSET_RISE_DB, "onset_over_floor_db": ONSET_OVER_FLOOR_DB,
                       "minimum_level_dbfs": MIN_LEVEL_DBFS, "minimum_attack_gap_s": MIN_ATTACK_GAP_S,
                       "pitch_range_hz": [PITCH_MIN_HZ, PITCH_MAX_HZ],
                       "tuning_tolerance_cents": TUNING_TOLERANCE_CENTS},
        "capture": {"sample_rate_hz": rate, "duration_s": count / rate, "channels": channels,
                    "peak_dbfs": round(_db(peak), 1), "clipped_sample_fraction": float(np.mean(clipped)),
                    "excessive_event_candidates": excessive_events},
        "alignment": {"reference": "approximate_tap_encoder_ready", "calibrated": False,
                      "analysis_hop_ms": hop / rate * 1000, "intended_onset_schedule_available": False},
        "limitations": ["Heuristic monophonic estimates, not calibrated confidence or guitar/contact verification.",
                        "Browser/server/input latency is uncalibrated; offsets are not rhythm errors or command-to-sound delay.",
                        "Quiet/overlapping notes, ringing, motor noise and weak fundamentals can remain ambiguous."],
        "per_note": per_note, "summary": summary,
    }
