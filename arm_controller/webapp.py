"""Guitarra web console — single-arm, tap-only, REAL hardware.

Flow: prompt -> Baseten converts it to a note plan (shown first) -> operator
hits Play -> the arm taps the keys for real. No plucking exists on this rig.

The serial port is opened per play and released after, so the keyframe GUI
(app.py) can be used between plays — but not DURING one (port is exclusive).

Run:  uv run --no-project --with fastapi --with "uvicorn" --with pyserial \
          python webapp.py --port 8787
Needs BASETEN_API_KEY in guitar/.env (or repo .env) for planning.
"""
import json
import re
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                  # fret.py / app.py
sys.path.insert(0, str(HERE.parent / "guitar"))  # model.baseten

from fret import FretArm, load_grid, STRING_NOTES, MAX_FRET  # noqa: E402
from model.baseten import BasetenClient, BasetenError, load_env  # noqa: E402

MAX_NOTES = 64
GAP_S = 0.25

# Fretted pitch table: tap-only rig — open strings can't sound, so the whole
# instrument is exactly the 18 recorded keys.
_SEMIS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _pitch(string: int, fret: int) -> str:
    name = STRING_NOTES[string]
    idx = _SEMIS.index(name[:-1]) + int(name[-1]) * 12 + fret
    return f"{_SEMIS[idx % 12]}{idx // 12}"


PLAYABLE = {(s, f): _pitch(s, f) for s in range(1, 7) for f in range(1, MAX_FRET + 1)}

PLAN_SYSTEM = f"""You arrange music for a one-armed robot guitarist that can ONLY
tap-sound these 18 keys (string, fret) -> pitch:
{json.dumps({f"s{s}f{f}": p for (s, f), p in sorted(PLAYABLE.items())})}
Strings: 1 = high E ... 6 = low E. Frets 1-3 only. Open strings CANNOT sound
(tap-only, no plucking). Notes are sequential taps — no chords, no sustain.

Given the user's request (a song name, a melody description, or a pasted song
sheet / tab), produce the best playable arrangement: transpose or substitute
the nearest available pitch when the original note isn't in the 18-key set.
At most {MAX_NOTES} notes. Reply with ONLY a JSON object, no prose:
{{"title": "<short name>", "notes": [{{"string": 1-6, "fret": 1-3}}, ...]}}"""


class PlanReq(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class NoteReq(BaseModel):
    string: int = Field(ge=1, le=6)
    fret: int = Field(ge=1, le=MAX_FRET)


class PlayReq(BaseModel):
    notes: list[NoteReq] = Field(min_length=1, max_length=MAX_NOTES)
    gap_s: float = Field(default=GAP_S, ge=0.0, le=2.0)


state = {"playing": False, "index": -1, "total": 0, "error": None, "stop": False}
_state_lock = threading.Lock()


def _play_thread(notes, gap_s):
    import time
    try:
        arm = FretArm()
    except Exception as e:
        with _state_lock:
            state.update(playing=False, error=f"arm unavailable: {e}")
        return
    try:
        for i, (s, f) in enumerate(notes):
            with _state_lock:
                if state["stop"]:
                    break
                state["index"] = i
            arm.tap_key(s, f)
            if gap_s:
                time.sleep(gap_s)
        arm.rest()
    except Exception as e:
        with _state_lock:
            state["error"] = str(e)
    finally:
        arm.close()  # torque stays ON so the arm holds position
        with _state_lock:
            state.update(playing=False, index=-1)


app = FastAPI()


@app.get("/api/bootstrap")
def bootstrap():
    cells, _, _ = load_grid()
    return {"keys": [{"string": s, "fret": f, "pitch": PLAYABLE[(s, f)]}
                     for (s, f) in sorted(cells)],
            "max_notes": MAX_NOTES, "hardware": "real", "plucking": False}


@app.post("/api/plan")
def plan(req: PlanReq):
    try:
        client = BasetenClient(effort="low", timeout_s=120)
        resp = client.chat(
            [{"role": "system", "content": PLAN_SYSTEM},
             {"role": "user", "content": req.prompt}],
            response_format={"type": "json_object"})
        raw = resp["choices"][0]["message"]["content"]
    except BasetenError as e:
        raise HTTPException(502, f"Baseten: {e}")
    except (KeyError, IndexError, TypeError):
        raise HTTPException(502, "Baseten returned an unexpected response shape")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise HTTPException(502, "model reply contained no JSON object")
    try:
        data = json.loads(m.group(0))
        notes = [(int(n["string"]), int(n["fret"])) for n in data["notes"]][:MAX_NOTES]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, "model JSON did not match the expected schema")
    bad = [n for n in notes if n not in PLAYABLE]
    if bad or not notes:
        raise HTTPException(502, f"model planned unplayable keys: {bad or 'none at all'}")
    return {"title": str(data.get("title", "untitled"))[:80], "model": client.model,
            "notes": [{"string": s, "fret": f, "pitch": PLAYABLE[(s, f)]} for s, f in notes]}


@app.post("/api/play")
def play(req: PlayReq):
    with _state_lock:
        if state["playing"]:
            raise HTTPException(409, "already playing — stop it first")
        state.update(playing=True, index=-1, total=len(req.notes), error=None, stop=False)
    notes = [(n.string, n.fret) for n in req.notes]
    threading.Thread(target=_play_thread, args=(notes, req.gap_s), daemon=True).start()
    return {"started": True, "total": len(notes)}


@app.post("/api/stop")
def stop():
    with _state_lock:
        state["stop"] = True
    return {"stopping": True}


@app.get("/api/status")
def status():
    with _state_lock:
        return dict(state)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guitarra</title>
