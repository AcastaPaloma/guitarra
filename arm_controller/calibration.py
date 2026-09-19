"""Browser calibration for the tap arm (IDs 7-11) — mounted by webapp.py.

Replaces the tkinter keyframe GUI for pose recording. Workflow:
  1) CONNECT (opens the serial port — exclusive, so playback is blocked)
  2) torque OFF -> pose the arm by hand while watching live counts/degrees/XYZ
     (or torque ON and jog joints from the page)
  3) SET REFERENCE once, in the measured pose kinematics.py documents
  4) capture keypoints: each saves raw counts + relative degrees + tip XYZ
  5) DISCONNECT to release the port for playback

Keypoints keep the keyframes_arm2.json schema fret.py plays back
(name/time/positions) and add "degrees" and "xyz_cm" alongside — playback
code ignores the extra keys.
"""
import json
import shutil
import threading
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import kinematics
from app import (BAUD, GOTO_ACC, GOTO_SPEED, JOINT_NAMES, KEYFRAMES_PATH,
                 MOTOR_IDS, PORT, FeetechBus)

router = APIRouter(prefix="/api/cal")

# Shared with the rehearsal manager: reservation and calibration connection are
# admitted atomically. RLock permits the injected play guard to inspect ownership.
ownership_lock = _lock = threading.RLock()
_bus = None
_torque_on = False

# webapp.py injects "is the tap player running?" to avoid a circular import
_play_guard = lambda: False


def set_play_guard(fn):
    global _play_guard
    _play_guard = fn


def session_active():
    return _bus is not None


def _require_bus():
    if _bus is None:
        raise HTTPException(409, "not connected — hit CONNECT first")
    return _bus


def _read_all(bus):
    counts = {}
    for sid in MOTOR_IDS:
        pos = bus.read_pos(sid)
        if pos is not None:
            counts[sid] = pos
    return counts


def _load_keypoints():
    if KEYFRAMES_PATH.exists():
        return json.loads(KEYFRAMES_PATH.read_text())
    return []


def _save_keypoints(kps):
    with _lock:
        if _play_guard():
            raise HTTPException(409, "a rehearsal owns this calibration snapshot — finish/stop it first")
        KEYFRAMES_PATH.write_text(json.dumps(kps, indent=2))


class GotoReq(BaseModel):
    id: int
    pos: int = Field(ge=0, le=4095)


class JogReq(BaseModel):
    id: int
    delta: int = Field(ge=-200, le=200)


class TorqueReq(BaseModel):
    on: bool


