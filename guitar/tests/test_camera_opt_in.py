"""Camera consent/default regressions. No cameras, microphones, robots, or model APIs."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import loop  # noqa: E402
from agent.backends import Turn  # noqa: E402
from agent.backends.baseten import _image_field  # noqa: E402
from agent.tools import NO_AUDIO_MESSAGE, ToolCall, Toolbox, specs  # noqa: E402
from sense import camera  # noqa: E402


def test_cli_camera_is_off_by_default_without_changing_mic_default():
    args = loop.parse_args([])
    assert args.use_camera is False
    assert args.no_mic is False


@pytest.mark.parametrize("flag,enabled", [("--camera", True), ("--no-camera", False)])
def test_explicit_camera_flags(flag, enabled):
    assert loop.parse_args([flag]).use_camera is enabled


def test_conflicting_camera_flags_are_rejected_before_startup():
    with pytest.raises(SystemExit) as exc:
        loop.parse_args(["--camera", "--no-camera"])
    assert exc.value.code == 2


@pytest.fixture
def mock_arm():
    return SimpleNamespace(
        state=Mock(return_value={"at": "ready"}),
        pluck=Mock(return_value={"t_cmd": 1.0, "duration_s": 0.5}),
        fret=Mock(return_value={"t_cmd": 1.0, "duration_s": 0.5}),
    )


def test_toolbox_default_look_reads_state_without_probing_camera(mock_arm, monkeypatch):
    grab = Mock(side_effect=AssertionError("camera must not be requested by default"))
    monkeypatch.setattr(camera, "grab", grab)
    tools = Toolbox(mock_arm)

    result = tools.run(ToolCall("look-1", "look", {}))

    assert tools.use_camera is False
    assert not result.is_error
    assert json.loads(result.text) == {"ok": True, "arm": {"at": "ready"}}
    assert result.image_jpeg is None
    assert _image_field(result.image_jpeg) == {}
    grab.assert_not_called()


def test_explicit_camera_opt_in_attaches_only_supplied_mock_frame(mock_arm, monkeypatch):
    frame = b"fake-camera-frame-not-a-real-recording"
    grab = Mock(return_value=frame)
    monkeypatch.setattr(camera, "grab", grab)

    result = Toolbox(mock_arm, use_camera=True).run(ToolCall("look-1", "look", {}))

    grab.assert_called_once_with()
    assert result.image_jpeg == frame
    assert "image_jpeg_b64" in _image_field(result.image_jpeg)


def test_opted_in_camera_failure_is_reported_without_an_image(mock_arm, monkeypatch):
    monkeypatch.setattr(camera, "grab", Mock(side_effect=camera.CameraError("relay unavailable")))

    result = Toolbox(mock_arm, use_camera=True).run(ToolCall("look-1", "look", {}))

    assert result.image_jpeg is None
    assert json.loads(result.text)["camera"] == "relay unavailable"


@pytest.mark.parametrize("role", ["fret", "pluck"])
def test_default_specs_do_not_promise_camera_or_microphone_measurements(role):
    definitions = {s["name"]: s for s in specs(["ready"], role, {5: [3, 5]})}

    assert "state only" in definitions["look"]["description"]
    assert "Camera input is disabled" in definitions["look"]["description"]
    assert "No acoustic measurement" in definitions[role]["description"]
    assert "camera snapshot" not in definitions[role]["description"]
    assert "camera snapshot" not in definitions["move_to"]["description"]


@pytest.mark.parametrize("role", ["fret", "pluck"])
def test_specs_advertise_explicitly_enabled_inputs(role):
    definitions = {
        s["name"]: s
        for s in specs(["ready"], role, {5: [3, 5]}, use_camera=True, use_mic=True)
    }

    assert "camera snapshot" in definitions["look"]["description"]
    assert "camera snapshot" in definitions[role]["description"]
    assert "local audio estimates" in definitions[role]["description"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("pluck", {"depth_mm": 1.0, "speed": 0.3}),
        ("fret", {"string": 5, "fret": 3, "press_mm": 1.0, "speed": 0.3}),
    ],
)
def test_missing_audio_never_tells_model_to_judge_sound_from_camera(
    name, args, mock_arm, monkeypatch,
):
    grab = Mock(side_effect=AssertionError("camera must stay off"))
    monkeypatch.setattr(camera, "grab", grab)

    result = Toolbox(mock_arm).run(ToolCall("motion-1", name, args))

    assert not result.is_error
    assert json.loads(result.text)["score"] == NO_AUDIO_MESSAGE
    assert result.image_jpeg is None
    grab.assert_not_called()


@pytest.mark.parametrize("role", ["fret", "pluck"])
@pytest.mark.parametrize("use_camera", [False, True])
@pytest.mark.parametrize("use_mic", [False, True])
def test_prompt_describes_only_enabled_observations(role, use_camera, use_mic):
    prompt = loop.build_system_prompt(
        role, goal="Test the qualified note", target="A2", turns=2,
        use_camera=use_camera, use_mic=use_mic,
    )

    assert ("Camera input is enabled" in prompt) is use_camera
    assert ("Camera input is disabled" in prompt) is (not use_camera)
    assert ("Microphone input is enabled" in prompt) is use_mic
    assert ("Microphone input is disabled" in prompt) is (not use_mic)
    assert "Test the qualified note" in prompt
    if not use_camera:
        assert "No images or video are provided" in prompt
        assert "do not claim to see the guitar" in prompt
    if not use_mic:
        assert "No acoustic measurement is available" in prompt


class RecordingBackend:
    name = "recording-test"

    def __init__(self):
        self.system = ""
        self.tool_specs = []
        self.opening_image = None
        self.results = []

    def begin(self, system, tool_specs, text, image_jpeg):
        self.system = system
        self.tool_specs = tool_specs
        self.opening_image = image_jpeg
        return Turn(text="", calls=[ToolCall("look-1", "look", {})], stop="tool_use")

    def respond(self, results, note=None):
        self.results.extend(results)
        return Turn(text="", calls=[ToolCall("done-1", "done", {"reason": "test complete"})], stop="tool_use")


@pytest.mark.parametrize(
    "flags,enabled",
    [([], False), (["--no-camera"], False), (["--camera"], True)],
)
def test_fake_loop_camera_mode_controls_requests_payloads_and_recordings(
    flags, enabled, monkeypatch, tmp_path,
):
    frame = b"fake-frame-for-opt-in-test"
    grab = Mock(return_value=frame) if enabled else Mock(
        side_effect=AssertionError("camera accessed without opt-in")
    )
    monkeypatch.setattr(camera, "grab", grab)
    monkeypatch.setattr("robot.arm.time.sleep", lambda _: None)
    monkeypatch.setattr(loop, "ROOT", tmp_path)  # no real .env reads or run files
    monkeypatch.setattr(loop, "RealArm", Mock(side_effect=AssertionError("no hardware")))
    backend = RecordingBackend()
    monkeypatch.setattr(loop.backends, "make", lambda *args, **kwargs: backend)
    monkeypatch.setattr(sys, "argv", [
        "loop", "--backend", "scripted", "--role", "fret", "--fake-arm",
        "--no-mic", "--turns", "2", *flags,
    ])

    loop.main()

    run = next((tmp_path / "runs").iterdir())
    records = [json.loads(line) for line in (run / "decisions.jsonl").read_text().splitlines()]
    start = next(r for r in records if r["event"] == "start")
    observation = json.loads(start["observation"])
    assert start["args"]["use_camera"] is enabled
    assert observation["inputs"] == {
        "camera": "enabled" if enabled else "disabled", "microphone": "disabled",
    }
    assert ("Camera input is enabled" in backend.system) is enabled
    look_spec = next(s for s in backend.tool_specs if s["name"] == "look")
    if enabled:
        assert grab.call_count == 2  # initial observation and look; both mocked
        assert backend.opening_image == frame
        assert backend.results[0].image_jpeg == frame
        assert len(list(run.glob("*.jpg"))) == 2
        assert "camera snapshot" in look_spec["description"]
    else:
        grab.assert_not_called()
        assert backend.opening_image is None
        assert all(result.image_jpeg is None for result in backend.results)
        assert not list(run.glob("*.jpg"))
        assert all(r.get("frame") is None for r in records)
        assert "state only" in look_spec["description"]
