"""Optional camera-relay client; guitar agent camera input is OFF by default.

Call only after explicit camera opt-in. Importing this module does not open a device
or contact the relay. See sense/README.md for the separate diagnostic capture path.
"""
import json
import urllib.request

RELAY = "http://127.0.0.1:8765"
MAX_AGE_S = 1.0


class CameraError(Exception):
    pass


def grab(relay: str = RELAY) -> bytes:
    """Fetch an explicitly requested 768 px JPEG snapshot; refuse stale relay frames."""
    try:
        health = json.load(urllib.request.urlopen(f"{relay}/health", timeout=2))
        if health["age_s"] is None or health["age_s"] > MAX_AGE_S:
            raise CameraError(f"camera feed stale (latest frame {health['age_s']}s old) - restart camera_relay.py")
        return urllib.request.urlopen(f"{relay}/astra.jpg", timeout=3).read()
    except OSError as e:
        raise CameraError(f"camera relay not reachable at {relay} - is camera_relay.py running? ({e})") from e