class NameReq(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.post("/connect")
def connect():
    global _bus, _torque_on
    with _lock:
        if _play_guard():
            raise HTTPException(409, "the arm is playing — wait for it to finish")
        if _bus is None:
            try:
                _bus = FeetechBus(PORT, BAUD)
            except Exception as e:
                raise HTTPException(502, f"could not open {PORT}: {e}")
        alive = [sid for sid in MOTOR_IDS if _bus.ping(sid)]
        _torque_on = bool(alive) and all(_bus.read_torque(sid) for sid in alive)
        return {"connected": True, "port": PORT, "alive": alive,
                "missing": [s for s in MOTOR_IDS if s not in alive],
                "torque": _torque_on}


@router.post("/disconnect")
def disconnect():
    global _bus
    with _lock:
        if _bus is not None:
            _bus.close()  # torque state is left as-is; servos hold if ON
            _bus = None
    return {"connected": False}


@router.get("/status")
def status():
    with _lock:
        if _bus is None:
            return {"connected": False}
        counts = _read_all(_bus)
        cal = kinematics.load_calibration()
        return {
            "connected": True, "port": PORT, "torque": _torque_on,
            "counts": {str(k): v for k, v in counts.items()},
            "names": {str(k): v for k, v in JOINT_NAMES.items()},
            "degrees": kinematics.joint_degrees(counts, cal),
            "xyz": kinematics.tip_xyz(counts, cal),
            "reference": None if cal is None else
                {"counts": cal.get("ref_counts"), "captured": cal.get("captured"),
                 "signs": cal.get("signs"), "geometry": cal.get("geometry")},
        }


@router.post("/torque")
def torque(req: TorqueReq):
    global _torque_on
    with _lock:
        bus = _require_bus()
        for sid in MOTOR_IDS:
            bus.set_torque(sid, req.on)
        _torque_on = req.on
    return {"torque": _torque_on}


def _command(bus, sid, pos):
    global _torque_on
    if sid not in MOTOR_IDS:
        raise HTTPException(400, f"motor {sid} is not commandable (IDs: {MOTOR_IDS})")
    if not _torque_on:  # taking control by wire implies torque, like the GUI
        for m in MOTOR_IDS:
            bus.set_torque(m, True)
        _torque_on = True
    bus.goto(sid, pos, speed=GOTO_SPEED, acc=GOTO_ACC)


@router.post("/goto")
def goto(req: GotoReq):
    with _lock:
        _command(_require_bus(), req.id, req.pos)
    return {"id": req.id, "pos": req.pos}


@router.post("/jog")
def jog(req: JogReq):
    with _lock:
        bus = _require_bus()
        pos = bus.read_pos(req.id)
        if pos is None:
            raise HTTPException(502, f"motor {req.id} did not answer")
        target = max(0, min(4095, pos + req.delta))
        _command(bus, req.id, target)
    return {"id": req.id, "pos": target}


@router.post("/reference")
def set_reference():
    """Capture the CURRENT pose as the kinematic zero (see kinematics.py)."""
    with _lock:
        bus = _require_bus()
        counts = _read_all(bus)
        if len(counts) < len(MOTOR_IDS):
            missing = [s for s in MOTOR_IDS if s not in counts]
            raise HTTPException(502, f"motors {missing} did not answer — cannot capture")
        cal = kinematics.save_reference(counts)
    return {"reference": cal["ref_counts"], "captured": cal["captured"]}


@router.get("/keypoints")
def keypoints():
    return {"keypoints": _load_keypoints()}


@router.post("/keypoints")
def save_keypoint(req: NameReq):
    with _lock:
        bus = _require_bus()
        counts = _read_all(bus)
        if len(counts) < len(MOTOR_IDS):
            missing = [s for s in MOTOR_IDS if s not in counts]
            raise HTTPException(502, f"motors {missing} did not answer — not saving")
    cal = kinematics.load_calibration()
    entry = {"name": req.name.strip(),
             "time": datetime.now().isoformat(timespec="seconds"),
             "positions": {str(k): v for k, v in counts.items()},
             "degrees": kinematics.joint_degrees(counts, cal),
             "xyz_cm": kinematics.tip_xyz(counts, cal)}
    kps = [k for k in _load_keypoints() if k["name"] != entry["name"]]  # re-record replaces
    kps.append(entry)
    _save_keypoints(kps)
    return entry


@router.post("/keypoints/goto")
def goto_keypoint(req: NameReq):
    kp = next((k for k in _load_keypoints() if k["name"] == req.name), None)
    if kp is None:
        raise HTTPException(404, f"no keypoint named '{req.name}'")
    with _lock:
        bus = _require_bus()
        for sid_str, pos in kp["positions"].items():
            _command(bus, int(sid_str), int(pos))
    return {"moving_to": req.name}


@router.post("/keypoints/delete")
def delete_keypoint(req: NameReq):
    kps = _load_keypoints()
    kept = [k for k in kps if k["name"] != req.name]
    if len(kept) == len(kps):
        raise HTTPException(404, f"no keypoint named '{req.name}'")
    _save_keypoints(kept)
    return {"deleted": req.name, "remaining": len(kept)}


@router.post("/keypoints/clear")
def clear_keypoints():
    kps = _load_keypoints()
    if kps:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = KEYFRAMES_PATH.with_name(f"{KEYFRAMES_PATH.stem}.backup-{stamp}.json")
        shutil.copy(KEYFRAMES_PATH, backup)
    _save_keypoints([])
    return {"cleared": len(kps)}


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guitarra — calibrate</title>
<style>
  :root { --paper:#F5F1E8; --ink:#1B1B1B; --accent:#D95D39; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--paper); color:var(--ink);
         font-family:"SF Mono",ui-monospace,Menlo,monospace;
         min-height:100vh; display:flex; flex-direction:column;
         align-items:center; padding:6vh 20px 40px; }
  h1 { font-size:24px; letter-spacing:5px; }
  .sub { margin-top:6px; font-size:12px; letter-spacing:2px; }
  a { color:var(--accent); }
  main { width:100%; max-width:760px; margin-top:28px; }
  section { border:2px solid var(--ink); padding:14px; margin-top:18px; }
  h2 { font-size:13px; letter-spacing:2px; margin-bottom:10px; }
  .btn { font:inherit; font-size:12px; letter-spacing:1px; padding:8px 14px;
         cursor:pointer; border:2px solid var(--ink); background:var(--paper); color:var(--ink); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:var(--paper); }
  .btn.mini { padding:4px 8px; border-width:1px; font-size:11px; }
  .btn:disabled { opacity:.4; cursor:default; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th, td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--ink); }
  th { letter-spacing:1px; font-size:11px; }
  td.num { font-variant-numeric:tabular-nums; }
  input[type=range] { width:150px; accent-color:var(--accent); vertical-align:middle; }
  input[type=text] { font:inherit; font-size:12px; padding:7px; width:180px;
                     background:var(--paper); border:2px solid var(--ink); outline:none; }
  input[type=text]:focus { border-color:var(--accent); }
  #xyz { display:flex; gap:26px; flex-wrap:wrap; font-size:13px; }
  #xyz b { font-size:22px; display:block; color:var(--accent); }
  #msg { margin-top:12px; font-size:12px; min-height:15px; }
  #msg.err { color:var(--accent); }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .note { font-size:11px; opacity:.75; margin-top:8px; line-height:1.5; }
  .kp-x { font-size:11px; opacity:.8; }
