"""Offline regression checks for the file-only evaluator; no API or device access."""
import base64
import copy
import io
import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import audio  # noqa: E402
from model.baseten import BasetenError  # noqa: E402


def wav_file(tmp_path, *, rate=16000, channels=1, seconds=0.2, width=2):
    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\0" * (int(rate * seconds) * channels * width))
    return path


def response():
    assessment = {
        "recording_quality": "unusable", "notes_match": "not_assessed", "timing_match": "not_assessed",
        "summary": "Insufficient acoustic evidence.", "observations": [],
        "limitations": ["This is an offline mocked response, not a model hearing the guitar."],
        "score": 0, "suggestions": ["Check capture quality before judging any notes."],
    }
    return {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(assessment)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "prompt_tokens_details": {"audio_tokens": 20}}}


@pytest.mark.parametrize("rate,channels", [(16000, 1), (44100, 2), (48000, 1)])
def test_normalization_and_provenance(tmp_path, rate, channels):
    path = wav_file(tmp_path, rate=rate, channels=channels)
    before = path.read_bytes()
    clip = audio.prepare_clip(path)
    assert path.read_bytes() == before  # original recording never modified
    assert clip.metadata["source_sample_rate_hz"] == rate
    assert clip.metadata["source_channels"] == channels
    assert clip.metadata["duration_s"] == pytest.approx(0.2)
    assert clip.metadata["local_signal_estimates"]["rms_dbfs"] is None
    assert len(clip.metadata["source_sha256"]) == 64
    with wave.open(io.BytesIO(clip.wav_bytes)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.getnframes() == 3200
    assert 'wav_bytes=' not in repr(clip)


@pytest.mark.parametrize("options", [{"width": 1}, {"seconds": 0}, {"seconds": audio.MAX_SECONDS + 1}, {"rate": 12345}])
def test_invalid_audio_is_rejected_locally(tmp_path, options):
    with pytest.raises(ValueError):
        audio.prepare_clip(wav_file(tmp_path, **options))


def test_non_audio_and_truncated_wav_are_rejected(tmp_path):
    path = tmp_path / "not-a-recording"
    path.write_text("this content must never be uploaded")
    with pytest.raises(ValueError):
        audio.prepare_clip(path)
    path = wav_file(tmp_path)
    path.write_bytes(path.read_bytes()[:-30])
    with pytest.raises(ValueError, match="truncated"):
        audio.prepare_clip(path)


def test_no_consent_no_file_read_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Consent must be checked before file/env/API work")
    monkeypatch.setattr(audio, "prepare_clip", forbidden)
    monkeypatch.setattr(audio, "load_env", forbidden)
    monkeypatch.setattr(audio, "BasetenClient", forbidden)
    with pytest.raises(ValueError, match="explicit"):
        audio.evaluate_file(Path("unused.wav"), expected_phrase="A2", attempt_id="one")


@pytest.fixture
def fake_client(monkeypatch):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.chat.return_value = response()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(audio, "BasetenClient", factory)
    monkeypatch.setattr(audio, "load_env", lambda: None)
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "thinkingmachines/inkling")
    monkeypatch.setenv("BASETEN_AUDIO_TIMEOUT_S", "30")
    monkeypatch.setenv("BASETEN_MODEL", "moonshotai/Kimi-K3")
    return client, factory


def test_evaluator_request_has_audio_schema_and_no_tools(tmp_path, fake_client):
    client, factory = fake_client
    report = audio.evaluate_file(wav_file(tmp_path), expected_phrase="A2", attempt_id="synthetic-one",
                                 source="synthetic_fixture", allow_upload=True)
    assert report["status"] == "assessed"
    assert report["source"] == "synthetic_fixture"
    assert report["motion_authority"] is False
    assert report["clip"]["upload_sha256"]
    assert factory.call_args.kwargs["model"] == "thinkingmachines/inkling"
    assert factory.call_args.kwargs["timeout_s"] == 30
    messages = client.chat.call_args.args[0]
    assert "tools" not in client.chat.call_args.kwargs
    assert client.chat.call_args.kwargs["response_format"]["type"] == "json_schema"
    part = messages[-1]["content"][-1]
    assert part["type"] == "audio_url"
    url = part["audio_url"]["url"]
    assert url.startswith("data:audio/wav;base64,")
    with wave.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as wav:
        assert wav.getframerate() == 16000
    assert "base64" not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(messages)


def test_timeout_is_unavailable_not_negative_score(tmp_path, fake_client):
    client, _ = fake_client
    client.chat.side_effect = BasetenError("Provider timed out")
    report = audio.evaluate_file(wav_file(tmp_path), expected_phrase="A2", attempt_id="one", allow_upload=True)
    assert report["status"] == "unavailable" and report["assessment"] is None
    assert client.chat.call_count == 1  # no retry or fallback


@pytest.mark.parametrize("mutation", ["length", "refusal", "tools", "invalid_json", "extra_property", "unusable_success", "duplicate_keys"])
def test_bad_response_never_becomes_assessment(mutation):
    raw = response()
    choice, message = raw["choices"][0], raw["choices"][0]["message"]
    if mutation == "length": choice["finish_reason"] = "length"
    elif mutation == "refusal": message["refusal"] = "No"
    elif mutation == "tools": message["tool_calls"] = [{"name": "move_to"}]
    elif mutation == "invalid_json": message["content"] = "```json invalid```"
    elif mutation == "duplicate_keys": message["content"] = '{"summary":"a","summary":"b"}'
    else:
        data = json.loads(message["content"])
        if mutation == "extra_property": data["motion"] = "press"
        else: data["notes_match"] = "consistent"
        message["content"] = json.dumps(data)
    with pytest.raises(BasetenError):
        audio.parse_assessment(raw)


def test_audio_usage_required_before_claiming_assessment(tmp_path, fake_client):
    client, _ = fake_client
    result = copy.deepcopy(response())
    del result["usage"]["prompt_tokens_details"]
    client.chat.return_value = result
    report = audio.evaluate_file(wav_file(tmp_path), expected_phrase="A2", attempt_id="one", allow_upload=True)
    assert report["assessment"] is None and report["status"] == "unavailable"


def test_no_kimi_fallback_for_audio(tmp_path, fake_client, monkeypatch):
    monkeypatch.setenv("BASETEN_AUDIO_MODEL", "moonshotai/Kimi-K3")
    with pytest.raises(ValueError, match="not the Kimi planner"):
        audio.evaluate_file(wav_file(tmp_path), expected_phrase="A2", attempt_id="one", allow_upload=True)
    assert not fake_client[1].called
