"""Songsterr official-tab lookup for the tap console. Read-only, no auth.

Pipeline (verified live 2026-09-19):
  1. GET  {API}/api/songs?pattern=&size=      -> song matches (songId, artist, title)
  2. GET  {API}/api/meta/{songId}             -> stable revisionId, image id, tracks
  3. GET  {CDN}/{songId}/{revisionId}/{image}/{trackIndex}.json  (gzip)
         -> measures -> voices -> beats -> notes [{string (0 = highest), fret}]

The extracted notes are converted to this rig's convention (string 1 = high E)
and condensed to TEXT that the arrangement model receives as MUSICAL DATA. Tab
content is untrusted external content: it never reaches any executable path,
tool call, or servo command — the planner's strict key validation still admits
only currently recorded keys.

CLI (no hardware):
  python songsterr.py --search "seven nation army"
  python songsterr.py --notes 265            # popular guitar track
  python songsterr.py --notes 265 --track 3  # explicit track index
"""
import argparse
import gzip
import io
import json
import ssl
import urllib.parse
import urllib.request

try:  # macOS framework Python often ships without CA certs; certifi fills in.
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # system trust store; verification stays ON either way
    _SSL_CONTEXT = ssl.create_default_context()

API = "https://www.songsterr.com"
CDN = "https://dqsljvtekg760.cloudfront.net"
TIMEOUT_S = 12
MAX_BYTES = 8_000_000
MAX_RESULTS = 10
MAX_NOTES = 400
STANDARD_TUNING = [64, 59, 55, 50, 45, 40]  # E4 B3 G3 D3 A2 E2, high to low
_SEMIS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class SongsterrError(RuntimeError):
    pass


def _get_json(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "guitarra-tap-console/1.0", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S,
                                    context=_SSL_CONTEXT) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SongsterrError("Songsterr response too large")
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES)
    except OSError as exc:
        raise SongsterrError(f"Songsterr request failed: {exc}") from None
    try:
        return json.loads(raw)
    except ValueError:
        raise SongsterrError("Songsterr returned invalid JSON") from None


def search(pattern, size=8):
    """-> [{songId, artist, title, tracks: <guitar-ish track count>}]"""
    query = urllib.parse.urlencode({"pattern": pattern, "size": min(int(size), MAX_RESULTS)})
    data = _get_json(f"{API}/api/songs?{query}")
    if not isinstance(data, list):
        raise SongsterrError("Unexpected search response shape")
    out = []
    for song in data[:MAX_RESULTS]:
        try:
            out.append({"songId": int(song["songId"]), "artist": str(song["artist"]),
                        "title": str(song["title"]),
                        "tracks": sum(1 for t in song.get("tracks", [])
                                      if len(t.get("tuning") or []) == 6)})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _pick_guitar_track(meta, explicit=None):
    tracks = meta.get("tracks") or []
    if explicit is not None:
        if not (isinstance(explicit, int) and 0 <= explicit < len(tracks)):
            raise SongsterrError(f"track index {explicit} out of range (0-{len(tracks) - 1})")
        return explicit
    for key in ("popularTrackGuitar", "defaultTrack", "popularTrack"):
        idx = meta.get(key)
        if isinstance(idx, int) and 0 <= idx < len(tracks) \
                and len(tracks[idx].get("tuning") or []) == 6:
            return idx
    for idx, track in enumerate(tracks):
        if len(track.get("tuning") or []) == 6:
            return idx
    raise SongsterrError("No 6-string track in this tab")


def fetch_track_notes(song_id, track=None):
    """-> {song, artist, track_name, tuning, standard_tuning, notes: [...]}.

    notes: [{"measure": 1-based, "string": 1 = high E, "fret": int}, ...] in
    playing order, first note of each beat (melody line), rests/ties skipped.
    """
    meta = _get_json(f"{API}/api/meta/{int(song_id)}")
    for field in ("revisionId", "image", "tracks"):
        if not meta.get(field):
            raise SongsterrError(f"Song meta is missing {field}")
    index = _pick_guitar_track(meta, track)
    data = _get_json(f"{CDN}/{int(song_id)}/{meta['revisionId']}/{meta['image']}/{index}.json")
    measures = data.get("measures")
    if not isinstance(measures, list):
        raise SongsterrError("Track data has no measures")
    notes = []
    for measure_number, measure in enumerate(measures, start=1):
        for voice in (measure.get("voices") or [])[:1]:  # lead voice only
            for beat in voice.get("beats") or []:
                if beat.get("rest"):
                    continue
                for note in (beat.get("notes") or [])[:1]:  # melody: top note
                    if note.get("rest") or note.get("tie"):
                        continue
                    string, fret = note.get("string"), note.get("fret")
                    if isinstance(string, int) and isinstance(fret, int) and fret >= 0:
                        notes.append({"measure": measure_number,
                                      "string": string + 1, "fret": fret})
    if not notes:
        raise SongsterrError("No playable notes found in this track")
    tuning = data.get("tuning") or meta["tracks"][index].get("tuning") or []
    return {"song": str(meta.get("title", "")), "artist": str(meta.get("artist", "")),
            "track_name": str(data.get("name", "")), "track_index": index,
            "tuning": tuning, "standard_tuning": tuning == STANDARD_TUNING,
            "notes": notes[:MAX_NOTES], "total_notes": len(notes)}


def _pitch_name(midi):
    return f"{_SEMIS[midi % 12]}{midi // 12 - 1}"


def condense(tab):
    """Compact text for the arrangement model. Data only, never instructions."""
    lines = [f"OFFICIAL TAB (Songsterr): {tab['artist']} — {tab['song']} "
             f"[track: {tab['track_name']}]",
             "Format: measure: (string,fret)…  String 1 = high E … 6 = low E."]
    tuning = tab.get("tuning") or STANDARD_TUNING
    if not tab.get("standard_tuning"):
        named = " ".join(_pitch_name(m) for m in tuning)
        lines.append(f"NON-STANDARD TUNING high→low: {named} — convert to sounding "
                     "pitches before arranging.")
    if tab["total_notes"] > len(tab["notes"]):
        lines.append(f"(first {len(tab['notes'])} of {tab['total_notes']} notes)")
    current, parts = None, []
    for note in tab["notes"]:
        if note["measure"] != current:
            current = note["measure"]
            parts.append(f"\nm{current}:")
        parts.append(f"({note['string']},{note['fret']})")
    lines.append(" ".join(parts).replace("\n ", "\n").strip())
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search")
    ap.add_argument("--notes", type=int, metavar="SONGID")
    ap.add_argument("--track", type=int, default=None)
    a = ap.parse_args()
    if a.search:
        print(json.dumps(search(a.search), indent=2))
    if a.notes:
        tab = fetch_track_notes(a.notes, a.track)
        print(condense(tab))