</style></head><body>
<h1>CALIBRATE</h1>
<div class="sub">arm 7&ndash;11 &middot; counts + degrees + xyz &middot; <a href="/">back to console</a></div>
<main>
  <section>
    <div class="row">
      <button class="btn primary" id="connect">CONNECT</button>
      <button class="btn" id="torque" disabled>TORQUE ON</button>
      <span id="conn" style="font-size:12px">disconnected</span>
    </div>
    <div class="note">torque OFF = pose the arm by hand, readouts follow live.
      touching a slider or jog takes control (torque comes on).</div>
  </section>

  <section>
    <h2>JOINTS</h2>
    <table id="joints"><thead>
      <tr><th>motor</th><th>raw</th><th>deg from ref</th><th>slide</th><th>jog</th></tr>
    </thead><tbody></tbody></table>
  </section>

  <section>
    <h2>FINGERTIP &middot; world frame, cm (origin: base axis at ground)</h2>
    <div id="xyz">
      <div>x (toward guitar)<b id="x">&mdash;</b></div>
      <div>y (yaw sweep)<b id="y">&mdash;</b></div>
      <div>z (height)<b id="z">&mdash;</b></div>
      <div>above strings<b id="above">&mdash;</b></div>
    </div>
    <div class="note" id="refnote">no reference captured yet &mdash; degrees/xyz appear after SET REFERENCE.</div>
    <div class="row" style="margin-top:10px">
      <button class="btn" id="setref" disabled>SET REFERENCE FROM CURRENT POSE</button>
    </div>
    <div class="note">reference pose = link1 straight up in line with the base column,
      link2 at 90&deg; horizontal toward the guitar, link3 hanging straight down.
      capture it once; re-capture only if the rig is re-assembled.</div>
  </section>

  <section>
    <h2>KEYPOINTS</h2>
    <div class="row">
      <input type="text" id="kpname" placeholder="pose-r1-c1 &hellip; or rest">
      <button class="btn primary" id="capture" disabled>CAPTURE</button>
      <button class="btn" id="clear">CLEAR ALL</button>
    </div>
    <div class="note">grid names fret.py plays: pose-r{fret}-c{string} (string 1 = high E)
      plus one 'rest'. re-capturing a name replaces it.</div>
    <table id="kps" style="margin-top:10px"><thead>
      <tr><th>name</th><th>xyz cm</th><th>deg 7..11</th><th></th></tr>
    </thead><tbody></tbody></table>
  </section>
  <div id="msg"></div>
</main>
<script>
const $ = id => document.getElementById(id);
let connected = false, torque = false, poller = null, sliding = null;
const session = fetch('/api/bootstrap').then(r => r.json());
const say = (m, err) => { $('msg').textContent = m; $('msg').className = err ? 'err' : ''; };
const api = async (path, body) => {
  const {session_token} = await session;
  const r = await fetch('/api/cal' + path, body === undefined ? {} :
    {method:'POST', headers:{'Content-Type':'application/json', 'X-Session-Token':session_token},
     body: JSON.stringify(body)});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.status);
  return d;
};

