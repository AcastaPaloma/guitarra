import {PcmCapture} from './capture.js';

const $ = id => document.getElementById(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const terminal = new Set(['review_ready', 'keep', 'inspect', 'unavailable', 'stopped', 'fault', 'expired']);
const storageKey = 'guitarra.rehearsal.session.v1';
let config, arrangement = [], arrangementTitle = '', parentId = null, sourceId = null, sessionId = null;
let pathProfile = 'lift_first', pathReady = false, previewVersion = 0;
let snaRunning = false, snaPoller = null;
// Never silently fall back to the contact-only neutral-hub route.
const defaultProfile = () => config?.preferred_path_profile || 'lift_first';
let running = false, cancelled = false, current = null, recorder = null, playSubmitted = false;
let heartbeatTimer, meterTimer, audioUrl, historyAudioUrl, lastReview, sessionHistory;
let foreignActive = false, stoppingPromise = null;

const say = (text, error = false) => { $('status').textContent = text; $('status').className = error ? 'err' : ''; };

// Pace estimator: per-note and per-phase durations learned by EMA and kept in
// localStorage, so progress/ETA reflect THIS rig rather than fixed guesses.
const paceEstimates = (() => {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem('guitarra.pace.v1') || '{}'); } catch (_) {}
  const defaults = {note_s: 2.2, reviewing_s: 8, revising_s: 10};
  return {
    get: key => (typeof stored[key] === 'number' && stored[key] > 0 && stored[key] < 300 ? stored[key] : defaults[key]),
    update(key, seconds) {
      if (!(seconds > 0) || seconds > 300) return;
      stored[key] = Math.round((0.6 * this.get(key) + 0.4 * seconds) * 100) / 100;
      try { localStorage.setItem('guitarra.pace.v1', JSON.stringify(stored)); } catch (_) {}
    },
  };
})();
const noteTrack = {index: null, since: 0};
const phaseTrack = {phase: null, since: 0};

function phaseBar(phase) {
  // Waiting phases have no server-side progress; estimate against the typical
  // duration, asymptotically approaching (never claiming) completion.
  const now = performance.now() / 1000;
  if (phaseTrack.phase !== phase) { finishPhaseBar(); phaseTrack.phase = phase; phaseTrack.since = now; }
  const typical = paceEstimates.get(`${phase}_s`), elapsed = now - phaseTrack.since;
  $('fill').style.width = `${Math.min(1 - Math.exp(-elapsed / typical), 0.95) * 100}%`;
  $('count').textContent = `${phase} · ${elapsed.toFixed(0)}s elapsed · typically ≈${Math.round(typical)}s`;
}

function finishPhaseBar() {
  if (!phaseTrack.phase) return;
  paceEstimates.update(`${phaseTrack.phase}_s`, performance.now() / 1000 - phaseTrack.since);
  phaseTrack.phase = null;
}
const step = n => [1, 2, 3, 4].forEach(i => { $('st' + i).className = i === n ? 'on' : i < n ? 'done' : ''; });
const pitch = n => config?.keys.find(k => k.string === n.string && k.fret === n.fret)?.pitch || `s${n.string}f${n.fret}`;
const brief = text => (text || '').length > 220 ? text.slice(0, 217) + '…' : text || '';
const rating = text => (text || 'not assessed').replaceAll('_', ' ');
const textNode = (tag, text, className = '') => { const node = document.createElement(tag); node.textContent = text; node.className = className; return node; };

