"""Offline regressions for local acoustic estimates, not physical qualification.

Waveforms and telemetry are generated fixtures, never real guitar or latency
evidence. The six original investigation failures are now ordinary regressions.
"""
import io
import json
import wave

import numpy as np
import pytest

from tap_audio_metrics import measure_take


DURATION_S = 3.0
DISPATCH_S = 0.1


def synthetic_wav(tones=(), *, rate=16000):
    """Each tone is (start_s, duration_s, frequency_hz, amplitude, decay_s)."""
    samples = np.random.default_rng(9).normal(0, 0.00004, int(rate * DURATION_S))
    for start, duration, frequency, amplitude, decay in tones:
        t = np.arange(int(duration * rate)) / rate
        envelope = np.exp(-t / decay) if decay else np.ones_like(t)
        offset = int(start * rate)
        samples[offset:offset + len(t)] += amplitude * envelope * np.sin(2 * np.pi * frequency * t)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.rint(np.clip(samples, -1, 0.9999) * 32768).astype("<i2").tobytes())
    return stream.getvalue()


def synthetic_event(index, capture_s):
    # By construction _tap_time_s(event) + DISPATCH_S == capture_s. These
    # invented stage times ONLY test the math, not browser/ADC synchronization.
    return {
        "event": "note_end", "index": index,
        "server_elapsed_s": capture_s - DISPATCH_S + 0.2,
        "result": {"stages": [
            {"stage": "tap", "command_start_s": 0.1, "encoder_ready_s": 0.2},
            {"stage": "lift_clear", "command_start_s": 0.32, "encoder_ready_s": 0.4},
        ]},
    }


def measure(tones, expected, centers, *, rate=16000, indices=None):
    indices = range(len(centers)) if indices is None else indices
    telemetry = [synthetic_event(i, t) for i, t in zip(indices, centers)]
    return measure_take(synthetic_wav(tones, rate=rate), telemetry, int(rate * DISPATCH_S), expected)


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
def test_isolated_sine_control(rate):
    metrics = measure([(1, 0.4, 220, 0.2, None)], ["A3"], [1], rate=rate)
    note = metrics["per_note"][0]
    assert note["heard"] and note["pitch_match"]
    assert note["detected_pitch"] == "A3"
    assert abs(note["onset_offset_ms"]) <= 10
    assert abs(note["cents_off"]) < 20


def test_background_only_control():
    metrics = measure([], ["A3"], [1])
    assert metrics["summary"]["notes_heard"] == 0
    assert metrics["per_note"][0]["detected_pitch"] is None


def test_semitone_mismatch_control():
    metrics = measure([(1, 0.4, 220 * 2 ** (1 / 12), 0.2, None)], ["A3"], [1])
    assert metrics["per_note"][0]["pitch_match"] is False


def test_sustain_cannot_supply_three_new_attacks():
    metrics = measure([(0.6, 1.9, 220, 0.2, None)], ["A3"] * 3, [1.2, 1.8, 2.2])
    # The only attack is at 0.6s, BEFORE every command's search window. None
    # of these three expected notes has a new attack in its own window.
    assert metrics["summary"]["notes_heard"] == 0


def test_one_attack_cannot_match_two_expected_notes():
    metrics = measure([(1.1, 0.15, 220, 0.2, None)], ["A3"] * 2, [1.0, 1.3])
    assert metrics["summary"]["notes_heard"] <= 1


def test_absent_telemetry_preserves_expected_note_rows():
    metrics = measure([], ["A3"] * 3, [])
    assert metrics["summary"]["notes_planned"] == 3
    assert len(metrics["per_note"]) == 3
    # Missing alignment is UNKNOWN, not acoustic evidence of a missed note.
    assert metrics["summary"]["missed_indices"] == []


def test_event_identity_not_iteration_order_selects_expected_pitch():
    metrics = measure([(1, 0.4, 293.6648, 0.2, None)], ["A3", "C4", "D4"], [1], indices=[2])
    detected = next(n for n in metrics["per_note"] if n["detected_pitch"] == "D4")
    assert detected["index"] == 2
    assert detected["expected_pitch"] == "D4"


def test_adjacent_note_or_boundary_ambiguity_is_not_an_unqualified_match():
    metrics = measure([(1, 0.4, 220 * 2 ** (60 / 1200), 0.2, None)], ["A3"], [1])
    # Separate tuning tolerance from note identity. A tone nearer A#3 cannot
    # also be an unqualified discrete A3 match; uncertainty is acceptable.
    assert metrics["per_note"][0]["pitch_match"] is not True


