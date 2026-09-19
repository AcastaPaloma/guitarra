"""Always-on mic ring buffer + a small pluck scorer (see sense/README.md).

The stream is opened once; capture() slices audio by monotonic time, so the moment the
stroke was commanded (t_cmd from robot/arm.py) lines up with what was heard.
"""
import threading
import time

import numpy as np
import sounddevice as sd

SR = 44100
HOP = 512
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(hz: float) -> str:
    midi = int(round(69 + 12 * np.log2(hz / 440.0)))
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def note_hz(name: str) -> float:
    pitch, octave = name[:-1], int(name[-1])
    midi = NOTE_NAMES.index(pitch) + 12 * (octave + 1)
    return 440.0 * 2 ** ((midi - 69) / 12)


def transpose(name: str, semitones: int) -> str:
    return note_name(note_hz(name) * 2 ** (semitones / 12))


def db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))


class Mic:
    def __init__(self, seconds: float = 10.0, device=None):
        self.buf = np.zeros(int(SR * seconds), dtype=np.float32)
        self.write = 0          # total samples written
        self.t_last = 0.0       # monotonic time of the last sample written
        self.lock = threading.Lock()
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=self._cb, device=device)
        self.floor_db = -90.0

    def _cb(self, indata, frames, t, status):
        now = time.monotonic()
        x = indata[:, 0]
        with self.lock:
            idx = (self.write + np.arange(frames)) % len(self.buf)
            self.buf[idx] = x
            self.write += frames
            self.t_last = now

    def start(self):
        self.stream.start()
        time.sleep(0.3)
        return self

    def stop(self):
        self.stream.stop(); self.stream.close()

    def capture(self, t0: float, t1: float) -> np.ndarray:
        """Audio between monotonic times t0 and t1 (waits until t1 has been recorded)."""
        while self.t_last < t1:
            time.sleep(0.02)
        with self.lock:
            end = self.write - int((self.t_last - t1) * SR)
            n = int((t1 - t0) * SR)
            idx = (end - n + np.arange(n)) % len(self.buf)
            return self.buf[idx].copy()

    def measure_floor(self, seconds: float = 1.5) -> float:
        """Noise floor with the arm holding still under torque (servo whine is the real floor)."""
        now = time.monotonic()
        self.floor_db = db(self.capture(now, now + seconds))
        return self.floor_db


def onsets(x: np.ndarray, k: float = 4.0) -> list[float]:
    """Onset times (s from window start) from spectral flux peaks above k x median."""
    frames = np.lib.stride_tricks.sliding_window_view(x, 2 * HOP)[::HOP] * np.hanning(2 * HOP)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    thresh = k * (np.median(flux) + 1e-9)
    peaks = [i for i in range(1, len(flux) - 1) if flux[i] > thresh and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]]
    out, last = [], -1e9
    for i in peaks:                      # merge peaks closer than 50 ms
        t = (i + 1) * HOP / SR
        if t - last > 0.05:
            out.append(t); last = t
    return out


def pitch(x: np.ndarray, lo: float = 60.0, hi: float = 1200.0, threshold: float = 0.15) -> float | None:
    """Fundamental via YIN on 4096 samples just after the loudest point (robust to strong overtones)."""
    w, max_lag = 4096, int(SR / lo)
    if len(x) < w + max_lag:
        return None
    energy = np.convolve(x ** 2, np.ones(1024), "valid")
    start = int(np.clip(np.argmax(energy), 0, len(x) - w - max_lag))
    frame = x[start:start + w + max_lag].astype(np.float64)
    min_lag = int(SR / hi)
    d = np.array([np.sum((frame[:w] - frame[tau:tau + w]) ** 2) for tau in range(max_lag + 1)])
    cmnd = np.ones_like(d)
    cmnd[1:] = d[1:] * np.arange(1, len(d)) / (np.cumsum(d[1:]) + 1e-12)
    tau = next((t for t in range(min_lag, max_lag) if cmnd[t] < threshold and cmnd[t] <= cmnd[t + 1]), None)
    if tau is None:
        tau = min_lag + int(np.argmin(cmnd[min_lag:max_lag]))
    # parabolic interpolation around the minimum for sub-sample lag
    a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0.0
    return float(SR / (tau + shift))


def score(mic: Mic, t_cmd: float, target: str, pre: float = 0.1, post: float = 1.2) -> dict:
    """Compact scorer JSON for one stroke: did it ring, when, and at what pitch."""
    x = mic.capture(t_cmd - pre, t_cmd + post)
    level = db(x)
    rang = level > mic.floor_db + 6
    ons = onsets(x) if rang else []  # below the floor, "onsets" are just room noise
    f0 = pitch(x) if rang else None
    out = {
        "rang": bool(rang),
        "level_over_floor_db": round(level - mic.floor_db, 1),
        "onsets": len(ons),
        "first_onset_ms": round((ons[0] - pre) * 1000) if ons else None,
        "pitch": note_name(f0) if f0 else None,
        "target": target,
    }
    if not rang:
        out["note"] = "silent - pick probably missed the string (too shallow or off to the side)"
    elif f0 and note_name(f0) != target:
        cents = 1200 * np.log2(f0 / note_hz(target))
        out["note"] = f"rang but pitch {note_name(f0)} ({cents:+.0f} cents from {target}) - wrong string/fret, or fret not pressed down"
    elif len(ons) > 1:
        out["note"] = f"{len(ons)} onsets - pick may have buzzed or snagged"
    else:
        out["note"] = "clean pluck"
    return out


def wait_for_pluck(mic: Mic, target: str, timeout_s: float = 8.0) -> dict:
    """Fretting-arm check: wait for the string to be plucked (by a person or the pluck arm),
    then score what sounded against the fretted note."""
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        now = time.monotonic()
        if db(mic.capture(now - 0.05, now)) > mic.floor_db + 10:
            return score(mic, now - 0.05, target)
        time.sleep(0.02)
    return {"rang": False, "target": target, "note": f"nobody plucked within {timeout_s:g}s - no measurement"}