<style>
  /* exactly three colors, flat */
  :root { --paper:#F5F1E8; --ink:#1B1B1B; --accent:#D95D39; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--paper); color:var(--ink);
         font-family:"SF Mono",ui-monospace,Menlo,monospace;
         min-height:100vh; display:flex; flex-direction:column;
         align-items:center; padding:9vh 20px 40px; }
  h1 { font-size:28px; letter-spacing:6px; }
  .sub { margin-top:6px; font-size:12px; letter-spacing:2px; }
  main { width:100%; max-width:620px; margin-top:42px; }
  textarea { width:100%; height:110px; resize:vertical; padding:14px;
             font:inherit; font-size:15px; color:var(--ink);
             background:var(--paper); border:2px solid var(--ink); outline:none; }
  textarea:focus { border-color:var(--accent); }
  .examples { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
  .examples button { font:inherit; font-size:11px; padding:6px 10px; cursor:pointer;
                     background:var(--paper); color:var(--ink); border:1px solid var(--ink); }
  .examples button:hover { border-color:var(--accent); color:var(--accent); }
  .actions { margin-top:18px; display:flex; gap:10px; justify-content:center; }
  .btn { font:inherit; font-size:14px; letter-spacing:2px; padding:12px 26px;
         cursor:pointer; border:2px solid var(--ink); background:var(--paper); color:var(--ink); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:var(--paper); }
  .btn:disabled { opacity:.4; cursor:default; }
  #status { margin-top:16px; text-align:center; font-size:12px; min-height:16px; }
  #status.err { color:var(--accent); }
  #plan { margin-top:34px; display:none; }
  #plan h2 { font-size:15px; letter-spacing:2px; border-bottom:2px solid var(--ink);
             padding-bottom:8px; }
  .notes { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
  .note { border:1px solid var(--ink); padding:7px 9px; font-size:12px; text-align:center; }
  .note b { display:block; font-size:14px; }
  .note.now { background:var(--accent); border-color:var(--accent); color:var(--paper); }
  .note.done { border-color:var(--accent); color:var(--accent); }
</style></head><body>
<h1>GUITARRA</h1>
<div class="sub">one arm &middot; eighteen keys &middot; tap only</div>
<main>
  <textarea id="prompt" placeholder="tell it what to play&hellip; a song, a melody, or paste a song sheet"></textarea>
  <div class="examples">
    <button data-x="Play Hot Cross Buns">hot cross buns</button>
    <button data-x="Play the hook of Seven Nation Army">seven nation army</button>
    <button data-x="Play an ascending then descending scale across all six strings">up-down scale</button>
    <button data-x="Song sheet:&#10;e|--1--3--1--|&#10;B|--------3--|&#10;G|--2--------|">paste a tab</button>
  </div>
  <div class="actions">
    <button class="btn primary" id="convert">CONVERT TO NOTES</button>
  </div>
  <div id="status"></div>
  <section id="plan">
    <h2 id="title"></h2>
    <div class="notes" id="notes"></div>
    <div class="actions">
      <button class="btn primary" id="play">TAP IT OUT</button>
      <button class="btn" id="stop" disabled>STOP</button>
    </div>
  </section>
</main>
<script>
const $ = id => document.getElementById(id);
let planNotes = [], poller = null;
document.querySelectorAll('.examples button').forEach(b =>
  b.onclick = () => { $('prompt').value = b.dataset.x.replace(/&#10;/g,'\\n'); });
const say = (msg, err) => { const s = $('status'); s.textContent = msg; s.className = err ? 'err' : ''; };

$('convert').onclick = async () => {
  const prompt = $('prompt').value.trim();
  if (!prompt) return say('write something first', true);
  $('convert').disabled = true; say('asking the model\\u2026');
  try {
    const r = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'},
                                        body: JSON.stringify({prompt})});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    planNotes = d.notes;
    $('title').textContent = d.title + '  \\u00b7  ' + d.notes.length + ' notes';
    $('notes').innerHTML = d.notes.map(n =>
      `<div class="note"><b>${n.pitch}</b>s${n.string} f${n.fret}</div>`).join('');
    $('plan').style.display = 'block'; say('review the notes, then tap it out');
  } catch (e) { say('plan failed: ' + e.message, true); }
  $('convert').disabled = false;
};

$('play').onclick = async () => {
  $('play').disabled = true; $('stop').disabled = false; say('playing\\u2026');
  try {
    const r = await fetch('/api/play', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({notes: planNotes.map(n => ({string:n.string, fret:n.fret}))})});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    poller = setInterval(poll, 300);
  } catch (e) { say('play failed: ' + e.message, true); $('play').disabled = false; $('stop').disabled = true; }
};

$('stop').onclick = () => fetch('/api/stop', {method:'POST'});

async function poll() {
  const s = await (await fetch('/api/status')).json();
  document.querySelectorAll('.note').forEach((el, i) => {
    el.className = 'note' + (i === s.index ? ' now' : (s.index > i || !s.playing) && el.className.includes('now') ? ' done' : el.className.includes('done') ? ' done' : ''));
  });
  if (s.index >= 0) say(`tapping ${s.index + 1} / ${s.total}`);
  if (!s.playing) {
    clearInterval(poller); poller = null;
    $('play').disabled = false; $('stop').disabled = true;
    say(s.error ? 'error: ' + s.error : 'done \\u2014 arm back at rest');
    if (s.error) $('status').className = 'err';
  }
}
</script></body></html>"""


@app.get("/")
def index():
    return HTMLResponse(PAGE)


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    load_env()
    print(f"Guitarra tap console: http://127.0.0.1:{a.port} — REAL ARM", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, access_log=False, log_level="warning")