async function api(path, body, options = {}) {
  const headers = {'X-Session-Token': config?.session_token, ...options.headers};
  let payload;
  if (body !== undefined) {
    headers['Content-Type'] ||= 'application/json';
    payload = body instanceof Blob ? body : JSON.stringify(body);
  }
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers, body: payload,
    signal: AbortSignal.timeout(options.timeout || 12000), keepalive: !!options.keepalive});
  if (response.ok && options.binary) return response.blob();
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request rejected (${response.status})`);
  return data;
}

function rememberSession() {
  try { if (sessionId) localStorage.setItem(storageKey, sessionId); else localStorage.removeItem(storageKey); } catch (_) { /* private browser mode */ }
}

function controls() {
  const ready = config?.keys.length && config.key_present && config.audio_model_supported && pathReady;
  $('convert').disabled = running || foreignActive || snaRunning || !config?.keys.length || !config.key_present;
  $('find-tab').disabled = running || foreignActive || snaRunning;
  $('play-sna').disabled = running || foreignActive || snaRunning || !config?.extra_pose_playback_enabled;
  $('play').disabled = running || foreignActive || snaRunning || !ready || !arrangement.length;
  $('confirm-play').disabled = running || !pathReady || !$('media-consent').checked || !$('supervised').checked;
  $('stop').disabled = !running && !foreignActive && !snaRunning;
  $('force-stop').disabled = !running && !foreignActive && !snaRunning;
  $('park').disabled = running || foreignActive || snaRunning;
  for (const id of ['prompt', 'take-start', 'take-count', 'media-consent', 'supervised', 'session-select', 'change-song']) {
    $(id).disabled = running || foreignActive;
  }
  for (const id of ['take-start', 'take-count']) $(id).disabled = running || foreignActive || !!parentId || !!sourceId;
  $('apply').disabled = running || foreignActive || lastReview?.phase !== 'review_ready';
  $('apply').hidden = lastReview?.phase !== 'review_ready' || parentId === lastReview?.attempt_id;
  $('repeat').disabled = running || foreignActive;
  $('repeat').hidden = lastReview?.playback_outcome !== 'completed' || sourceId === lastReview?.attempt_id;
  document.querySelectorAll('.examples button, #take-history button').forEach(b => { b.disabled = running || foreignActive || b.dataset.unavailable === 'true'; });
  $('play').textContent = parentId || sourceId ? 'PLAY NEXT TAKE' : 'PLAY + LISTEN';
}

function switchTab(history) {
  $('play-view').hidden = history; $('history-view').hidden = !history;
  $('play-tab').className = history ? '' : 'active'; $('history-tab').className = history ? 'active' : '';
  $('play-tab').setAttribute('aria-selected', String(!history)); $('history-tab').setAttribute('aria-selected', String(history));
  if (history) $('recorded-audio').pause(); else $('history-audio').pause();
}
$('play-tab').onclick = () => switchTab(false);
$('history-tab').onclick = () => { switchTab(true); void refreshSessions(); };

// Longest take the server's execution/recording budget admits (default pauses).
// The server re-validates with the plan's actual pauses; this keeps the UI's
// defaults inside the budget instead of tripping a rejection.
function budgetFit() {
  const pause = 0.25, pace = config?.note_pace_s || 3.2, budget = config?.max_play_seconds || 150;
  return Math.max(1, Math.floor((budget + pause) / (pace + pause)));
}

function selection() {
  const start = Math.trunc(Math.max(0, Math.min(arrangement.length - 1, (Number($('take-start').value) || 1) - 1)));
  const count = Math.trunc(Math.max(1, Math.min(config?.max_take_notes || 4, budgetFit(),
    arrangement.length - start, Number($('take-count').value) || 1)));
  return {start, count, notes: arrangement.slice(start, start + count).map(n => ({...n}))};
}

function selectTake() {
  if (!arrangement.length) return;
  const {start, count, notes} = selection();
  $('take-start').value = start + 1; $('take-count').value = count;
  document.querySelectorAll('.note').forEach((node, index) => {
    node.className = 'note' + (index >= start && index < start + count ? ' selected' : '');
  });
  const capped = arrangement.length > budgetFit() && count >= budgetFit()
    ? ` · capped at ${budgetFit()} notes by the ${config?.max_play_seconds || 150}s recording budget — play the rest as another take` : '';
  const pauses = notes.slice(0, -1).map(n => n.pause_ms);
  const pauseText = pauses.length === 0 ? ' · one tap'
    : new Set(pauses).size === 1 ? ` · ${pauses[0]}ms pause after each lift`
    : ' · pauses after lift: ' + pauses.join('ms / ') + 'ms';
  $('selected').textContent = (parentId ? 'proposed · ' : '') + pathProfile.replace('_', '-') + pauseText + capped;
  void previewTrajectory(notes);
}

async function previewTrajectory(notes) {
  const version = ++previewVersion;
  pathReady = false; controls();
  $('path-status').textContent = 'Checking the whole lift-first route locally…';
  $('path-trace').textContent = '';
  try {
    const result = await api('/api/trajectory', {plan: {notes, path_profile: pathProfile}});
    if (version !== previewVersion) return;
    pathReady = result.executable === true;
    if (!pathReady) {
      $('path-status').textContent = 'Playback blocked: ' + (result.blockers || []).join(' ');
      return;
    }
    const trace = result.trajectory;
    $('path-status').textContent = 'Lift → reviewed hover travel → tap → lift. No neutral between notes. ' +
      `${trace.joint_travel_proxy_counts} counts travel proxy (not time or proof of clearance).`;
    // Single-arm trajectories carry exit_route; two-arm ones carry per-arm exit_routes.
    const exits = trace.exit_route
      ? trace.exit_route.join(' → ')
      : Object.entries(trace.exit_routes || {}).map(([arm, route]) => `${arm}: ${route.join(' → ')}`).join('  |  ');
    $('path-trace').textContent = trace.notes.map((note, i) =>
      `${i + 1}. ${(trace.assignments?.[i]?.arm) || note.arm || 'arm'} s${note.string}f${note.fret}: ` +
      note.stages.map(stage => `${stage.stage} ${stage.pose}`).join(' → ')).join('\n') +
      '\nFinal parking only: ' + exits;
  } catch (error) {
    if (version === previewVersion) $('path-status').textContent = 'Path check unavailable; no playback. ' + error.message;
  } finally {
    if (version === previewVersion) controls();
  }
}

function showArrangement(notes, title, profile) {
  arrangement = notes.map(n => ({arm: n.arm || 'tap_primary', string: n.string, fret: n.fret, pause_ms: n.pause_ms ?? 250}));
  pathProfile = profile || defaultProfile();
  arrangementTitle = title;
  $('title').textContent = title;
  $('notes').replaceChildren(...arrangement.map((n, i) => {
    const node = textNode('div', '', 'note');
    node.append(textNode('b', `s${n.string}·f${n.fret}`), textNode('span', `${i + 1}. ${pitch(n)} · ${n.arm}`));
    return node;
  }));
  $('take-start').max = arrangement.length; $('take-start').value = 1;
  $('take-count').value = Math.min(config.max_take_notes, budgetFit(), arrangement.length);
  $('plan').hidden = false; $('composer').hidden = true; $('now').hidden = true;
  selectTake(); controls();
}

$('change-song').onclick = () => { $('composer').hidden = !$('composer').hidden; };
for (const id of ['media-consent', 'supervised']) $(id).onchange = controls;
for (const id of ['take-start', 'take-count']) $(id).onchange = () => {
  if (!parentId && !sourceId) { sessionId = null; rememberSession(); selectTake(); }
};
document.querySelectorAll('.examples button').forEach(b => { b.onclick = () => { $('prompt').value = b.dataset.example; }; });

$('find-tab').onclick = async () => {
  const query = $('prompt').value.trim();
  if (!query) return say('Type the song name first, then find its tab.', true);
  $('find-tab').disabled = true; say('Searching Songsterr…');
  try {
    const data = await api('/api/tabs/search?pattern=' + encodeURIComponent(query.slice(0, 200)),
                           undefined, {timeout: 25000});
    const select = $('tab-results');
    select.replaceChildren(new Option('— no official tab (arrange from memory) —', ''));
    for (const song of data.results) select.add(new Option(`${song.artist} — ${song.title}`, String(song.songId)));
    select.hidden = false;
    if (data.results.length) { select.selectedIndex = 1; say('Official tab selected — MAKE NOTES will arrange from it.'); }
    else say('No Songsterr match; arrange from memory instead.', true);
  } catch (error) { say('Tab search: ' + error.message, true); }
  $('find-tab').disabled = false;
};

$('convert').onclick = async () => {
  const prompt = $('prompt').value.trim();
  if (!prompt) return say('Write a musical request first.', true);
  running = true; controls(); $('stop').disabled = true; step(1); say('Making a playable arrangement…');
  try {
    const songId = Number($('tab-results').value) || null;
    const request = {prompt, allow_inference: true};
    if (songId) request.songsterr_song_id = songId;
    const result = await api('/api/plan', request, {timeout: 90000});
    parentId = sourceId = sessionId = null; lastReview = null; sessionHistory = null; rememberSession();
    $('review').hidden = true; $('history-count').textContent = '0';
    showArrangement(result.notes, result.title, result.path_profile);
    if (result.transcription) {
      const t = result.transcription;
      const shift = t.transpose ? ` · transposed ${t.transpose > 0 ? '+' : ''}${t.transpose} semitones to fit the rig` : '';
      const rough = t.approximated ? ` · ${t.approximated} nearest-pitch` : '';
      const cut = t.dropped ? ` · ${t.dropped} out-of-range dropped` : '';
      say(`Official tab transcribed note-for-note: ${t.exact} exact of ${t.total}${rough}${cut}${shift}. Play + listen.`);
    } else say('Choose a short phrase, then play + listen.');
  } catch (error) { say(error.message, true); }
  finally { running = false; controls(); }
};

const consentKey = 'guitarra.standing-consent.v1';
function confirmTake() {
  if (running || foreignActive || !arrangement.length || !pathReady) return;
  let standing = false;
  try { standing = localStorage.getItem(consentKey) === 'granted'; } catch (_) { /* no storage */ }
  if (standing) {
    // Operator granted standing consent once; each take still sends explicit
    // consent flags to the server — this only skips re-ticking the boxes.
    $('media-consent').checked = true; $('supervised').checked = true;
    void runTake();
    return;
  }
  $('media-consent').checked = false; $('supervised').checked = false;
  $('confirm-description').textContent = parentId ? 'Try the proposed tuning shown below. One take, then review.' :
    sourceId ? 'Continue this session with the saved tuning. Inspect the arm before this new supervised set.' :
      'Play, record, review—then pause for your next choice.';
  controls(); $('consent-dialog').showModal();
}
$('play').onclick = confirmTake;
$('cancel-play').onclick = () => $('consent-dialog').close();
$('confirm-play').onclick = () => {
  if (!$('media-consent').checked || !$('supervised').checked) return;
  try { localStorage.setItem(consentKey, 'granted'); } catch (_) { /* session-only consent */ }
  $('consent-dialog').close(); void runTake();
};

function micOff() {
  clearInterval(meterTimer); meterTimer = null;
  $('recording').textContent = 'Mic off'; $('recording').className = '';
}

function ownAudio(blob, caption) {
  $('recorded-audio').pause();
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(blob);
  $('recorded-audio').src = audioUrl; $('recorded-audio').hidden = false;
  $('capture-info').textContent = caption;
}

function requestStop(reason = 'Stopped by operator.') {
  if (stoppingPromise) return stoppingPromise;
  cancelled = true;
  const record = current;
  stoppingPromise = (async () => {
    const stopRequest = record ? api('/api/stop', {attempt_id: record.attempt_id}, {keepalive: true}).catch(() => null) : Promise.resolve(null);
    const partial = recorder ? await recorder.partial().catch(() => null) : null;
    micOff();
    const stopped = await stopRequest;
    say(stopped || !record ? `${reason} No automatic rerun.` : `${reason} Stop unconfirmed; inspect the arm.`, true);
    if (partial && record && playSubmitted) {
      ownAudio(partial.blob, 'Incomplete recording · local inspection only, not sent to Baseten.');
      try {
        await api(`/api/attempts/${record.attempt_id}/partial-audio`, partial.blob, {headers: {
          'Content-Type': 'audio/wav', 'X-Capture-Metadata': JSON.stringify({capture_id: record.capture_id,
            sample_rate: partial.sample_rate, frames: partial.frames, incomplete: true}),
        }});
      } catch (_) { $('capture-info').textContent = 'Incomplete recording retained in this page; archive save unavailable.'; }
    }
  })();
  return stoppingPromise;
}
$('stop').onclick = () => {
  if (snaRunning) { void api('/api/sna-stop', {}).catch(() => {}); say('Stopping the riff after this tap…'); return; }
  if (foreignActive) stoppingPromise = null;
  void requestStop();
};

$('play-sna').onclick = async () => {
  if (!confirm('The arm will MOVE for real and play the Seven Nation Army riff on the ' +
               'low-E poses (2/3/5/7/10). Supervising with the body supported?')) return;
  try {
    const started = await api('/api/play-sna', {supervised_and_supported: true});
    snaRunning = true; controls();
    say(`Seven Nation Army — ${started.total} taps…`);
    snaPoller = setInterval(async () => {
      try {
        const s = (await api('/api/status')).sna;
        if (s.running) { if (s.index >= 0) say(`Seven Nation Army — tap ${s.index + 1} of ${s.total}`); return; }
        clearInterval(snaPoller); snaPoller = null; snaRunning = false; controls();
        say(s.error ? 'Riff error: ' + s.error : 'Seven Nation Army done — arm parked at rest (torque held).',
            !!s.error);
      } catch { /* keep polling */ }
    }, 400);
  } catch (error) { say('Riff: ' + error.message, true); }
};
$('force-stop').onclick = async () => {
  // No confirm dialog: this is the emergency control; a prompt would delay it.
  try {
    await api('/api/force-stop', {});
    say('FORCE STOP — arm frozen, then both arms revert to rest automatically.', true);
  } catch (error) { say('Force stop: ' + error.message, true); }
  if (running) void requestStop('Force stop.');
};
$('park').onclick = async () => {
  $('park').disabled = true; say('Resetting arms to rest…');
  try {
    const result = await api('/api/park', {}, {timeout: 45000});
    say('Reset: ' + Object.entries(result.arms)
      .map(([arm, ok]) => `${arm} ${ok === true ? 'at rest ✓' : ok}`).join(' · '));
  } catch (error) { say('Reset failed: ' + error.message, true); }
  $('park').disabled = false; controls();
};

function resetReview() {
  noteTrack.index = null; phaseTrack.phase = null;
  lastReview = null; $('review').hidden = false; $('proposal').hidden = true;
  $('apply').hidden = true; $('repeat').hidden = true;
  $('assessment-status').textContent = 'recording';
  for (const id of ['assessment-summary', 'capture-info', 'telemetry']) $(id).textContent = '';
  for (const id of ['observations', 'limitations', 'changes', 'inspection']) $(id).replaceChildren();
  $('recorded-audio').pause(); $('recorded-audio').removeAttribute('src'); $('recorded-audio').hidden = true;
  $('history-audio').pause(); $('history-audio').hidden = true;
  if (audioUrl) URL.revokeObjectURL(audioUrl); audioUrl = null;
}

function showProgress(record, offset) {
  $('now').hidden = false;
  const note = record.plan.notes[record.index];
  $('now-pitch').textContent = note ? `s${note.string} · f${note.fret}` : '…';
  $('now-note').textContent = note ? pitch(note) : 'preparing';
  if (record.phase === 'playing') {
    const now = performance.now() / 1000;
    if (noteTrack.index !== record.completed_notes) {
      if (noteTrack.index !== null && record.completed_notes > noteTrack.index)
        paceEstimates.update('note_s', (now - noteTrack.since) / (record.completed_notes - noteTrack.index));
      noteTrack.index = record.completed_notes; noteTrack.since = now;
    }
    const pace = paceEstimates.get('note_s');
    const withinNote = Math.min((now - noteTrack.since) / pace, 0.95);
    const left = Math.max(0, (record.total - record.completed_notes) * pace - (now - noteTrack.since));
    $('fill').style.width = `${(record.completed_notes + withinNote) / record.total * 100}%`;
    $('count').textContent = `${record.completed_notes}/${record.total} tap commands · ≈${Math.ceil(left)}s left`;
  } else if (record.phase === 'reviewing' || record.phase === 'revising') {
    phaseBar(record.phase);
  } else {
    $('count').textContent = `${record.completed_notes}/${record.total} tap commands`;
    $('fill').style.width = `${record.completed_notes / record.total * 100}%`;
  }
  document.querySelectorAll('.note').forEach((node, i) => {
    const index = i - offset;
    node.className = 'note' + (index >= 0 && index < record.total ? ' selected' : '') +
      (record.phase === 'playing' && index === record.index ? ' now' : index >= 0 && index < record.completed_notes ? ' done' : '');
  });
  $('telemetry').textContent = `${record.completed_notes}/${record.total} commands; outcome: ${record.playback_outcome}. ` +
    (record.playback_elapsed_s !== undefined ? `Server command duration ${record.playback_elapsed_s.toFixed(2)}s. ` : '') +
    'Encoder readiness is not proof of contact or an acoustic onset.';
}

function list(id, values) { $(id).replaceChildren(...values.map(text => textNode('li', text))); }
function changeText(change) {
  if (change.kind === 'timing') return `Note ${change.note_index + 1}: post-lift pause ${change.before_ms} → ${change.after_ms}ms`;
  if (change.kind === 'positioning') return `Note ${change.note_index + 1}: s${change.before.string}/f${change.before.fret} → s${change.after.string}/f${change.after.fret}, same pitch`;
  if (change.kind === 'path') return `Path staging ${change.before} → ${change.after}; same contact poses, shorter travels`;
  return `Order ${change.before.map(i => i + 1).join('–')} → ${change.after.map(i => i + 1).join('–')}. Changes the arrangement.`;
}

function showReview(record) {
  lastReview = record;
  $('attempt-label').textContent = String(record.take_number || record.attempt_number);
  const assessment = record.assessment;
  const measured = record.acoustic_metrics?.summary;
  const report = record.audio_model_report;
  const providerLine = report?.model ? `Audio reviewer: ${report.model}` +
    (report.model_fallback_from ? ` (fallback from ${report.model_fallback_from})` : '') : null;
  const heardLine = measured
    ? `estimated attack candidates matched: ${measured.notes_heard}/${measured.notes_planned}` +
      ` · pitch matches ${measured.pitch_matched}/${measured.pitch_assessed ?? 'unknown'} assessed` +
      (measured.mean_clarity_db != null ? ` · level ~${measured.mean_clarity_db}dB above estimated noise` : '')
    : null;
  $('assessment-status').textContent = [
    measured ? `attacks matched ${measured.notes_heard}/${measured.notes_planned}` : null,
    assessment && typeof assessment.score === 'number' ? `model opinion ${assessment.score}/10` : null,
    assessment ? `notes ${rating(assessment.notes_match)} · timing ${rating(assessment.timing_match)}` : 'review unavailable',
  ].filter(Boolean).join(' · ');
  $('assessment-summary').textContent = brief(assessment?.summary || record.error || 'No audio assessment received.');
  list('observations', [
    ...(providerLine ? [providerLine] : []),
    ...(report?.requests || []).filter(r => r.error).map(r => `${r.model}: ${r.error}`),
    ...(heardLine ? [heardLine] : []),
    ...(measured?.missed_indices?.length ? [`no unique attack detected for notes ${measured.missed_indices.map(i => i + 1).join(', ')}; not a missed-contact diagnosis`] : []),
    ...(measured?.unknown_indices?.length ? [`measurement unavailable for notes ${measured.unknown_indices.map(i => i + 1).join(', ')}`] : []),
    ...(assessment ? [assessment.summary, `Recording quality: ${assessment.recording_quality}`,
      ...assessment.observations, ...(assessment.suggestions || []).map(s => `try: ${s}`)] : []),
  ]);
  list('limitations', [...(record.acoustic_metrics?.limitations || []), ...(assessment?.limitations || [])]);
  if (record.revision) {
    $('proposal').hidden = false;
    $('rationale').textContent = brief(record.revision.rationale);
    list('inspection', [record.revision.rationale, ...record.revision.inspection_notes]);
    list('changes', record.revision.changes.map(changeText));
    $('apply').hidden = record.phase !== 'review_ready';
  }
  $('repeat').hidden = record.playback_outcome !== 'completed';
  if (record.phase === 'review_ready') { step(4); say('Next tuning ready. Review it, then try another take.'); }
  else if (record.phase === 'keep') { step(4); say('Keep this tuning. Your audio and review are saved.'); }
  else if (record.phase === 'inspect') { step(4); say(record.error || 'Inspect/listen before the next take.'); }
  else say(record.error || `Take ${record.phase}.`, true);
}

async function runTake() {
  if (running || !pathReady || !$('media-consent').checked || !$('supervised').checked) return;
  const selected = selection();
  const plan = {notes: selected.notes, path_profile: pathProfile};
  running = true; cancelled = false; current = null; stoppingPromise = null; playSubmitted = false;
  controls(); resetReview(); step(2); say('Preparing microphone…');
  try {
    recorder = new PcmCapture({maxSeconds: config.max_capture_seconds, onFailure: message => { void requestStop(message); }});
    recorder.prime(); // still in the confirmation click gesture; NO microphone opened yet
    current = await api('/api/attempts', {plan, title: arrangementTitle.slice(0, 80), session_id: sessionId,
      parent_attempt_id: parentId, source_attempt_id: sourceId,
      allow_audio_upload: true, allow_revision_inference: true, supervised_and_supported: true});
    sessionId = current.session_id || sessionId; rememberSession();
    if (cancelled) throw new Error('Cancelled before recording');
    $('attempt-label').textContent = String(current.take_number || current.attempt_number);
    const attemptId = current.attempt_id;
    let heartbeatPending = false;
    heartbeatTimer = setInterval(async () => {
      if (heartbeatPending) return;
      heartbeatPending = true;
      try {
        const lease = await api(`/api/attempts/${attemptId}/heartbeat`, {}, {timeout: 4000});
        if (current?.attempt_id !== attemptId || !running) return;
        if (!cancelled && (lease.stop_requested || ['stopped', 'fault', 'expired'].includes(lease.phase))) void requestStop('Server stopped this take.');
      } catch (_) {
        if (current?.attempt_id === attemptId && running && !cancelled) void requestStop('Server connection lost.');
      } finally { heartbeatPending = false; }
    }, 1000);
    say('Allow microphone access. Motion waits for audio samples.');
    await recorder.start();
    if (cancelled) throw new Error('Cancelled before Play');
    const dispatchFrame = await recorder.mark(), sampleRate = recorder.sampleRate;
    $('recording').className = 'live';
    meterTimer = setInterval(() => {
      if (recorder && !recorder.closed) $('recording').textContent = `● ${(recorder.frames / sampleRate).toFixed(1)}s`;
    }, 200);
    playSubmitted = true;
    await api('/api/play', {attempt_id: attemptId, capture_id: current.capture_id,
      sample_rate: sampleRate, dispatch_frame: dispatchFrame, capture_ready: true});
    say('Playing + listening…');
    while (true) {
      const record = await api(`/api/attempts/${attemptId}`);
      showProgress(record, selected.start);
      if (terminal.has(record.phase)) {
        finishPhaseBar();
        current = record;
        if (record.playback_outcome !== 'completed' && recorder) await requestStop(record.error || 'Take interrupted.');
        showReview(record); break;
      }
      if (record.stop_requested && !cancelled) await requestStop(record.error || 'Take stopped.');
      if (record.phase === 'awaiting_audio' && !cancelled) {
        const completionFrame = await recorder.mark();
        await sleep(350);
        if (cancelled) throw new Error('Capture cancelled');
        const capture = await recorder.finish(); recorder = null; micOff();
        if (cancelled) throw new Error('Capture cancelled');
        ownAudio(capture.blob, `${(capture.frames / sampleRate).toFixed(2)}s mono PCM16 · saved with this take. Browser/server alignment is approximate.`);
        step(3); say('Mic off. Reviewing this recording…');
        $('assessment-status').textContent = 'reviewing';
        await api(`/api/attempts/${attemptId}/audio`, capture.blob, {timeout: 25000, headers: {
          'Content-Type': 'audio/wav', 'X-Capture-Metadata': JSON.stringify({
            capture_id: current.capture_id, sample_rate: sampleRate, dispatch_frame: dispatchFrame,
            completion_frame: completionFrame, frames: capture.frames, elapsed_s: capture.elapsed_s, interrupted: false,
          }),
        }});
      } else if (record.phase === 'reviewing') { step(3); say('Audio model reviewing…'); }
      else if (record.phase === 'revising') { step(4); say('Refining with this take + previous tuning history…'); }
      await sleep(300);
    }
  } catch (error) {
    await requestStop(error.message);
    $('assessment-status').textContent = 'incomplete take';
    try { const active = (await api('/api/status')).active_attempt; if (active) { current = active; foreignActive = true; } }
    catch (_) { foreignActive = !!current; }
  } finally {
    if (recorder) await recorder.abort().catch(() => {});
    recorder = null; micOff(); clearInterval(heartbeatTimer); heartbeatTimer = null;
    $('media-consent').checked = false; $('supervised').checked = false;
    // Prepare the next choice automatically, NEVER the next physical run. Keep
    // the proposal's approval/expiry link; don't turn failed proposals into roots.
    if (current?.playback_outcome === 'completed' && terminal.has(current.phase)) {
      const proposed = current.phase === 'review_ready' && current.revision;
      parentId = proposed ? current.attempt_id : null;
      sourceId = proposed ? null : current.attempt_id;
      showArrangement(proposed ? current.revision.plan.notes : current.plan.notes, arrangementTitle,
                      proposed ? current.revision.plan.path_profile : current.plan.path_profile);
    }
    running = false;
    if (sessionId) await refreshHistory(sessionId).catch(() => {});
    await refreshSessions().catch(() => {}); controls();
  }
}

$('apply').onclick = () => {
  if (lastReview?.phase !== 'review_ready') return;
  parentId = lastReview.attempt_id; sourceId = null;
  showArrangement(lastReview.revision.plan.notes, arrangementTitle, lastReview.revision.plan.path_profile);
  say('Proposed tuning staged. Start only after inspection/confirmation.');
  confirmTake();
};
$('repeat').onclick = () => {
  if (lastReview?.playback_outcome !== 'completed') return;
  parentId = null; sourceId = lastReview.attempt_id;
  showArrangement(lastReview.plan.notes, arrangementTitle, lastReview.plan.path_profile); confirmTake();
};

async function refreshSessions() {
  const data = await api('/api/sessions');
  $('session-select').replaceChildren(...data.sessions.map(session => {
    const option = textNode('option', `${session.title} · ${session.take_count} takes`); option.value = session.session_id; return option;
  }));
  if (!data.sessions.length) $('session-select').append(textNode('option', 'No saved sessions'));
  if (sessionId) $('session-select').value = sessionId;
  return data.sessions;
}

async function refreshHistory(id) {
  sessionHistory = await api(`/api/sessions/${id}`);
  $('history-count').textContent = String(sessionHistory.takes.length);
  const tunings = new Set(sessionHistory.takes.map(t => t.tuning_id));
  const assessed = sessionHistory.takes.filter(t => t.assessment).length;
  $('history-summary').textContent = `${sessionHistory.title} · ${sessionHistory.takes.length} takes · ${tunings.size} tunings · ${assessed} audio reviews`;
  $('take-history').replaceChildren();
  for (const take of [...sessionHistory.takes].reverse()) {
    const row = textNode('div', '', 'take-row' + (take.preferred_by_operator ? ' preferred' : ''));
    const name = textNode('div', `Take ${take.take_number}`, 'take-name');
    const detail = textNode('div', take.assessment ? `notes ${rating(take.assessment.notes_match)} · timing ${rating(take.assessment.timing_match)}` : rating(take.phase));
    const time = Number.isFinite(take.command_elapsed_s) ? `${take.command_elapsed_s.toFixed(2)}s commands` : 'not completed';
    const delta = Number.isFinite(take.command_delta_from_first_s) ? ` · ${take.command_delta_from_first_s >= 0 ? '+' : ''}${take.command_delta_from_first_s.toFixed(2)}s vs first` : '';
    detail.append(textNode('p', `${time}${delta}${take.audio_incomplete ? ' · partial audio' : ''}`, 'take-meta'));
    const buttons = textNode('div', '', 'take-buttons');
    for (const [label, enabled, action] of [
      ['listen', take.audio_available, () => listenTake(take)],
      ['use tuning', take.can_load_tuning, () => useTuning(take)],
      [take.preferred_by_operator ? '★' : '☆', take.can_load_tuning, async () => {
        await api(`/api/sessions/${id}/preferred`, {attempt_id: take.attempt_id}); await refreshHistory(id);
      }],
    ]) {
      const button = textNode('button', label); button.dataset.unavailable = String(!enabled);
      button.title = label === '☆' || label === '★' ? 'Mark as your preferred take (human judgment)' : label;
      button.onclick = () => { void Promise.resolve(action()).catch(error => say(error.message, true)); };
      buttons.append(button);
    }
    row.append(name, detail, buttons); $('take-history').append(row);
  }
  const series = sessionHistory.takes.filter(t => t.same_phrase_and_calibration && Number.isFinite(t.command_elapsed_s)).slice(-16);
  $('trend').hidden = series.length < 2; $('trend-bars').replaceChildren();
  const max = Math.max(0.01, ...series.map(t => t.command_elapsed_s));
  for (const take of series) {
    const column = textNode('div', '', 'trend-column');
    const bar = textNode('div', '', 'trend-bar'); bar.style.height = `${take.command_elapsed_s / max * 65}%`;
    column.append(textNode('span', take.command_elapsed_s.toFixed(1), 'trend-value'), bar, textNode('span', String(take.take_number), 'trend-label'));
    $('trend-bars').append(column);
  }
  controls(); return sessionHistory;
}

function useTuning(take) {
  if (!take.can_load_tuning || running) return;
  sessionId = sessionHistory.session_id; parentId = null; sourceId = take.attempt_id; rememberSession();
  showArrangement(take.plan.notes, sessionHistory.title, take.plan.path_profile); switchTab(false);
  $('review').hidden = true; lastReview = null; controls();
  say(`Loaded Take ${take.take_number}'s tuning. No motion started; fresh admission/confirmation required.`);
}

