"""Deterministic per-note acoustic measurement of a supervised take.

Pure local DSP (numpy) over the saved capture WAV, aligned to the take's own
telemetry: for every planned note we know roughly WHEN its tap stage ran
(dispatch_frame + server_elapsed_s + stage timings), so we can measure whether
a sound onset actually occurred there, how clear it was over the noise floor,
and what fundamental pitch the following window carried.

This is the loop's primary evidence: reproducible numbers, not model hearing.
It cannot verify musical quality or true string contact — it measures energy
onsets and periodicity, and says so. The browser/server alignment is
approximate (network + thread start), so each note gets a search window
rather than a point, and offsets are reported relative to the expected time.
"""
from __future__ import annotations

import io
import math
import wave

import numpy as np

FRAME_S = 0.010          # analysis hop
ONSET_PRE_S = 0.30       # search this far before the expected tap time
ONSET_POST_S = 0.55      # ... and this far after
ONSET_OVER_FLOOR_DB = 10.0  # a frame this far above the noise floor is an onset
PITCH_WINDOW_S = 0.25    # pitch is estimated over this span after the onset
PITCH_MIN_HZ = 70.0
PITCH_MAX_HZ = 500.0
PITCH_MATCH_CENTS = 80.0

_SEMIS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _hz(pitch_name: str) -> float:
    body, octave = pitch_name[:-1], int(pitch_name[-1])
    midi = 12 * (octave + 1) + _SEMIS.index(body)
    return 440.0 * 2 ** ((midi - 69) / 12)


def _name(freq_hz: float) -> str:
    midi = int(round(69 + 12 * math.log2(freq_hz / 440.0)))
    return f"{_SEMIS[midi % 12]}{midi // 12 - 1}"


def _tap_time_s(note_event: dict) -> float | None:
    """Expected sound time within the capture: note start + its tap stage end."""
    base = note_event.get("server_elapsed_s")
    stages = (note_event.get("result") or {}).get("stages") or []
    tap = next((s for s in stages if s.get("stage") == "tap"), None)
    if base is None or tap is None:
        return None
    # note_end's server_elapsed_s is stamped at note END; subtract the part of
    # the tap that ran after impact plus the lift stage to get close to impact.
    total = stages[-1].get("encoder_ready_s")
    if total is None or tap.get("encoder_ready_s") is None:
        return None
    return float(base) - (float(total) - float(tap["encoder_ready_s"]))


def _autocorr_pitch(chunk: np.ndarray, rate: int) -> float | None:
    if len(chunk) < int(rate / PITCH_MIN_HZ) * 2:
        return None
    chunk = chunk - chunk.mean()
    if not np.any(chunk):
        return None
    corr = np.correlate(chunk, chunk, mode="full")[len(chunk) - 1:]
    lo, hi = int(rate / PITCH_MAX_HZ), min(int(rate / PITCH_MIN_HZ), len(corr) - 1)
    if hi <= lo or corr[0] <= 0:
        return None
    lag = lo + int(np.argmax(corr[lo:hi]))
    if corr[lag] / corr[0] < 0.25:  # not periodic enough to call a pitch
        return None
    return rate / lag


def measure_take(wav_bytes: bytes, telemetry: list[dict], dispatch_frame: int,
                 expected_pitches: list[str]) -> dict:
    """-> {"per_note": [...], "summary": {...}} — deterministic, no model."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        rate, frames = reader.getframerate(), reader.getnframes()
        samples = np.frombuffer(reader.readframes(frames), dtype="<i2").astype(np.float64)
        if reader.getnchannels() == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)
    samples /= 32768.0

    hop = max(1, int(rate * FRAME_S))
    usable = len(samples) - len(samples) % hop
    frame_rms = np.sqrt(np.mean(samples[:usable].reshape(-1, hop) ** 2, axis=1)) + 1e-9
    floor = float(np.percentile(frame_rms, 20))
    floor_db = 20 * math.log10(floor)

    note_ends = [e for e in telemetry if e.get("event") == "note_end"]
    play_start_s = dispatch_frame / rate
    per_note = []
    for index, event in enumerate(note_ends):
        expected = expected_pitches[index] if index < len(expected_pitches) else None
        tap_s = _tap_time_s(event)
        entry = {"index": index, "expected_pitch": expected, "heard": False,
                 "onset_offset_ms": None, "clarity_db": None,
                 "detected_pitch": None, "pitch_match": None}
        if tap_s is not None:
            center = play_start_s + tap_s
            a = max(0, int((center - ONSET_PRE_S) / FRAME_S))
            b = min(len(frame_rms), int((center + ONSET_POST_S) / FRAME_S) + 1)
            window = frame_rms[a:b]
            if len(window):
                over = 20 * np.log10(window) - floor_db
                onsets = np.nonzero(over >= ONSET_OVER_FLOOR_DB)[0]
                if len(onsets):
                    onset_frame = a + int(onsets[0])
                    entry["heard"] = True
                    entry["onset_offset_ms"] = round((onset_frame * FRAME_S - center) * 1000)
                    entry["clarity_db"] = round(float(np.max(over[onsets[0]:])), 1)
                    start = onset_frame * hop
                    freq = _autocorr_pitch(samples[start:start + int(rate * PITCH_WINDOW_S)], rate)
                    if freq:
                        entry["detected_pitch"] = _name(freq)
                        if expected:
                            cents = 1200 * math.log2(freq / _hz(expected))
                            entry["pitch_match"] = bool(abs(cents) <= PITCH_MATCH_CENTS)
                            entry["cents_off"] = round(cents)
        per_note.append(entry)

    heard = [n for n in per_note if n["heard"]]
    matched = [n for n in per_note if n["pitch_match"]]
    offsets = [n["onset_offset_ms"] for n in heard if n["onset_offset_ms"] is not None]
    summary = {
        "notes_planned": len(per_note), "notes_heard": len(heard),
        "pitch_matched": len(matched),
        "mean_clarity_db": round(float(np.mean([n["clarity_db"] for n in heard])), 1) if heard else None,
        "onset_jitter_ms": round(float(np.std(offsets))) if len(offsets) > 1 else None,
        "noise_floor_dbfs": round(floor_db, 1),
        "missed_indices": [n["index"] for n in per_note if not n["heard"]],
        "method": "local RMS-onset + autocorrelation pitch at telemetry-predicted tap "
                  "times; alignment approximate; onsets are energy events, not "
                  "verified string contact",
    }
    return {"per_note": per_note, "summary": summary}
