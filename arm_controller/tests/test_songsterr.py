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


RIG_KEYS = {(s, f) for s in range(1, 7) for f in range(1, 4)}


def tab_of(notes, tuning=songsterr.STANDARD_TUNING):
    return {"song": "S", "artist": "A", "track_name": "T", "track_index": 0,
            "tuning": tuning, "standard_tuning": tuning == songsterr.STANDARD_TUNING,
            "notes": notes, "total_notes": len(notes)}


def test_transcribe_keeps_exact_string_and_fret_for_in_range_notes():
    notes = [{"measure": 1, "string": 3, "fret": 2}, {"measure": 1, "string": 1, "fret": 1},
             {"measure": 2, "string": 6, "fret": 3}]
    result = songsterr.transcribe(tab_of(notes), RIG_KEYS)
    assert result["notes"] == [(3, 2), (1, 1), (6, 3)]
    assert result["transpose"] == 0 and result["exact"] == 3
    assert result["approximated"] == 0 and result["dropped"] == 0


def test_transcribe_transposes_whole_line_to_fit_the_rig():
    # frets 8-10 on string 1 are far above the rig's range; one global -7
    # (or octave-preferred) shift must map ALL notes at exact pitches.
    notes = [{"measure": 1, "string": 1, "fret": 13},
             {"measure": 1, "string": 1, "fret": 14},
             {"measure": 1, "string": 1, "fret": 15}]
    result = songsterr.transcribe(tab_of(notes), RIG_KEYS)
    assert result["transpose"] == -12 and result["exact"] == 3
    assert result["notes"] == [(1, 1), (1, 2), (1, 3)]


def test_transcribe_respects_non_standard_tuning():
    # whole-step-down tuning: string 1 fret 3 sounds like standard fret 1
    drop = [m - 2 for m in songsterr.STANDARD_TUNING]
    result = songsterr.transcribe(
        tab_of([{"measure": 1, "string": 1, "fret": 3}], tuning=drop), RIG_KEYS)
    assert result["notes"] == [(1, 1)] and result["exact"] == 1


def test_transcribe_drops_only_truly_unreachable_notes():
    keys = {(1, 1)}  # rig knows a single pitch
    notes = [{"measure": 1, "string": 1, "fret": 1},
             {"measure": 1, "string": 6, "fret": 1}]  # ~24 semitones apart
    result = songsterr.transcribe(tab_of(notes), keys)
    assert result["exact"] == 1 and result["dropped"] == 1
    assert result["notes"] == [(1, 1)]


def test_plan_with_tab_is_deterministic_no_model_call(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(webapp, "read_registry",
                        lambda: {"keys": RIG_KEYS, "grid": None, "row_rests": {},
                                 "path_profiles": ("rest_hub",), "fingerprint": "x",
                                 "warnings": []})
    monkeypatch.setattr(webapp.songsterr, "fetch_track_notes",
                        lambda song_id, track=None: tab_of(
                            [{"measure": 1, "string": 1, "fret": 1},
                             {"measure": 1, "string": 2, "fret": 2}]))

    def no_model(*args, **kwargs):
        raise AssertionError("tab mode must not call the arrangement model")

    monkeypatch.setattr(webapp, "arrange", no_model)
    response = client.post("/api/plan", json={"prompt": "play S", "allow_inference": True,
                                              "songsterr_song_id": 7})
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "deterministic-tab-transcription"
    assert data["notes"] == [{"arm": "tap_primary", "string": 1, "fret": 1},
                             {"arm": "tap_primary", "string": 2, "fret": 2}]
    assert data["path_profile"] == "lift_first"
    assert data["transcription"]["exact"] == 2 and data["transcription"]["transpose"] == 0
    assert data["tab_source"]["song"] == "S"
