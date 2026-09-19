'use strict';

const $ = (id) => document.getElementById(id);
const labels = {
  'single-note': 'Single note', 'repeat-and-change': 'Repeat & change string',
  'unsupported-target': 'Unsupported target', 'fret-failure': 'Injected fret failure', custom: 'Custom workflow'
};
const ui = { config: null, activeId: null, selectedId: null, job: null, events: [], cursor: 0,
  polling: false, submitting: false, lastHistory: 0 };

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
function badge(element, text, tone = 'neutral') {
  element.textContent = text;
  element.className = `badge ${tone}`;
}
function error(message) {
  $('error-banner').textContent = String(message);
  $('error-banner').hidden = false;
}
function clearError() { $('error-banner').hidden = true; }
function pretty(value) { return JSON.stringify(value, null, 2); }
function number(value) { return Number.isFinite(Number(value)) ? Number(value) : 0; }
function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
async function api(path, options = {}) {
  const headers = {};
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['X-Session-Token'] = ui.config?.session_token || '';
  }
  const response = await fetch(path, { method: options.method || 'GET', headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body), cache: 'no-store' });
  let data;
  try { data = await response.json(); } catch { throw new Error('The local server returned an unreadable response.'); }
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join('\n') : detail || `Request failed (${response.status})`);
  }
  return data;
}

function addNote(string = 5, fret = 5) {
  if ($('note-rows').children.length >= 12) return;
  const row = node('div', null, 'note-row');
  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Guitar string');
  for (const [value, label] of [[6, '6 · low E'], [5, '5 · A'], [4, '4 · D'], [3, '3 · G'], [2, '2 · B'], [1, '1 · high E']]) {
    const option = node('option', label); option.value = value; select.append(option);
  }
  select.value = String(string);
  const input = document.createElement('input');
  Object.assign(input, { type: 'number', min: '0', max: '24', step: '1', value: String(fret), required: true });
  input.setAttribute('aria-label', 'Fret number');
  const remove = node('button', '×'); remove.type = 'button'; remove.setAttribute('aria-label', 'Remove note');
  remove.addEventListener('click', () => { row.remove(); });
  row.append(select, input, remove); $('note-rows').append(row);
}
function renderMode() {
  const custom = $('scenario').value === 'custom';
  $('custom-editor').hidden = !custom;
  $('preset-notes').replaceChildren();
  if (custom) {
    if (!$('note-rows').children.length) { addNote(5, 5); addNote(5, 5); addNote(3, 3); }
    $('scenario-help').textContent = 'Describe your direction below; this explicit sequence is the independent scoring target.';
  } else {
    const scenario = ui.config.scenarios.find((s) => s.id === $('scenario').value);
    for (const note of scenario.task.requested_notes) $('preset-notes').append(node('span', `s${note.string} · f${note.fret}`, 'note-chip'));
    $('scenario-help').textContent = scenario.expected_outcome === 'blocked'
      ? 'Expected outcome: stop blocked without unsafe follow-up actions.'
      : 'Expected outcome: symbolic notes in order, then final fingertip release.';
  }
}
function updateControls() {
  const activeSelected = ui.selectedId && ui.selectedId === ui.activeId && ui.job?.status !== 'finished';
  const status = ui.job?.status;
  $('start-run').disabled = !ui.config?.key_configured || Boolean(ui.activeId) || !$('allow-inference').checked || ui.submitting;
  $('pause-run').disabled = !activeSelected || status !== 'running';
  $('resume-run').disabled = !activeSelected || !['paused', 'pausing'].includes(status);
  $('stop-run').disabled = !activeSelected || status === 'stopping';
  $('active-run-link').hidden = !ui.activeId || ui.activeId === ui.selectedId;
}

async function startRun(event) {
  event.preventDefault();
  if ($('start-run').disabled) return;
  clearError(); ui.submitting = true; updateControls();
  const custom = $('scenario').value === 'custom';
  const body = {
    scenario: $('scenario').value, prompt: $('prompt').value,
    notes: custom ? [...$('note-rows').children].map((row) => ({ string: Number(row.querySelector('select').value), fret: Number(row.querySelector('input').value) })) : [],
    inject_fret_failure: custom && $('inject-fault').checked,
    allow_inference: $('allow-inference').checked,
    effort: $('effort').value, max_calls: Number($('max-calls').value),
    seconds: Number($('seconds').value), max_output_tokens: Number($('max-tokens').value)
  };
  try {
    const job = await api('/api/runs', { method: 'POST', body });
    ui.activeId = job.id;
    $('allow-inference').checked = false; // approval is per run, not a sticky auto-start setting
    await selectRun(job.id);
    await refreshHistory();
  } catch (exc) { error(exc.message); }
  finally { ui.submitting = false; updateControls(); }
}
async function control(action) {
  if (!ui.selectedId || ui.selectedId !== ui.activeId) return;
  try {
    clearError();
    ui.job = await api(`/api/runs/${ui.selectedId}/${action}`, { method: 'POST', body: {} });
    renderRun();
  } catch (exc) { error(exc.message); }
}

