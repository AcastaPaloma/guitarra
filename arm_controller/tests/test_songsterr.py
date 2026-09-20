"""Songsterr tab lookup: offline parsing, condensing, and endpoint wiring."""
import pytest
import songsterr
import webapp
from test_tap_web import client  # noqa: F401 - pytest fixture

META = {"songId": 7, "revisionId": 11, "image": "v0-abc", "title": "Song", "artist": "Band",
        "popularTrackGuitar": 1, "defaultTrack": 0,
        "tracks": [{"tuning": None, "hash": "drums_x"},
                   {"tuning": songsterr.STANDARD_TUNING, "hash": "guitar_x"}]}
TRACK = {"name": "Lead", "tuning": songsterr.STANDARD_TUNING,
         "measures": [
             {"voices": [{"beats": [
                 {"notes": [{"string": 0, "fret": 3}], "duration": [1, 4]},
                 {"rest": True, "duration": [1, 4]},
                 {"notes": [{"string": 1, "fret": 2}, {"string": 2, "fret": 0}]},
             ]}]},
             {"voices": [{"beats": [
                 {"notes": [{"string": 5, "fret": 1, "tie": True}]},
                 {"notes": [{"string": 3, "fret": 5}]},
             ]}]},
         ]}


def fake_get(urls):
    def _get(url):
        for fragment, payload in urls.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL {url}")
    return _get


def test_fetch_track_notes_extracts_melody_line(monkeypatch):
    monkeypatch.setattr(songsterr, "_get_json",
                        fake_get({"/api/meta/7": META, "/7/11/v0-abc/1.json": TRACK}))
    tab = songsterr.fetch_track_notes(7)
    # picks the guitar track (index 1), skips rests/ties, takes the top note per beat,
    # converts to string 1 = high E
    assert tab["track_index"] == 1 and tab["standard_tuning"] is True
    assert tab["notes"] == [{"measure": 1, "string": 1, "fret": 3},
                            {"measure": 1, "string": 2, "fret": 2},
                            {"measure": 2, "string": 4, "fret": 5}]


def test_condense_flags_non_standard_tuning(monkeypatch):
    drop = dict(TRACK, tuning=[62, 59, 55, 50, 45, 38])
    monkeypatch.setattr(songsterr, "_get_json",
                        fake_get({"/api/meta/7": META, "/7/11/v0-abc/1.json": drop}))
    text = songsterr.condense(songsterr.fetch_track_notes(7))
    assert "NON-STANDARD TUNING" in text and "m1: (1,3) (2,2)" in text


def test_no_guitar_track_is_an_error(monkeypatch):
    meta = dict(META, tracks=[{"tuning": None, "hash": "drums_x"}],
                popularTrackGuitar=0, defaultTrack=0)
    monkeypatch.setattr(songsterr, "_get_json", fake_get({"/api/meta/7": meta}))
    with pytest.raises(songsterr.SongsterrError, match="6-string"):
        songsterr.fetch_track_notes(7)


def test_tab_search_endpoint(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(webapp.songsterr, "search",
                        lambda pattern, size=8: [{"songId": 1, "artist": "A",
                                                  "title": pattern, "tracks": 2}])
    data = client.get("/api/tabs/search", params={"pattern": "test song"}).json()
    assert data["results"][0]["title"] == "test song"
    assert client.get("/api/tabs/search", params={"pattern": ""}).status_code == 400


def test_plan_passes_tab_context_to_arranger(client, monkeypatch):  # noqa: F811
    captured = {}
    monkeypatch.setattr(webapp.songsterr, "fetch_track_notes",
                        lambda song_id, track=None: {"song": "S", "artist": "A",
                                                     "track_name": "T", "track_index": 0,
                                                     "tuning": songsterr.STANDARD_TUNING,
                                                     "standard_tuning": True,
                                                     "notes": [{"measure": 1, "string": 1, "fret": 1}],
                                                     "total_notes": 1})

    def fake_arrange(prompt, keys, tab_context=None):
        captured["tab"] = tab_context
        return {"title": "t", "model": "m",
                "notes": [{"string": 1, "fret": 1, "pause_ms": 250}],
                "path_profile": "rest_hub"}

    monkeypatch.setattr(webapp, "arrange", fake_arrange)
    response = client.post("/api/plan", json={"prompt": "play S", "allow_inference": True,
                                              "songsterr_song_id": 7})
    assert response.status_code == 200
    assert response.json()["tab_source"] == {"songId": 7, "artist": "A", "song": "S", "track": "T"}
    assert captured["tab"].startswith("OFFICIAL TAB (Songsterr): A — S")