async function listenTake(take) {
  if (running) return;
  const blob = await api(`/api/attempts/${take.attempt_id}/audio`, undefined, {binary: true});
  if (running) return; // a late history fetch cannot expose playback controls during capture
  $('history-audio').pause(); if (historyAudioUrl) URL.revokeObjectURL(historyAudioUrl);
  historyAudioUrl = URL.createObjectURL(blob); $('history-audio').src = historyAudioUrl;
  $('history-audio').hidden = false; $('history-detail').hidden = false;
  $('history-detail-title').textContent = `TAKE ${take.take_number}${take.audio_incomplete ? ' · INCOMPLETE, LOCAL ONLY' : ''}`;
  $('history-review').textContent = take.assessment?.summary || take.error || 'No audio assessment.';
  $('history-tuning').textContent = `Tuning ${take.tuning_id} · ${take.plan.notes.map(n => `s${n.string}f${n.fret} ${pitch(n)} (${n.pause_ms}ms pause)`).join(' → ')} · ${(take.plan.path_profile || 'rest_hub').replace('_', '-')}`;
}

$('session-select').onchange = async () => {
  if (!$('session-select').value) return;
  try { await refreshHistory($('session-select').value); }
  catch (error) { say(error.message, true); }
};

window.addEventListener('pagehide', () => {
  void recorder?.abort();
  if (running && current) void api('/api/stop', {attempt_id: current.attempt_id}, {keepalive: true}).catch(() => {});
});