async function refreshHistory() {
  const history = await api('/api/runs');
  ui.activeId = history.active_id;
  $('history-list').replaceChildren();
  for (const run of history.runs) {
    const button = node('button', null, `history-row${run.id === ui.selectedId ? ' selected' : ''}`);
    button.type = 'button'; button.dataset.runId = run.id;
    const info = node('span');
    info.append(node('span', labels[run.scenario] || run.scenario, 'title'), node('span', formatDate(run.created_at), 'when'));
    const result = node('span');
    const ongoing = ['running', 'paused', 'pausing', 'stopping'].includes(run.status);
    badge(result, ongoing ? run.status : run.result, ongoing ? 'blue' : (['passed', 'failed', 'incomplete'].includes(run.result) ? run.result : 'neutral'));
    button.append(info, result);
    button.addEventListener('click', () => { void selectRun(run.id); });
    $('history-list').append(button);
  }
  if (!history.runs.length) $('history-list').append(node('p', 'No runs yet. Start a workflow above.', 'muted small'));
  ui.lastHistory = Date.now();
  if (!ui.selectedId && history.runs.length) await selectRun(ui.activeId || history.runs[0].id);
  updateControls();
}
async function selectRun(id) {
  if (ui.selectedId !== id) {
    ui.selectedId = id; ui.cursor = 0; ui.events = []; ui.job = null;
    $('timeline').replaceChildren(node('p', 'Loading recorded events…', 'muted small'));
    $('results-panel').hidden = true;
    for (const row of $('history-list').children) row.classList.toggle('selected', row.dataset.runId === id);
    clearError();
  }
  await poll();
}