def test_weak_fundamental_is_correct_or_explicitly_ambiguous():
    metrics = measure([(1, 0.4, 110, 0.01, 0.1), (1, 0.4, 220, 0.2, 0.1)], ["A2"], [1])
    note = metrics["per_note"][0]
    # This synthetic sum has a 110 Hz fundamental and a dominant second
    # harmonic. No perfect detector is assumed: an unknown result is valid.
    assert note["detected_pitch"] == "A2" or note["pitch_match"] is None


@pytest.mark.parametrize("rate", [8000, 22050, 96000])
def test_pitch_and_onset_use_the_actual_sample_clock(rate):
    metrics = measure([(1.23, 0.3, 220, 0.2, None)], ["A3"], [1.23], rate=rate)
    note = metrics["per_note"][0]
    assert abs(note["onset_s"] - 1.23) < 0.011
    assert note["pitch_match"] is True
    assert note["timing_error_ms"] is None
    assert note["command_to_sound_delay_ms"] is None
    assert metrics["summary"]["onset_jitter_ms"] is None
    assert metrics["alignment"]["calibrated"] is False
    json.dumps(metrics, allow_nan=False)


def test_long_22050hz_capture_does_not_accumulate_nominal_hop_drift(monkeypatch):
    monkeypatch.setitem(synthetic_wav.__globals__, "DURATION_S", 30.0)
    result = measure([(25, 0.3, 220, 0.2, None)], ["A3"], [25], rate=22050)
    assert abs(result["per_note"][0]["onset_s"] - 25) < 0.011


def test_pitch_is_estimated_independently_of_the_target():
    tones = [(1, 0.3, 220, 0.2, None)]
    matched = measure(tones, ["A3"], [1])["per_note"][0]
    wrong = measure(tones, ["A4"], [1])["per_note"][0]
    assert wrong["detected_hz"] == matched["detected_hz"]
    assert matched["pitch_match"] is True and wrong["pitch_match"] is False


def test_duplicate_telemetry_identity_stays_unknown():
    data = synthetic_wav([(1, 0.3, 220, 0.2, None)])
    event = synthetic_event(0, 1)
    result = measure_take(data, [event, event], 1600, ["A3"])
    assert result["per_note"][0]["heard"] is None
    assert result["summary"]["unknown_indices"] == [0]
    assert result["summary"]["missed_indices"] == []


@pytest.mark.parametrize("base", [None, -1, float("nan"), float("inf"), True])
def test_invalid_reference_is_unknown_not_a_missed_note(base):
    data = synthetic_wav([(1, 0.3, 220, 0.2, None)])
    event = synthetic_event(0, 1)
    event["server_elapsed_s"] = base
    result = measure_take(data, [event], 1600, ["A3"])
    assert result["per_note"][0]["heard"] is None
    assert result["summary"]["missed_indices"] == []
    json.dumps(result, allow_nan=False)


def test_missing_tap_stage_is_unknown():
    data = synthetic_wav([(1, 0.3, 220, 0.2, None)])
    event = synthetic_event(0, 1)
    event["result"]["stages"] = []
    result = measure_take(data, [event], 1600, ["A3"])
    assert result["per_note"][0]["heard"] is None


def test_clipped_window_withholds_pitch_accuracy():
    result = measure([(1, 0.3, 220, 2.0, None)], ["A3"], [1])
    assert result["capture"]["clipped_sample_fraction"] > 0
    assert result["per_note"][0]["pitch_match"] is None
    assert result["per_note"][0]["pitch_reason"] == "clipped_window"


def test_zero_samples_cannot_be_missed_notes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * (16000 * 3 * 2))
    result = measure_take(stream.getvalue(), [synthetic_event(0, 1)], 1600, ["A3"])
    assert result["per_note"][0]["heard"] is None
    assert result["summary"]["pitch_assessed"] == 0


def test_truncated_wave_cannot_produce_measurements():
    with pytest.raises(ValueError, match="Truncated"):
        measure_take(synthetic_wav()[:-200], [], 1600, ["A3"])


def test_one_unique_candidate_per_note_with_extra_attack_counted_separately():
    tones = [(0.2, 0.12, 220, 0.2, None), (1, 0.2, 220, 0.2, None), (2, 0.2, 261.6256, 0.2, None)]
    result = measure(tones, ["A3", "C4"], [1, 2])
    assert result["summary"]["onsets_matched"] == 2
    assert result["summary"]["unassigned_attack_candidates"] == 1
    assert result["summary"]["pitch_matched"] == 2
    assert result["summary"]["matched_inter_onset_intervals_ms"] == pytest.approx([1000], abs=11)


def test_semitone_boundary_abstains_instead_of_arbitrary_note_assignment():
    result = measure([(1, 0.3, 220 * 2 ** (50 / 1200), 0.2, None)], ["A3"], [1])
    assert result["per_note"][0]["pitch_match"] is None
    assert result["per_note"][0]["pitch_reason"] == "near_semitone_boundary"
