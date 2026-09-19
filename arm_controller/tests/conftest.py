"""Device-free single-arm console tests. Never import a motion script as a test."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "guitar"))
sys.path.insert(0, str(ROOT / "arm_controller"))


@pytest.fixture(autouse=True)
def no_devices_or_live_models(monkeypatch):
    import serial
    from model import baseten

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline test attempted a real device or provider request")

    monkeypatch.setattr(serial, "Serial", forbidden)
    monkeypatch.setattr(baseten, "request_json", forbidden)