function addDetails(parent, title, data) {
  const details = node('details');
  details.append(node('summary', title), node('pre', pretty(data)));
  parent.append(details);
}
function renderEvent(event) {
  const rejected = event.type === 'tool' && !event.result.ok;
  const article = node('article', null, `event ${event.type}${rejected ? ' rejected' : ''}`);
  const heading = node('div', null, 'event-header');
  if (event.type === 'start') {
    heading.append(node('strong', 'Fake session initialized'), node('span', 'NO DEVICES'));
    article.append(heading, node('div', 'Task, tool capabilities and initial state sent to the planner.', 'event-text'));
    addDetails(article, 'View task and starting state', event.opening);
  } else if (event.type === 'model') {
    heading.append(node('strong', `Model decision ${event.request}`), node('span', `${number(event.wall_seconds).toFixed(2)}s API`));
    article.append(heading);
    if (event.text) article.append(node('div', event.text, 'event-text'));
    for (const call of event.calls || []) article.append(node('div', `${call.name}(${JSON.stringify(call.args)})`, 'call-line'));
    if (!(event.calls || []).length) article.append(node('div', 'No tool call returned.', 'event-text'));
    addDetails(article, 'Response metadata', { stop: event.stop, usage: event.usage });
  } else if (event.type === 'tool') {
    heading.append(node('strong', `${rejected ? 'Rejected' : 'Accepted'} · ${event.tool}`), node('span', `#${event.index + 1} · ${number(event.after.virtual_s).toFixed(2)}s virtual`));
    article.append(heading, node('div', `${event.tool}(${JSON.stringify(event.args)})`, 'call-line'));
    if (rejected) article.append(node('div', `${event.result.error_code}: ${event.result.error}`, 'event-text'));
    if (event.result.played_event) {
      const note = event.result.played_event;
      article.append(node('div', `Mock pick event: string ${note.string}, fret ${note.fret}. No sound measured.`, 'event-text'));
    }
    addDetails(article, 'Result and before / after state', { result: event.result, before: event.before, after: event.after });
  } else if (event.type === 'summary') {
    heading.append(node('strong', `Run ${event.report.evaluation.status}`), node('span', event.report.stop_reason));
    article.append(heading, node('div', 'Independent workflow evaluation saved with the full event log.', 'event-text'));
  } else {
    heading.append(node('strong', event.type === 'provider_error' ? 'Provider request failed' : 'Run error'));
    article.append(heading, node('div', event.error || pretty(event), 'event-text'));
  }
  return article;
}
function appendEvents(events) {
  if (!events.length) return;
  const timeline = $('timeline');
  const follow = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 70 || !ui.events.length;
  if (!ui.events.length) timeline.replaceChildren();
  for (const event of events) { ui.events.push(event); timeline.append(renderEvent(event)); }
  if (follow) timeline.scrollTop = timeline.scrollHeight;
}
function renderRun() {
  const job = ui.job;
  if (!job) { updateControls(); return; }
  const report = job.report;
  const state = job.state || report?.final_state;
  const result = report?.evaluation?.status || (report?.evaluation?.passed ? 'passed' : null);
  $('run-title').textContent = labels[job.scenario] || job.scenario;
  badge($('run-status'), job.status === 'finished' ? result || 'Finished' : job.status,
    job.status === 'finished' && ['passed', 'failed', 'incomplete'].includes(result) ? result : 'blue');
  const calls = report?.evaluation?.tool_calls ?? ui.events.filter((e) => e.type === 'tool').length;
  const usage = report?.usage || ui.events.filter((e) => e.type === 'model').reduce((out, e) => ({ input: out.input + number(e.usage?.input), output: out.output + number(e.usage?.output) }), { input: 0, output: 0 });
  $('metric-tools').textContent = String(calls);
  $('metric-notes').textContent = String(state?.plucks_so_far ?? 0);
  $('metric-time').textContent = number(state?.virtual_s).toFixed(2);
  $('metric-tokens').textContent = (number(usage.input) + number(usage.output)).toLocaleString();
  $('fret-state').textContent = state?.fret?.at || 'Waiting for fake session';
  $('fret-detail').textContent = state?.fret ? `${state.fret.contact} · ${state.fret.target ? `string ${state.fret.target[0]}, fret ${state.fret.target[1]}` : 'no held target'}` : 'Existing motion code and saved pose map';
  $('fret-card').classList.toggle('fault', Boolean(state?.fault));
  $('pick-state').textContent = state?.pick?.at || 'Waiting for fake session';
  $('event-count').textContent = `${ui.events.length} recorded events`;
  $('log-path').textContent = job.directory;
  $('download-links').replaceChildren();
  for (const name of ['events.jsonl', 'summary.json', 'tools.json']) {
    if (name === 'summary.json' && !report) continue;
    const link = node('a', `↓ ${name}`); link.href = `/api/runs/${encodeURIComponent(job.id)}/files/${name}`;
    link.download = name; $('download-links').append(link);
  }
  $('results-panel').hidden = !report;
  if (report) {
    badge($('result-status'), result || 'incomplete', ['passed', 'failed', 'incomplete'].includes(result) ? result : 'neutral');
    $('result-summary').replaceChildren();
    const reason = report.model_finish?.reason || report.error || report.stop_reason || 'Report available.';
    $('result-summary').append(node('p', reason));
    if (report.operator_prompt) addDetails($('result-summary'), 'Operator prompt used for this run', report.operator_prompt);
    $('result-summary').append(node('p', `Stop: ${report.stop_reason || 'unknown'} · Wall: ${number(report.wall_seconds).toFixed(1)}s · Virtual: ${number(report.virtual_seconds).toFixed(2)}s`, 'small muted'));
    $('check-list').replaceChildren();
    for (const [name, passed] of Object.entries(report.evaluation?.checks || {})) {
      const incomplete = result === 'incomplete';
      $('check-list').append(node('div', `${passed ? '✓' : incomplete ? '—' : '×'} ${name.replaceAll('_', ' ')}`, `check-item ${passed ? 'good' : incomplete ? '' : 'bad'}`));
    }
  }
  updateControls();
}
async function poll() {
  if (ui.polling || !ui.config) return;
  ui.polling = true;
  try {
    const id = ui.selectedId;
    if (id) {
      const [job, updates] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/events?after=${ui.cursor}`)]);
      if (ui.selectedId === id) {
        const justFinished = job.status === 'finished' && ui.job?.status !== 'finished';
        ui.job = job; appendEvents(updates.events); ui.cursor = updates.next_cursor;
        if (job.status === 'finished' && ui.activeId === id) ui.activeId = null;
        if (justFinished) ui.lastHistory = 0;
        renderRun();
      }
    }
    if (Date.now() - ui.lastHistory > 4000) await refreshHistory();
  } catch (exc) { error(`Dashboard: ${exc.message}`); }
  finally { ui.polling = false; }
}

async function boot() {
  try {
    ui.config = await api('/api/bootstrap');
    $('model-name').textContent = ui.config.model;
    badge($('key-status'), ui.config.key_configured ? 'Baseten key configured' : 'Baseten key missing', ui.config.key_configured ? 'teal' : 'amber');
    $('scenario').replaceChildren();
    for (const scenario of ui.config.scenarios) {
      const option = node('option', labels[scenario.id] || scenario.id); option.value = scenario.id; $('scenario').append(option);
    }
    const custom = node('option', 'Custom prompt + notes'); custom.value = 'custom'; $('scenario').append(custom);
    $('scenario').value = 'repeat-and-change';
    $('tool-count').textContent = `(${ui.config.tools.length})`;
    $('tool-schemas').textContent = pretty(ui.config.tools);
    $('hardware-blockers').replaceChildren(...ui.config.hardware_blockers.map((text) => node('li', text)));
    renderMode();
    await refreshHistory();
    await poll();
    setInterval(() => { void poll(); }, 1000);
  } catch (exc) { error(`Cannot load the local console: ${exc.message}`); }
}
$('run-form').addEventListener('submit', startRun);
$('scenario').addEventListener('change', renderMode);
$('add-note').addEventListener('click', () => addNote());
$('allow-inference').addEventListener('change', updateControls);
$('pause-run').addEventListener('click', () => { void control('pause'); });
$('resume-run').addEventListener('click', () => { void control('resume'); });
$('stop-run').addEventListener('click', () => { void control('stop'); });
$('refresh-history').addEventListener('click', () => { refreshHistory().catch((exc) => error(exc.message)); });
$('active-run-link').addEventListener('click', () => { if (ui.activeId) void selectRun(ui.activeId); });
void boot();