(async function init() {
  try {
    config = await api('/api/bootstrap');
    $('availability').textContent = !config.keys.length ? 'No current keypoints · calibrate before playing.' :
      !config.paths_ready ? `${config.keys.length} contact keys · ${config.recorded_hover_count || 0} hover poses. Playback blocked: ${config.path_blocker || 'lift-first paths need review.'}` :
      !config.key_present ? 'Configure Baseten before playing.' : !config.audio_model_supported ? 'Audio evaluator is not configured.' :
      'Reviewed lift-first routes only · supervised takes · audio endpoint not yet live-verified.';
    $('arm-status').textContent = 'Primary: its recorded rows 1–5 only. Secondary: planned rows 7–11, strings 1–6 right-to-left; unavailable until calibrated/commissioned. No overlapping arm motion is enabled.';
    $('provider-status').textContent = `Planner: ${config.planner_model}. Audio: ${config.audio_model}. ${config.audio_endpoint_status}. ` +
      [config.warning, config.path_blocker, ...(config.keypoint_warnings || [])].filter(Boolean).join(' ');
    if (config.active_attempt) {
      current = config.active_attempt; foreignActive = true;
      $('plan').hidden = false;
      say('Another page owns a take. Stop it and reload after completion; this page will not resume it.', true);
    }
    const sessions = await refreshSessions();
    let remembered;
    try { remembered = localStorage.getItem(storageKey); } catch (_) { /* no persistent browser storage */ }
    if (sessions.length) {
      sessionId = sessions.some(s => s.session_id === remembered) ? remembered : sessions[0].session_id;
      $('session-select').value = sessionId;
      const history = await refreshHistory(sessionId);
      const loadable = t => t.can_load_tuning && t.tuning_current !== false;
      const saved = history.takes.find(t => t.preferred_by_operator && loadable(t)) || [...history.takes].reverse().find(loadable);
      if (saved && !foreignActive) useTuning(saved); // load symbolic settings only, NEVER resume motion/capture
      else if (!foreignActive && history.takes.some(t => t.can_load_tuning)) {
        say('Calibration changed since your saved tunings — MAKE NOTES to replan (nothing is broken).');
      }
    }
    controls();
  } catch (error) { say(`Console unavailable: ${error.message}`, true); }
})();