function joinRows(names) {
  const tb = $('joints').querySelector('tbody');
  if (tb.children.length) return;
  for (const id of Object.keys(names)) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${id} ${names[id]}</td>
      <td class="num" id="raw${id}">&mdash;</td>
      <td class="num" id="deg${id}">&mdash;</td>
      <td><input type="range" min="0" max="4095" id="sl${id}"></td>
      <td>
        <button class="btn mini" data-id="${id}" data-d="-25">-25</button>
        <button class="btn mini" data-id="${id}" data-d="-2">-2</button>
        <button class="btn mini" data-id="${id}" data-d="2">+2</button>
        <button class="btn mini" data-id="${id}" data-d="25">+25</button>
      </td>`;
    tb.appendChild(tr);
    const sl = tr.querySelector('input');
    sl.oninput = () => { sliding = id; };
    sl.onchange = async () => {
      try { await api('/goto', {id:+id, pos:+sl.value}); } catch(e) { say(e.message, true); }
      sliding = null;
    };
  }
  tb.onclick = async e => {
    const b = e.target.closest('button[data-id]');
    if (!b) return;
    try { await api('/jog', {id:+b.dataset.id, delta:+b.dataset.d}); }
    catch(e2) { say(e2.message, true); }
  };
}

async function poll() {
  let s;
  try { s = await api('/status'); } catch(e) { return; }
  if (!s.connected) return setConnected(false);
  joinRows(s.names);
  torque = s.torque;
  $('torque').textContent = torque ? 'TORQUE OFF' : 'TORQUE ON';
  for (const [id, v] of Object.entries(s.counts || {})) {
    $('raw'+id).textContent = v;
    if (sliding !== id) $('sl'+id).value = v;
    $('deg'+id).textContent = s.degrees ? (s.degrees[id] ?? '—') + '°' : '—';
  }
  if (s.xyz) {
    $('x').textContent = s.xyz.x_cm; $('y').textContent = s.xyz.y_cm;
    $('z').textContent = s.xyz.z_cm; $('above').textContent = s.xyz.above_strings_cm;
  }
  $('refnote').textContent = s.reference && s.reference.counts
    ? 'reference captured ' + s.reference.captured
    : 'no reference captured yet — degrees/xyz appear after SET REFERENCE.';
}

function setConnected(on) {
  connected = on;
  $('connect').textContent = on ? 'DISCONNECT' : 'CONNECT';
  $('conn').textContent = on ? 'connected' : 'disconnected';
  for (const id of ['torque','setref','capture']) $(id).disabled = !on;
  if (on && !poller) poller = setInterval(poll, 350);
  if (!on && poller) { clearInterval(poller); poller = null; }
}

$('connect').onclick = async () => {
  try {
    if (!connected) {
      const d = await api('/connect', {});
      say(d.missing.length ? 'connected, MISSING motors ' + d.missing.join(', ')
                           : 'connected, all motors OK', d.missing.length > 0);
      setConnected(true); poll();
    } else {
      await api('/disconnect', {});
      setConnected(false); say('port released — playback is possible again');
    }
  } catch (e) { say(e.message, true); }
};

$('torque').onclick = async () => {
  try { await api('/torque', {on: !torque}); poll(); } catch (e) { say(e.message, true); }
};

$('setref').onclick = async () => {
  if (!confirm('Capture CURRENT pose as the kinematic reference?\\n' +
               'The arm must be in the documented reference pose.')) return;
  try { const d = await api('/reference', {}); say('reference captured ' + d.captured); poll(); }
  catch (e) { say(e.message, true); }
};

$('capture').onclick = async () => {
  const name = $('kpname').value.trim();
  if (!name) return say('name the keypoint first', true);
  try {
    const d = await api('/keypoints', {name});
    say('saved ' + d.name + (d.xyz_cm ? ' @ (' + d.xyz_cm.x_cm + ', ' + d.xyz_cm.y_cm +
        ', ' + d.xyz_cm.z_cm + ') cm' : ' (no reference — counts only)'));
    $('kpname').value = ''; loadKps();
  } catch (e) { say(e.message, true); }
};

$('clear').onclick = async () => {
  if (!confirm('Back up and CLEAR all keypoints?')) return;
  try { const d = await api('/keypoints/clear', {}); say('cleared ' + d.cleared + ' keypoints (backup written)'); loadKps(); }
  catch (e) { say(e.message, true); }
};

async function loadKps() {
  const d = await api('/keypoints');
  const tb = $('kps').querySelector('tbody');
  tb.innerHTML = d.keypoints.map(k => {
    const xyz = k.xyz_cm ? `(${k.xyz_cm.x_cm}, ${k.xyz_cm.y_cm}, ${k.xyz_cm.z_cm})` : '—';
    const deg = k.degrees ? Object.keys(k.degrees).sort((a,b)=>a-b).map(i => k.degrees[i]).join(' / ') : '—';
    return `<tr><td>${k.name}</td><td class="num kp-x">${xyz}</td><td class="num kp-x">${deg}</td>
      <td><button class="btn mini" data-go="${k.name}">go</button>
          <button class="btn mini" data-del="${k.name}">del</button></td></tr>`;
  }).join('');
}
$('kps').onclick = async e => {
  const go = e.target.closest('button[data-go]'), del = e.target.closest('button[data-del]');
  try {
    if (go) { await api('/keypoints/goto', {name: go.dataset.go}); say('moving to ' + go.dataset.go); }
    if (del && confirm('Delete ' + del.dataset.del + '?')) {
      await api('/keypoints/delete', {name: del.dataset.del}); loadKps();
    }
  } catch (e2) { say(e2.message, true); }
};

loadKps();
api('/status').then(s => { if (s.connected) { setConnected(true); poll(); } });
</script></body></html>"""


@router.get("/page", include_in_schema=False)
def page():  # mounted at /calibrate by webapp.py as well
    return HTMLResponse(PAGE)
