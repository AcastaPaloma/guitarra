"""Budget-exceeding takes are refused with a clean message, never a 500."""
from test_tap_web import client  # noqa: F401 - pytest fixture


def oversized_preparation():
    return {"plan": {"notes": [{"string": 1, "fret": 1, "pause_ms": 250}] * 64,
                     "path_profile": "rest_hub"},
            "allow_audio_upload": True, "allow_revision_inference": True,
            "supervised_and_supported": True}


def test_budget_overrun_is_a_clean_409_not_a_500(client):  # noqa: F811
    response = client.post("/api/attempts", json=oversized_preparation())
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "budget" in detail and "notes" in detail  # actionable, names the cap


def test_bootstrap_exposes_the_budget_for_the_ui(client):  # noqa: F811
    data = client.get("/api/bootstrap").json()
    assert data["max_play_seconds"] == 150 and data["note_pace_s"] == 3.2
