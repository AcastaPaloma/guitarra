"""Frames from sense/camera_relay.py (which runs in Terminal because it holds camera permission)."""
import json
import urllib.request

RELAY = "http://127.0.0.1:8765"
MAX_AGE_S = 1.0


class CameraError(Exception):
    pass


def grab(relay: str = RELAY) -> bytes:
    """Latest frame as Astra/Claude get it: 768 px wide JPEG. Refuses stale frames."""
    try:
        health = json.load(urllib.request.urlopen(f"{relay}/health", timeout=2))
        if health["age_s"] is None or health["age_s"] > MAX_AGE_S:
            raise CameraError(f"camera feed stale (latest frame {health['age_s']}s old) - restart camera_relay.py")
        return urllib.request.urlopen(f"{relay}/astra.jpg", timeout=3).read()
    except OSError as e:
        raise CameraError(f"camera relay not reachable at {relay} - is camera_relay.py running? ({e})") from e
