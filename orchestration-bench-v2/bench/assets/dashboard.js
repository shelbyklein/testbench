/* Orchestration Bench operator dashboard.
 *
 * Reads the operator API described in contracts/CONTRACTS.md §11 and renders it without
 * inventing anything: an unknown is drawn as the word "unknown", a partial aggregate says how
 * many values are missing, provenance is always visible, and no view ranks the methods.
 */
'use strict';

const TOKEN = window.BENCH_TOKEN;
const DIMENSIONS = ['correctness', 'completeness', 'maintainability', 'ux', 'evidence_quality'];
const DIMENSION_LABELS = {
  correctness: 'Correctness', completeness: 'Completeness', maintainability: 'Maintainability',
  ux: 'User experience', evidence_quality: 'Evidence quality',
};
const PHASES = ['first', 'repaired'];
const TABS = ['runs', 'trace', 'compare'];

const state = {
  data: null,
  comparison: null,
  traces: new Map(),
  run: null,
  phase: 'first',
  tab: 'runs',
  configMethod: null,
};

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let toastTimer = null;
function toast(message, isError) {
  const node = $('#toast');
  node.textContent = message;
  node.className = 'toast' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 7000);
}

async function api(route, body) {
  const options = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Bench-Token': TOKEN },
        body: JSON.stringify(body) }
    : {};
  const response = await fetch('/api/' + route, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || ('HTTP ' + response.status));
  return payload;
}

/* ------------------------------------------------------------ value rendering */

const UNKNOWN = '<span class="unknown" title="No value was recorded. This is not zero.">unknown</span>';

function known(value) {
  return value !== null && value !== undefined && value !== '';
}

function number(value, digits) {
  if (!known(value) || typeof value !== 'number' || !isFinite(value)) return UNKNOWN;
  return esc(digits === undefined ? String(value) : value.toFixed(digits));
}

function provenance(entry) {
  if (!entry || !entry.provenance) return '';
  const source = entry.source ? ('Source: ' + entry.source) : 'No source was recorded.';
  return '<span class="prov prov-' + esc(entry.provenance) + '" tabindex="0" data-source="'
    + esc(source) + '" title="' + esc(source) + '">' + esc(entry.provenance) + '</span>'
    + '<span class="vh"> (provenance: ' + esc(entry.provenance) + '; ' + esc(source) + ')</span>';
}

/** A measurement object: {value, unit, provenance, source}. */
function measurement(entry, digits) {
  if (!entry) return UNKNOWN;
  const body = entry.value === null || entry.value === undefined
    ? UNKNOWN
    : number(entry.value, digits) + (entry.unit ? ' <span class="small">' + esc(entry.unit) + '</span>' : '');
  return body + provenance(entry);
}

/** An aggregate: {value, complete, unknownCount, unit, source}. */
function aggregate(entry, digits) {
  if (!entry) return UNKNOWN;
  const missing = entry.unknownCount || 0;
  if (entry.value === null || entry.value === undefined) {
    // Nothing is known at all. Saying "unknown" once is the whole truth; the count of
    // missing inputs belongs in the tooltip, not next to the word.
    return '<span class="unknown" title="No value was recorded. This is not zero.'
      + (missing ? ' ' + missing + ' contributing value(s) were unknown.' : '') + '">unknown</span>';
  }
  let html = number(entry.value, digits)
    + (entry.unit ? ' <span class="small">' + esc(entry.unit) + '</span>' : '');
  if (entry.complete === false) {
    html += ' <span class="partial">partial (' + missing + ' unknown)</span>';
  }
  if (entry.source) {
    html += '<span class="prov prov-measured" tabindex="0" data-source="Source: ' + esc(entry.source)
      + '" title="Source: ' + esc(entry.source) + '">aggregate</span><span class="vh"> (aggregated from ' + esc(entry.source) + ')</span>';
  }
  return html;
}

function pill(text, kind) {
  return '<span class="pill ' + (kind || '') + '">' + esc(text) + '</span>';
}

function gatePill(text) {
  if (!text) return pill('Not captured');
  if (text === 'Meets acceptance') return pill(text, 'ok');
  if (/stale|failed|defect|error|not met/i.test(text)) return pill(text, 'bad');
  if (/pending|incomplete/i.test(text)) return pill(text, 'wait');
  return pill(text);
}

function statusPill(status) {
  const kind = { completed: 'ok', failed: 'bad', missing: 'bad', canceled: 'bad',
    skipped: 'wait', running: 'wait' }[status] || '';
  const text = status === 'missing' ? 'MISSING — never observed' : status;
  return pill(text, kind);
}

function shellQuote(value) {
  return "'" + String(value).replaceAll("'", "'\\''") + "'";
}

function command(args) {
  return 'python3 ' + shellQuote(state.data.controllerPath)
    + ' --experiment ' + shellQuote(state.data.experimentPath) + ' ' + args;
}

/* ------------------------------------------------------------ data access */

const phase = () => state.phase;
const currentRun = () => (state.data.runs || []).find((run) => run.id === state.run) || null;
const phaseOf = (run) => ((run && run.phases) || {})[phase()] || {};

/* ------------------------------------------------------------ top of page */

function renderHeader() {
  const data = state.data;
  const definition = data.definition || {};
  $('#synthetic-banner').classList.toggle('hidden', !data.synthetic);
  $('#readonly-banner').classList.toggle('hidden', !data.readOnly);
  $('#integrity-banner').classList.toggle('hidden', data.integrityOK !== false);
  document.title = (data.synthetic ? 'SYNTHETIC · ' : '') + 'Orchestration Bench — operator';

  $('#exp-title').textContent = definition.title || 'Experiment';
  $('#exp-question').textContent = definition.question || '';
  $('#brand-sub').textContent = (definition.id || 'experiment')
    + ' · ' + (data.runs || []).length + ' runs'
    + (data.synthetic ? ' · SYNTHETIC' : '');
  $('#location').textContent = data.experimentPath || '';

  const readiness = data.readiness;
  if (!readiness) {
    $('#readiness').innerHTML = '<p class="small">Readiness is not computed for a v1 experiment.</p>';
  } else if (readiness.ready) {
    $('#readiness').innerHTML = '<div class="notice ok">Ready to start. Nothing is blocking a run.</div>'
      + '<p class="small">' + esc(readiness.note || '') + '</p>';
  } else {
    $('#readiness').innerHTML = '<div class="notice bad"><strong>Not ready to start. '
      + readiness.blockers.length + ' blocker' + (readiness.blockers.length === 1 ? '' : 's') + ':</strong></div>'
      + '<ul>' + readiness.blockers.map((b) => '<li>' + esc(b) + '</li>').join('') + '</ul>'
      + '<p class="small">' + esc(readiness.note || '') + '</p>';
  }

  const integrity = data.integrityOK === undefined
    ? '<p class="small">Integrity is not tracked for a v1 experiment.</p>'
    : (data.integrityOK
      ? '<p>' + pill('Integrity verified', 'ok') + ' Method, scenario and seed files still hash to what was frozen at preparation.</p>'
      : '<p>' + pill('Integrity broken', 'bad') + ' Bench files changed after preparation.</p>');

  const schedule = data.schedule || {};
  const balance = schedule.balance || {};
  const positions = Object.keys(balance).length
    ? Array.from(new Set(Object.values(balance).flatMap((row) => Object.keys(row)))).sort()
    : [];
  const balanceTable = positions.length ? '<div class="tbl"><table><caption>How often each method '
    + 'occupied each schedule position.</caption><thead><tr><th scope="col">Method</th>'
    + positions.map((p) => '<th scope="col">Position ' + esc(p) + '</th>').join('')
    + '</tr></thead><tbody>'
    + Object.keys(balance).sort().map((methodId) => '<tr><th scope="row">' + esc(methodId) + '</th>'
      + positions.map((p) => '<td>' + esc(balance[methodId][p] ?? 0) + '</td>').join('') + '</tr>').join('')
    + '</tbody></table></div>' : '';

  $('#schedule').innerHTML = '<details><summary>Run order and position balance</summary>'
    + '<dl class="kv"><dt>Algorithm</dt><dd class="mono">' + esc(schedule.algorithm || 'not recorded') + '</dd>'
    + '<dt>Seed</dt><dd class="mono">' + esc(schedule.seed ?? 'not recorded') + '</dd>'
    + '<dt>Counterbalanced</dt><dd>' + (schedule.complete
      ? pill('complete', 'ok') + ' every method occupied every position equally'
      : pill('incomplete', 'wait') + ' positions are not fully counterbalanced') + '</dd></dl>'
    + (schedule.imbalance && schedule.imbalance.length
      ? '<p class="small">Imbalance:</p><ul class="small">'
        + schedule.imbalance.map((item) => '<li>' + esc(typeof item === 'string' ? item : JSON.stringify(item)) + '</li>').join('')
        + '</ul>' : '')
    + balanceTable + '</details>';
  $('#integrity-status').innerHTML = integrity;
}

/* ------------------------------------------------------------ runs */

function renderRunPicker() {
  const picker = $('#run-picker');
  picker.innerHTML = (state.data.runs || []).map((run) => '<option value="' + esc(run.id) + '"'
    + (run.id === state.run ? ' selected' : '') + '>' + esc(run.id) + ' · ' + esc(run.methodLabel || run.method)
    + '</option>').join('');
}

function renderRunGroups() {
  const runs = state.data.runs || [];
  const groups = new Map();
  runs.forEach((run) => {
    const key = run.pairKey || 'unpaired';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(run);
  });
  $('#run-groups').innerHTML = Array.from(groups.entries()).map(([key, members]) => {
    const rows = members.map((run) => {
      const details = phaseOf(run);
      const evaluation = details.evaluation;
      return '<tr' + (run.id === state.run ? ' class="selected"' : '') + '>'
        + '<td data-label="Run"><span class="mono">' + esc(run.id) + '</span>'
        + '<div class="small">position ' + esc(run.position) + ' of block ' + esc(run.block) + '</div></td>'
        + '<td data-label="Method"><strong>' + esc(run.methodLabel || run.method) + '</strong></td>'
        + '<td data-label="Scenario">' + esc(run.scenario) + ' <span class="small">v'
        + esc(run.scenarioVersion) + ' · repeat ' + esc(run.repeat) + '</span></td>'
        + '<td data-label="Submission">' + esc(details.capturedAt ? 'Captured' : (run.status === 'prepared' ? 'Not started' : 'Not captured')) + '</td>'
        + '<td data-label="Checks">' + (evaluation ? esc(evaluation.passed + ' / ' + evaluation.total) : UNKNOWN) + '</td>'
        + '<td data-label="Trace">' + (run.hasTrace ? pill('imported', 'info') : pill('no trace', 'wait')) + '</td>'
        + '<td data-label="Acceptance">' + gatePill(details.gate) + '</td>'
        + '<td data-label=""><button type="button" class="small" data-run="' + esc(run.id) + '">Inspect '
        + '<span class="vh">run ' + esc(run.id) + '</span></button></td></tr>';
    }).join('');
    return '<section class="panel"><h3 class="mono">' + esc(key) + '</h3>'
      + '<p class="small">' + members.length + ' comparable run' + (members.length === 1 ? '' : 's')
      + ' in this group.</p><div class="tbl"><table class="stacky"><thead><tr>'
      + ['Run', 'Method', 'Scenario', 'Submission', 'Checks', 'Trace', 'Acceptance', 'Action']
        .map((h) => '<th scope="col">' + h + '</th>').join('')
      + '</tr></thead><tbody>' + rows + '</tbody></table></div></section>';
  }).join('');
}

function evaluationBlock(details) {
  const evaluation = details.evaluation;
  if (!evaluation) {
    return '<div class="panel"><h3>Independent acceptance checks</h3>'
      + '<p class="small">Not evaluated yet. Capture a submission first — an unevaluated run is not a failure and not a pass.</p></div>';
  }
  const checks = (evaluation.checks || []).map((check) => '<li>'
    + pill(check.status === 'pass' ? 'pass' : 'fail', check.status === 'pass' ? 'ok' : 'bad')
    + ' <span class="mono">' + esc(check.id) + '</span> ' + esc(check.description || '')
    + (check.evidence ? '<details><summary>Evidence</summary><pre>' + esc(check.evidence) + '</pre></details>' : '')
    + '</li>').join('');
  const publicChecks = (evaluation.publicChecks || []).map((item) => '<li>'
    + pill(item.exitCode === 0 ? 'passed' : 'failed or errored', item.exitCode === 0 ? 'ok' : 'bad')
    + ' <span class="mono">' + esc((item.argv || []).join(' ')) + '</span></li>').join('');
  return '<div class="panel"><h3>Independent acceptance checks</h3>'
    + '<p>' + esc(evaluation.passed + ' of ' + evaluation.total) + ' checks passed · '
    + (evaluation.allPassed ? pill('all passed', 'ok') : pill('not all passed', 'bad'))
    + ' · evaluator ' + esc(evaluation.graderVersion || 'version unrecorded') + '</p>'
    + (evaluation.integrityNote ? '<div class="notice bad">' + esc(evaluation.integrityNote) + '</div>' : '')
    + (details.taskIntact === false ? '<div class="notice bad">The task brief was changed or removed in the workspace.</div>' : '')
    + '<ul class="stack">' + checks + '</ul>'
    + (publicChecks ? '<h4>Baseline smoke checks</h4><ul class="stack">' + publicChecks + '</ul>' : '');
}

function metricsForm(run, details) {
  const metrics = (run.metrics || {})[phase()] || {};
  const fields = [
    ['costUSD', 'Total cost (USD)', 'any'],
    ['humanMinutes', 'Your active minutes', 'any'],
    ['interventions', 'Times you intervened', '1'],
    ['inputTokens', 'Input tokens', '1'],
    ['outputTokens', 'Output tokens', '1'],
  ];
  const elapsed = details.elapsedMinutes === undefined || details.elapsedMinutes === null
    ? '<p>Elapsed time ' + UNKNOWN + '</p>'
    : '<p>' + number(details.elapsedMinutes, 1) + ' of ' + esc(details.allowanceMinutes)
      + ' minutes used ' + (details.overBudget ? pill('over the allowance', 'bad') : pill('within allowance', 'ok')) + '</p>';
  return '<div class="panel"><h3>Effort you can account for</h3>'
    + '<p class="small">Leave a box empty when you do not know the value. Empty stays unknown; it never becomes zero.</p>'
    + elapsed
    + '<div class="cols">' + fields.map(([key, label, step]) => '<div class="field">'
      + '<label for="metric-' + key + '">' + esc(label) + '</label>'
      + '<input type="number" min="0" step="' + step + '" id="metric-' + key + '" value="'
      + esc(metrics[key] ?? '') + '"></div>').join('') + '</div>'
    + '<div class="field"><label for="metric-source">Where these numbers came from</label>'
    + '<input id="metric-source" value="' + esc(metrics.source || '') + '" placeholder="Provider usage export, stopwatch, session log…"></div>'
    + '<div class="field"><label for="metric-notes">Intervention notes</label>'
    + '<textarea id="metric-notes">' + esc(metrics.notes || '') + '</textarea></div>'
    + '<button type="button" class="primary" id="metrics-save">Save effort</button></div>';
}

function defectRows(defects) {
  return (defects || []).map((defect, index) => '<fieldset data-defect="' + index + '">'
    + '<legend>Defect ' + (index + 1) + '</legend>'
    + '<div class="field"><label for="defect-severity-' + index + '">Severity</label>'
    + '<select id="defect-severity-' + index + '">'
    + ['critical', 'major', 'minor'].map((s) => '<option value="' + s + '"'
      + (defect.severity === s ? ' selected' : '') + '>' + s + '</option>').join('')
    + '</select></div>'
    + '<div class="field"><label for="defect-evidence-' + index + '">How to reproduce it, and what it costs the user</label>'
    + '<textarea id="defect-evidence-' + index + '">' + esc(defect.evidence || '') + '</textarea></div>'
    + '<button type="button" class="small" data-remove-defect="' + index + '">Remove this defect</button>'
    + '</fieldset>').join('');
}

function reviewForm(run, details) {
  if (!details.capturedAt) {
    return '<div class="panel"><h3>Review waits for a submission</h3>'
      + '<p class="small">Nothing has been captured for this phase, so there is nothing to judge. '
      + 'A prepared run implies no result.</p></div>';
  }
  const template = run.reviewTemplate || { scores: {}, manual: [], defects: [], reviewer: '', notes: '' };
  const review = details.review || template;
  const manualSource = template.manual || [];
  const staleNotice = details.reviewCurrent === false
    ? '<div class="notice bad">This saved review judged a different submission or evaluator version. '
      + 'It is stale: rebuild the review package and review the current submission.</div>' : '';
  const scores = DIMENSIONS.map((key) => {
    const score = (review.scores || {})[key] || { value: null, evidence: '' };
    return '<div class="field"><label for="score-' + key + '">' + esc(DIMENSION_LABELS[key]) + '</label>'
      + '<select id="score-' + key + '"><option value="">unknown / not judged</option>'
      + [0, 1, 2, 3].map((n) => '<option value="' + n + '"' + (score.value === n ? ' selected' : '') + '>' + n + '</option>').join('')
      + '</select>'
      + '<textarea id="evidence-' + key + '" aria-label="' + esc(DIMENSION_LABELS[key])
      + ' evidence" placeholder="What you did, what you saw">' + esc(score.evidence || '') + '</textarea></div>';
  }).join('');
  const manual = manualSource.map((item) => {
    const saved = (review.manual || []).find((m) => m.id === item.id) || item;
    return '<fieldset><legend>' + esc(item.id) + '</legend><p class="small">'
      + esc(item.description || item.instruction || '') + '</p>'
      + '<div class="field"><label for="manual-' + esc(item.id) + '">Result</label>'
      + '<select id="manual-' + esc(item.id) + '">'
      + ['not_run', 'pass', 'fail'].map((s) => '<option value="' + s + '"'
        + (saved.status === s ? ' selected' : '') + '>' + s.replace('_', ' ') + '</option>').join('')
      + '</select></div>'
      + '<div class="field"><label for="manual-evidence-' + esc(item.id) + '">Evidence</label>'
      + '<textarea id="manual-evidence-' + esc(item.id) + '">' + esc(saved.evidence || '') + '</textarea></div>'
      + '</fieldset>';
  }).join('');
  return '<div class="panel"><h3>Evidence-backed review</h3>' + staleNotice
    + '<p class="small">0 unusable · 1 major gaps · 2 sound with a small gap · 3 complete and verified. '
    + 'Leave a dimension unscored when you did not verify it — unscored is not zero.</p>'
    + '<div class="field"><label for="reviewer">Reviewer name or ID</label>'
    + '<input id="reviewer" value="' + esc(review.reviewer || '') + '"></div>'
    + scores
    + '<h4>Manual acceptance checks</h4>' + (manual || '<p class="small">This scenario declares no manual checks.</p>')
    + '<h4>Unresolved defects</h4><div id="defects">' + defectRows(review.defects) + '</div>'
    + '<button type="button" class="small" id="add-defect">Add a defect</button>'
    + '<div class="field"><label for="review-notes">Notes and limits of this review</label>'
    + '<textarea id="review-notes">' + esc(review.notes || '') + '</textarea></div>'
    + '<button type="button" class="primary" id="review-save">Save review</button></div>';
}

function renderRunDetail() {
  const run = currentRun();
  if (!run) { $('#run-detail').innerHTML = '<p class="small">No run selected.</p>'; return; }
  const details = phaseOf(run);
  $('#detail-heading').textContent = run.id + ' · ' + (run.methodLabel || run.method);

  const phaseCards = PHASES.map((name) => {
    const item = (run.phases || {})[name];
    if (!item) {
      return '<div class="panel"><h4>' + esc(name) + '</h4><p>Not captured. ' + UNKNOWN
        + ' elapsed, ' + UNKNOWN + ' checks.</p></div>';
    }
    return '<div class="panel"><h4>' + esc(name) + '</h4><p>' + gatePill(item.gate) + '</p>'
      + '<dl class="kv"><dt>Captured</dt><dd class="mono">' + esc(item.capturedAt) + '</dd>'
      + '<dt>Elapsed</dt><dd>' + number(item.elapsedMinutes, 1) + ' / ' + esc(item.allowanceMinutes) + ' min'
      + (item.overBudget ? ' ' + pill('over', 'bad') : '') + '</dd>'
      + '<dt>Checks</dt><dd>' + (item.evaluation ? esc(item.evaluation.passed + ' / ' + item.evaluation.total) : UNKNOWN) + '</dd>'
      + '<dt>Review</dt><dd>' + (item.review
        ? (item.reviewCurrent === false ? pill('stale', 'bad') : pill('saved', 'ok'))
        : pill('none yet', 'wait')) + '</dd>'
      + '<dt>Submission hash</dt><dd class="mono">' + esc(item.submissionHash || 'unrecorded') + '</dd></dl></div>';
  }).join('');

  const actions = [
    ['Start the first-attempt clock', command('start ' + run.id)],
    ['Capture the first submission', command('capture ' + run.id + ' --phase first')],
    ['Evaluate the first submission', command('evaluate ' + run.id + ' --phase first')],
    ['Export blind reviewer packages', command('blind --phase ' + phase())],
    ['Start the repair clock', command('repair ' + run.id)],
    ['Capture the repaired submission', command('capture ' + run.id + ' --phase repaired')],
    ['Evaluate the repaired submission', command('evaluate ' + run.id + ' --phase repaired')],
    ['Import a trace for this run', command('trace-import ' + run.id + ' --file /path/to/trace.jsonl')],
    ['Export every result', command('export')],
  ];

  const method = run.methodFrozen || (state.data.methods || []).find((m) => m.id === run.method) || {};
  const roles = (method.roles || []).map((role) => '<tr><td data-label="Role">' + esc(role.role) + '</td>'
    + ['model', 'reasoning'].map((field) => {
      const value = role[field] || {};
      return '<td data-label="' + field + ' requested">' + (known(value.requested) ? esc(value.requested) : UNKNOWN) + '</td>'
        + '<td data-label="' + field + ' effective">' + (known(value.effective) ? esc(value.effective) : UNKNOWN)
        + ' ' + (value.verified ? pill('verified', 'ok') : pill('unverified', 'wait')) + '</td>';
    }).join('') + '</tr>').join('');
  const budgets = Object.entries(method.budgets || {}).map(([key, budget]) => '<tr>'
    + '<td data-label="Budget">' + esc(key) + '</td>'
    + '<td data-label="Limit">' + (known(budget.limit) ? esc(budget.limit) : UNKNOWN) + '</td>'
    + '<td data-label="Enforcement">' + esc(budget.enforcement) + '</td></tr>').join('');

  $('#run-detail').innerHTML = '<div class="cols">' + phaseCards + '</div>'
    + '<div class="cols"><div>'
    + '<div class="panel"><h3>What to run next</h3>'
    + '<p class="small">Copy a command into a terminal. Stop every agent write before a capture. '
    + 'Nothing here starts an agent for you.</p><div class="stack">'
    + actions.map(([label, text]) => '<div class="rowline"><span class="small" style="flex:1">'
      + esc(label) + '</span><button type="button" class="small" data-copy="' + esc(text) + '">Copy'
      + '<span class="vh"> the command to ' + esc(label.toLowerCase()) + '</span></button></div>').join('')
    + '</div><details><summary>Show the commands as text</summary><pre>'
    + esc(actions.map((a) => a[1]).join('\n\n')) + '</pre></details>'
    + '<details><summary>Launch text handed to the session</summary>'
    + '<p class="mono small">' + esc(run.workspace || '') + '</p>'
    + '<pre class="scrollbox">' + esc(run.launch || 'No launch text has been written for this run.') + '</pre>'
    + '<button type="button" class="small" id="copy-launch">Copy the launch text</button></details>'
    + '<details><summary>Evidence and adapter details</summary>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Role</th>'
    + '<th scope="col">Model requested</th><th scope="col">Model effective</th>'
    + '<th scope="col">Reasoning requested</th><th scope="col">Reasoning effective</th></tr></thead>'
    + '<tbody>' + (roles || '<tr><td colspan="5">No roles recorded.</td></tr>') + '</tbody></table></div>'
    + '<div class="tbl" style="margin-top:10px"><table class="stacky"><thead><tr><th scope="col">Budget</th>'
    + '<th scope="col">Limit</th><th scope="col">Enforcement</th></tr></thead><tbody>'
    + (budgets || '<tr><td colspan="3">No budgets recorded.</td></tr>') + '</tbody></table></div>'
    + '<dl class="kv" style="margin-top:10px"><dt>Transport</dt><dd>' + esc(method.transport || 'not recorded') + '</dd>'
    + '<dt>Adapter</dt><dd class="mono">' + esc(method.adapter || 'none — launched by the operator') + '</dd>'
    + '<dt>Baseline commit</dt><dd class="mono">' + esc(run.baselineCommit || 'not recorded') + '</dd></dl>'
    + '</details>'
    + '</div>' + evaluationBlock(details) + metricsForm(run, details)
    + '</div><div>' + reviewForm(run, details) + '</div></div>';
}

function renderMethods() {
  const data = state.data;
  $('#methods').innerHTML = (data.methods || []).map((method) => {
    const started = (data.runs || []).some((run) => run.method === method.id && run.startedAt);
    return '<div class="rowline" style="border-top:1px solid var(--line-soft);padding:10px 0">'
      + '<div style="flex:1"><strong>' + esc(method.label) + '</strong>'
      + ' ' + (method.configured ? pill('setup recorded', 'ok') : pill('setup still needed', 'wait'))
      + '<div class="small mono">' + esc(method.id) + ' · ' + esc(method.mode) + '</div></div>'
      + '<button type="button" class="small" data-config="' + esc(method.id) + '"'
      + (started ? ' disabled' : '') + '>Configure<span class="vh"> ' + esc(method.label) + '</span></button></div>';
  }).join('') || '<p class="small">This experiment records no methods.</p>';
}

/* ------------------------------------------------------------ trace view */

const TIMELINE_KIND = {
  node_failed: 'kind-bad', fault: 'kind-bad', node_canceled: 'kind-bad',
  restart: 'kind-warn', intervention: 'kind-warn', node_skipped: 'kind-warn',
  node_completed: 'kind-good', node_declared: 'kind-info', node_started: 'kind-info',
};

function graphColumn(title, graph, joinStatus, note) {
  const nodes = Object.values((graph && graph.nodes) || {});
  if (!nodes.length) {
    return '<div class="panel"><h3>' + esc(title) + '</h3><p>No nodes. ' + esc(note || '') + '</p></div>';
  }
  return '<div class="panel"><h3>' + esc(title) + '</h3><p class="small">' + esc(note || '') + '</p>'
    + '<ul class="graph-list">' + nodes.map((node) => {
      const status = (joinStatus || {})[node.nodeId];
      return '<li class="graph-node state-' + esc(status || 'unknown') + '">'
        + '<span class="node-id">' + esc(node.nodeId) + '</span> '
        + pill(node.role || 'role unrecorded')
        + ' ' + (status ? statusPill(status) : pill('not in the join', 'wait'))
        + '<div class="small">attempts: ' + esc((node.attempts || []).join(', ') || 'none')
        + (node.dependsOn && node.dependsOn.length ? ' · depends on ' + esc(node.dependsOn.join(', ')) : '')
        + (node.parentId ? ' · parent ' + esc(node.parentId) : '') + '</div></li>';
    }).join('') + '</ul></div>';
}

function usageSummary(usage) {
  if (!usage) return '';
  const parts = [];
  [['inputTokens', 'in'], ['outputTokens', 'out'], ['costUSD', 'cost'], ['durationSeconds', 'duration']]
    .forEach(([key, label]) => {
      if (usage[key]) parts.push(esc(label) + ' ' + measurement(usage[key]));
    });
  if (!parts.length) return '';
  return '<div class="small">usage (' + esc(usage.scope || 'self') + '): ' + parts.join(' · ') + '</div>';
}

function rolesTable(roles) {
  const entries = Object.entries(roles || {});
  if (!entries.length) return '<p class="small">No per-role usage is present in this trace.</p>';
  return '<div class="tbl"><table class="stacky"><caption>Effort by role, as recorded in the trace.</caption>'
    + '<thead><tr><th scope="col">Role</th><th scope="col">Input tokens</th><th scope="col">Output tokens</th>'
    + '<th scope="col">Cost (USD)</th><th scope="col">Duration</th><th scope="col">Nodes</th></tr></thead><tbody>'
    + entries.map(([role, usage]) => '<tr><th scope="row" data-label="Role">' + esc(role) + '</th>'
      + '<td data-label="Input tokens">' + aggregate(usage.inputTokens) + '</td>'
      + '<td data-label="Output tokens">' + aggregate(usage.outputTokens) + '</td>'
      + '<td data-label="Cost (USD)">' + aggregate(usage.costUSD, 4) + '</td>'
      + '<td data-label="Duration">' + aggregate(usage.durationSeconds) + '</td>'
      + '<td data-label="Nodes" class="mono">' + esc((usage.nodes || []).join(', ')) + '</td></tr>').join('')
    + '</tbody></table></div>';
}

function renderTrace() {
  const run = currentRun();
  const body = $('#trace-body');
  if (!run) { body.innerHTML = '<p>No run selected.</p>'; return; }
  const trace = state.traces.get(run.id);
  if (!trace) { body.innerHTML = '<p class="small">Loading the trace…</p>'; return; }
  if (!trace.hasTrace) {
    body.innerHTML = '<div class="notice bad"><strong>No trace has been imported for run '
      + esc(run.id) + '.</strong> Nothing about what ran is known here — this is missing evidence, '
      + 'not an empty or successful run.</div>'
      + '<p class="small">Import one with <span class="mono">' + esc(command('trace-import ' + run.id + ' --file /path/to/trace.jsonl')) + '</span></p>';
    return;
  }
  const report = trace.report || {};
  const join = trace.join || {};
  const graphs = report.graphs || {};
  const missing = (join.missing || []);
  const failed = (join.failed || []);

  const problems = '<div class="' + (missing.length || failed.length ? 'notice bad' : 'notice ok') + '">'
    + (missing.length || failed.length
      ? '<strong>Missing or failed work in this run.</strong><ul>'
        + missing.map((n) => '<li><span class="mono">' + esc(n) + '</span> — declared, never observed: '
          + 'its output is MISSING, not empty.</li>').join('')
        + failed.map((n) => '<li><span class="mono">' + esc(n) + '</span> — FAILED. Its outputs are not usable evidence.</li>').join('')
        + (join.skipped || []).map((n) => '<li><span class="mono">' + esc(n) + '</span> — skipped.</li>').join('')
        + '</ul>'
      : 'Every expected node reached a terminal state, and none failed.')
    + '</div>';

  const differences = '<div class="panel"><h3>Declared versus observed</h3><dl class="kv">'
    + '<dt>Declared but never observed</dt><dd>' + ((graphs.declaredOnly || []).length
      ? '<span class="mono">' + esc(graphs.declaredOnly.join(', ')) + '</span> ' + pill('difference', 'bad') : 'none') + '</dd>'
    + '<dt>Observed but never declared</dt><dd>' + ((graphs.observedOnly || []).length
      ? '<span class="mono">' + esc(graphs.observedOnly.join(', ')) + '</span> ' + pill('difference', 'bad') : 'none') + '</dd>'
    + '<dt>Edges that differ</dt><dd>' + ((graphs.edgeDifferences || []).length
      ? '<span class="mono">' + esc(graphs.edgeDifferences.map((e) => e.join(' → ')).join('; ')) + '</span>' : 'none') + '</dd>'
    + '<dt>Deviated from the declared plan</dt><dd>' + (graphs.deviated ? pill('yes', 'bad') : pill('no', 'ok')) + '</dd>'
    + '<dt>Join</dt><dd>' + (join.joinOk ? pill('all nodes completed or deliberately skipped', 'ok') : pill('join incomplete', 'bad'))
      + ((join.forcedSkips || []).length ? ' <span class="mono">' + esc(join.forcedSkips.join(', ')) + '</span> skipped because a limit or a failed dependency stopped them' : '') + '</dd>'
    + '</dl></div>';

  const timeline = (trace.timeline || []).map((event) => {
    const kind = TIMELINE_KIND[event.type] || '';
    const artifacts = [].concat((event.artifacts || {}).inputs || [], (event.artifacts || {}).outputs || []);
    return '<li class="' + kind + '"><span class="when">' + esc(event.timestamp) + '</span> · '
      + '<span class="mono">' + esc(event.nodeId) + '</span> attempt ' + esc(event.attempt)
      + ' · <strong>' + esc(event.type.replace(/_/g, ' ')) + '</strong>'
      + ' · ' + esc(event.role) + ' · status ' + esc(event.status)
      + (event.sourceRevision ? ' · rev <span class="mono">' + esc(event.sourceRevision) + '</span>' : '')
      + ((event.payload && event.payload.kind) ? ' · ' + esc(event.payload.kind) : '')
      + usageSummary(event.usage)
      + (artifacts.length ? '<div class="small">artifacts: '
        + artifacts.map((a) => esc(a.path) + ' <span class="evref">' + esc((a.sha256 || '').slice(0, 12)) + '</span>').join(', ')
        + '</div>' : '')
      + '<div class="evref">evidence: ' + esc((event.evidence || {}).ref || 'no reference recorded')
      + ' · ' + esc(((event.evidence || {}).sha256 || '').slice(0, 12) || 'no hash')
      + ' · importer ' + esc((event.evidence || {}).importer) + ' ' + esc((event.evidence || {}).importerVersion)
      + '</div></li>';
  }).join('');

  const lineage = Object.entries(trace.lineage || {}).map(([nodeId, attempts]) => '<details>'
    + '<summary>' + esc(nodeId) + ' — ' + attempts.length + ' attempt' + (attempts.length === 1 ? '' : 's')
    + ((attempts.some((a) => a.stale) ? ' · stale source revision' : ''))
    + ((attempts.some((a) => (a.reusedArtifactHashes || []).length) ? ' · reused artifact' : '')) + '</summary>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Attempt</th><th scope="col">Status</th>'
    + '<th scope="col">Source revision</th><th scope="col">Outputs</th><th scope="col">Flags</th></tr></thead><tbody>'
    + attempts.map((a) => '<tr><td data-label="Attempt">' + esc(a.attempt) + '</td>'
      + '<td data-label="Status">' + statusPill(a.status) + '</td>'
      + '<td data-label="Source revision" class="mono">' + (known(a.sourceRevision) ? esc(a.sourceRevision) : UNKNOWN) + '</td>'
      + '<td data-label="Outputs" class="mono">' + ((a.outputs || []).map((o) => esc(o.path)).join(', ') || 'none') + '</td>'
      + '<td data-label="Flags">' + (a.stale ? pill('stale revision', 'bad') + ' ' : '')
      + ((a.reusedArtifactHashes || []).length ? pill('reused artifact', 'wait') : '')
      + (!a.stale && !(a.reusedArtifactHashes || []).length ? '—' : '') + '</td></tr>').join('')
    + '</tbody></table></div></details>').join('');

  const critical = report.criticalPath || {};
  const resources = '<div class="panel"><h3>What this run consumed</h3>'
    + '<dl class="kv">'
    + '<dt>Wall time (interval union)</dt><dd>' + measurement((report.wallTime || {}).seconds, 1)
    + ' <span class="small">sum of node durations was '
    + number((report.wallTime || {}).sumOfDurationsSeconds, 1) + ' s; overlapping work is never added twice</span></dd>'
    + '<dt>Waiting</dt><dd>' + measurement((report.overhead || {}).waitingSeconds, 1) + '</dd>'
    + '<dt>Integration</dt><dd>' + measurement((report.overhead || {}).integrationSeconds, 1) + '</dd>'
    + '<dt>Retry</dt><dd>' + measurement((report.overhead || {}).retrySeconds, 1) + '</dd>'
    + '<dt>Critical path</dt><dd>' + (critical.supported
      ? esc((critical.nodes || []).join(' → ')) + ' · ' + measurement(critical.seconds, 1)
      : UNKNOWN + ' <span class="small">' + esc(critical.reason || 'not supported by this trace') + '</span>') + '</dd>'
    + '<dt>Agent interventions in the trace</dt><dd>' + esc((report.interventions || {}).count ?? 0) + '</dd>'
    + '<dt>Faults and restarts</dt><dd>' + esc((report.faults || {}).count ?? 0) + '</dd>'
    + '<dt>Highest attempt seen</dt><dd>' + esc((report.retries || {}).attempts ?? 0)
    + ' <span class="small">retried nodes: '
    + esc(((report.retries || {}).nodes || []).join(', ') || 'none') + '</span></dd>'
    + '</dl>'
    + '<h4>Totals</h4><dl class="kv">'
    + '<dt>Input tokens</dt><dd>' + aggregate((report.usageTotals || {}).inputTokens) + '</dd>'
    + '<dt>Output tokens</dt><dd>' + aggregate((report.usageTotals || {}).outputTokens) + '</dd>'
    + '<dt>Cost</dt><dd>' + aggregate((report.usageTotals || {}).costUSD, 4) + '</dd>'
    + '</dl>'
    + '<h4>Reconciliation against the imported total</h4>'
    + '<p>' + pill((report.reconciliation || {}).status || 'unknown',
      { matches: 'ok', mismatch: 'bad', unknown: 'wait' }[(report.reconciliation || {}).status] || 'wait')
    + ' ' + esc((report.reconciliation || {}).detail || '') + '</p>'
    + rolesTable(report.roles) + '</div>';

  body.innerHTML = '<p>' + (trace.synthetic ? pill('SYNTHETIC TRACE', 'synthetic') : pill('trace imported', 'info'))
    + ' <span class="mono">' + esc(run.id) + '</span> · ' + esc(run.methodLabel || run.method)
    + ' · ' + esc(report.eventCount ?? 0) + ' events</p>'
    + problems
    + '<div class="cols">'
    + graphColumn('Declared graph', trace.declared, join.status, 'What the method said it would run.')
    + graphColumn('Observed graph', trace.observed, join.status, 'What the trace actually shows.')
    + '</div>'
    + differences
    + '<div class="panel"><h3>Timeline</h3><p class="small">Every event, in trace order, with its '
    + 'attempt and its evidence reference.</p><ol class="timeline scrollbox">' + timeline + '</ol></div>'
    + '<div class="panel"><h3>Lineage: which revision produced which artifact</h3>'
    + '<p class="small">A stale source revision or a reused artifact hash means an attempt did not '
    + 'judge the code it appears to judge.</p>' + (lineage || '<p>No lineage recorded.</p>') + '</div>'
    + resources
    + (report.trace && report.trace.issues && report.trace.issues.length
      ? '<div class="notice bad"><strong>This trace is incomplete:</strong><ul>'
        + report.trace.issues.map((i) => '<li>' + esc(i) + '</li>').join('') + '</ul></div>'
      : '<div class="notice ok">No internal contradictions were found in this trace.</div>');
}

async function ensureTrace(runId) {
  if (state.traces.has(runId)) return state.traces.get(runId);
  const trace = await api('trace/' + encodeURIComponent(runId));
  state.traces.set(runId, trace);
  return trace;
}

/* ------------------------------------------------------------ comparison */

function qualityPanel(comparison) {
  const methods = comparison.methods || {};
  const phases = comparison.phases || PHASES;
  const rows = Object.keys(methods).sort().flatMap((methodId) => phases.map((name) => {
    const slot = (methods[methodId].phases || {})[name] || {};
    return '<tr><th scope="row" data-label="Method">' + esc(methodId) + '</th>'
      + '<td data-label="Phase">' + esc(name) + '</td>'
      + '<td data-label="Runs">' + esc(slot.runs ?? 0) + '</td>'
      + '<td data-label="Evaluated">' + esc(slot.evaluated ?? 0) + '</td>'
      + '<td data-label="Accepted">' + esc(slot.accepted ?? 0) + '</td>'
      + '<td data-label="Reviewed">' + esc(slot.reviewed ?? 0) + '</td>'
      + '<td data-label="Runs with serious defects">' + esc(slot.runsWithSeriousDefects ?? 0) + '</td></tr>';
  })).join('');

  const summary = comparison.pairedSummary || {};
  const pairRows = Object.keys(summary).sort().flatMap((left) => Object.keys(summary[left]).sort()
    .map((right) => {
      const cell = summary[left][right];
      return '<tr><th scope="row" data-label="Method">' + esc(left) + '</th>'
        + '<td data-label="Compared with">' + esc(right) + '</td>'
        + '<td data-label="Wins">' + esc(cell.wins) + '</td>'
        + '<td data-label="Losses">' + esc(cell.losses) + '</td>'
        + '<td data-label="Ties">' + esc(cell.ties) + '</td>'
        + '<td data-label="Not comparable">' + esc(cell.incomplete) + '</td></tr>';
    })).join('');

  const raw = (comparison.rows || []).map((row) => '<tr>'
    + '<td data-label="Run" class="mono">' + esc(row.runId) + '</td>'
    + '<td data-label="Method">' + esc(row.method) + '</td>'
    + '<td data-label="Scenario">' + esc(row.scenario) + ' · repeat ' + esc(row.repeat) + '</td>'
    + '<td data-label="Phase">' + esc(row.phase) + '</td>'
    + '<td data-label="Accepted">' + (row.accepted === null || row.accepted === undefined
      ? UNKNOWN : (row.accepted ? pill('accepted', 'ok') : pill('not accepted', 'bad'))) + '</td>'
    + '<td data-label="Serious defects">' + (row.evaluated ? esc(row.seriousDefects) : UNKNOWN) + '</td>'
    + '<td data-label="Trace complete">' + (row.traceComplete ? pill('complete', 'ok') : pill('incomplete', 'wait')) + '</td>'
    + '</tr>').join('');

  return '<div class="panel"><h3>Quality</h3>'
    + '<p class="small">Acceptance is the external evaluator\'s verdict for that phase. '
    + 'A run with no evaluation is unknown, not a failure.</p>'
    + '<div class="tbl"><table class="stacky"><caption>Acceptance and serious defects by method and phase.</caption>'
    + '<thead><tr><th scope="col">Method</th><th scope="col">Phase</th><th scope="col">Runs</th>'
    + '<th scope="col">Evaluated</th><th scope="col">Accepted</th><th scope="col">Reviewed</th>'
    + '<th scope="col">Runs with serious defects</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
    + '<h4>Paired outcomes</h4><p class="small">Only runs sharing a pair key and a phase are compared. '
    + 'Ties are a real result.</p>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Method</th>'
    + '<th scope="col">Compared with</th><th scope="col">Wins</th><th scope="col">Losses</th>'
    + '<th scope="col">Ties</th><th scope="col">Not comparable</th></tr></thead><tbody>'
    + (pairRows || '<tr><td colspan="6">No pairs yet.</td></tr>') + '</tbody></table></div>'
    + ((comparison.unpaired || []).length
      ? '<h4>Unpaired</h4><ul class="small">' + comparison.unpaired.map((u) => '<li><span class="mono">'
        + esc(u.pairKey) + '</span> · ' + esc(u.phase) + ' — ' + esc(u.reason) + '</li>').join('') + '</ul>' : '')
    + '<h4>Every run, unaggregated</h4>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Run</th><th scope="col">Method</th>'
    + '<th scope="col">Scenario</th><th scope="col">Phase</th><th scope="col">Accepted</th>'
    + '<th scope="col">Serious defects</th><th scope="col">Trace</th></tr></thead><tbody>'
    + raw + '</tbody></table></div></div>';
}

function resourcePanel(comparison) {
  const methods = comparison.methods || {};
  const operator = comparison.operatorMetrics || {};
  const rows = Object.keys(methods).sort().map((methodId) => {
    const bucket = methods[methodId];
    return '<tr><th scope="row" data-label="Method">' + esc(methodId) + '</th>'
      + '<td data-label="Runs with a trace">' + esc(bucket.tracedRuns) + ' of ' + esc(bucket.runs) + '</td>'
      + '<td data-label="Wall time">' + aggregate(bucket.wallTimeSeconds, 1) + '</td>'
      + '<td data-label="Input tokens">' + aggregate(bucket.usage.inputTokens) + '</td>'
      + '<td data-label="Output tokens">' + aggregate(bucket.usage.outputTokens) + '</td>'
      + '<td data-label="Cost (USD)">' + aggregate(bucket.usage.costUSD, 4) + '</td>'
      + '<td data-label="Agent interventions (trace)">' + esc(bucket.interventions) + '</td>'
      + '<td data-label="Reconciliation">' + Object.entries(bucket.reconciliation)
        .filter(([, count]) => count)
        .map(([key, count]) => pill(key + ' ' + count,
          { matches: 'ok', mismatch: 'bad', unknown: 'wait', absent: 'wait' }[key]))
        .join(' ') + '</td></tr>';
  }).join('');

  const humanRows = (state.data.runs || []).flatMap((run) => PHASES.map((name) => {
    const metrics = (operator[run.id] || {})[name];
    if (!metrics) return '';
    return '<tr><td data-label="Run" class="mono">' + esc(run.id) + '</td>'
      + '<td data-label="Method">' + esc(run.methodLabel || run.method) + '</td>'
      + '<td data-label="Phase">' + esc(name) + '</td>'
      + '<td data-label="Your active minutes">' + number(metrics.humanMinutes, 1) + '</td>'
      + '<td data-label="Your interventions">' + number(metrics.interventions) + '</td>'
      + '<td data-label="Cost you recorded">' + number(metrics.costUSD, 2) + '</td>'
      + '<td data-label="Source">' + (metrics.source ? esc(metrics.source) : UNKNOWN) + '</td></tr>';
  })).filter(Boolean).join('');

  const perRole = {};
  state.traces.forEach((trace, runId) => {
    const run = (state.data.runs || []).find((r) => r.id === runId);
    if (!run || !trace || !trace.report) return;
    const bucket = perRole[run.method] || (perRole[run.method] = {});
    Object.entries(trace.report.roles || {}).forEach(([role, usage]) => {
      const slot = bucket[role] || (bucket[role] = { value: null, complete: true, unknownCount: 0, unit: 'tokens', source: 'traces' });
      const tokens = usage.inputTokens || {};
      if (tokens.value === null || tokens.value === undefined) {
        slot.complete = false; slot.unknownCount += 1;
      } else { slot.value = (slot.value === null ? 0 : slot.value) + tokens.value; }
      if (tokens.complete === false) { slot.complete = false; slot.unknownCount += (tokens.unknownCount || 0); }
    });
  });
  const roleRows = Object.keys(perRole).sort().flatMap((methodId) => Object.keys(perRole[methodId]).sort()
    .map((role) => '<tr><th scope="row" data-label="Method">' + esc(methodId) + '</th>'
      + '<td data-label="Role">' + esc(role) + '</td>'
      + '<td data-label="Input tokens">' + aggregate(perRole[methodId][role]) + '</td></tr>')).join('');

  return '<div class="panel"><h3>Resources</h3>'
    + '<p class="small">Machine effort and human effort are separate columns on purpose. '
    + 'They are not added together, and neither is combined with quality.</p>'
    + '<div class="tbl"><table class="stacky"><caption>Machine effort per method, from imported traces.</caption>'
    + '<thead><tr><th scope="col">Method</th><th scope="col">Runs with a trace</th><th scope="col">Wall time</th>'
    + '<th scope="col">Input tokens</th><th scope="col">Output tokens</th><th scope="col">Cost (USD)</th>'
    + '<th scope="col">Agent interventions (trace)</th><th scope="col">Reconciliation</th></tr></thead><tbody>'
    + rows + '</tbody></table></div>'
    + '<h4>Human effort, recorded separately by the operator</h4>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Run</th><th scope="col">Method</th>'
    + '<th scope="col">Phase</th><th scope="col">Your active minutes</th><th scope="col">Your interventions</th>'
    + '<th scope="col">Cost you recorded</th><th scope="col">Source</th></tr></thead><tbody>'
    + (humanRows || '<tr><td colspan="7">No operator measurements recorded yet.</td></tr>')
    + '</tbody></table></div>'
    + '<h4>Per-role breakdown, where a trace has one</h4>'
    + '<div class="tbl"><table class="stacky"><thead><tr><th scope="col">Method</th><th scope="col">Role</th>'
    + '<th scope="col">Input tokens</th></tr></thead><tbody>'
    + (roleRows || '<tr><td colspan="3">No trace in this experiment records usage by role.</td></tr>')
    + '</tbody></table></div>'
    + ((comparison.incompleteTraces || []).length
      ? '<h4>Runs whose record is incomplete</h4><ul class="small">'
        + comparison.incompleteTraces.map((item) => '<li><span class="mono">' + esc(item.runId)
          + '</span> — ' + esc(item.reason) + '</li>').join('') + '</ul>'
      : '<p class="small">Every run has a complete record.</p>')
    + '</div>';
}

function renderComparison() {
  const comparison = state.comparison;
  const body = $('#compare-body');
  if (!comparison) { body.innerHTML = '<p class="small">Loading the comparison…</p>'; return; }
  const variation = comparison.variation || {};
  body.innerHTML = '<div class="notice"><strong>No overall winner is computed.</strong> '
    + esc('winner: ' + String(comparison.winner) + ' · policy: ' + comparison.winnerPolicy
      + ' · composite score: ' + String(comparison.compositeScore))
    + '. The tables below are in alphabetical order, which is not a ranking. Read quality first, '
    + 'then decide whether the effort was worth it.</div>'
    + (comparison.synthetic ? '<p>' + pill('SYNTHETIC DATA', 'synthetic') + '</p>' : '')
    + '<div class="cols">' + qualityPanel(comparison) + resourcePanel(comparison) + '</div>'
    + '<div class="panel"><h3>How much variation this experiment can see</h3><div class="cols">'
    + '<div><h4>Task level</h4><p>' + esc((variation.taskLevel || {}).distinctTasks ?? 0)
    + ' distinct scenario(s): <span class="mono">' + esc(((variation.taskLevel || {}).scenarios || []).join(', '))
    + '</span></p><p class="small">' + esc((variation.taskLevel || {}).note || '') + '</p></div>'
    + '<div><h4>Repeat level</h4><p>' + esc(JSON.stringify((variation.repeatLevel || {}).repeatsByScenario || {}))
    + ' across ' + esc((variation.repeatLevel || {}).totalRepeatRuns ?? 0) + ' runs</p>'
    + '<p class="small">' + esc((variation.repeatLevel || {}).note || '') + '</p></div></div></div>'
    + pairForm(comparison);
}

function pairForm(comparison) {
  const run = currentRun();
  const members = (state.data.runs || []).filter((r) => run && r.pairKey === run.pairKey);
  const options = members.map((r) => '<option value="' + esc(r.id) + '">' + esc(r.id) + ' · '
    + esc(r.methodLabel || r.method) + '</option>').join('');
  const history = (comparison.pairJudgments || []).map((judgment) => '<li>'
    + esc(judgment.preference === 'tie' ? 'Tie'
      : judgment.preference === 'incomparable' ? 'Incomparable'
        : 'Preferred ' + judgment[judgment.preference])
    + ' · <span class="mono">' + esc(judgment.a) + '</span> vs <span class="mono">' + esc(judgment.b)
    + '</span> · ' + esc(judgment.phase) + '<div class="small">' + esc(judgment.evidence) + '</div></li>').join('');
  return '<div class="panel"><h3>Record a paired judgment</h3>'
    + '<p class="small">Compare two runs of the same pair key and phase, after both reviews are saved. '
    + '"Tie" and "incomparable" are useful answers.</p>'
    + '<div class="cols">'
    + '<div class="field"><label for="pair-a">Submission A</label><select id="pair-a">' + options + '</select></div>'
    + '<div class="field"><label for="pair-b">Submission B</label><select id="pair-b">' + options + '</select></div>'
    + '<div class="field"><label for="preference">Your judgment</label><select id="preference">'
    + '<option value="tie">Tie</option><option value="a">Prefer A</option>'
    + '<option value="b">Prefer B</option><option value="incomparable">Incomparable</option></select></div>'
    + '<div class="field"><label for="pair-reviewer">Reviewer</label><input id="pair-reviewer"></div>'
    + '</div>'
    + '<div class="field"><label for="pair-evidence">The concrete reason, and what you are unsure about</label>'
    + '<textarea id="pair-evidence"></textarea></div>'
    + '<button type="button" class="primary" id="pair-save">Save the judgment</button>'
    + '<ul class="stack small" style="margin-top:12px">' + history + '</ul></div>';
}

/* ------------------------------------------------------------ tabs */

function selectTab(name, focus) {
  state.tab = name;
  TABS.forEach((tab) => {
    const button = $('#tab-' + tab);
    const panel = $('#panel-' + tab);
    const selected = tab === name;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
  });
  if (focus) $('#tab-' + name).focus();
  if (name === 'trace' && state.run) {
    ensureTrace(state.run).then(renderTrace).catch((error) => toast(error.message, true));
    renderTrace();
  }
  if (name === 'compare') { loadComparison().catch((error) => toast(error.message, true)); }
}

async function loadComparison() {
  state.comparison = await api('metrics');
  const traced = (state.data.runs || []).filter((run) => run.hasTrace);
  await Promise.all(traced.map((run) => ensureTrace(run.id).catch(() => null)));
  renderComparison();
}

/* ------------------------------------------------------------ actions */

function collectReview(run, details) {
  const template = run.reviewTemplate || { scores: {}, manual: [], defects: [], notes: '' };
  const review = {
    reviewer: $('#reviewer').value,
    scores: {},
    manual: (template.manual || []).map((item) => ({
      id: item.id,
      description: item.description,
      status: $('#manual-' + item.id).value,
      evidence: $('#manual-evidence-' + item.id).value,
    })),
    defects: Array.from(document.querySelectorAll('#defects fieldset')).map((node) => {
      const index = node.dataset.defect;
      return { severity: $('#defect-severity-' + index).value, evidence: $('#defect-evidence-' + index).value };
    }),
    notes: $('#review-notes').value,
  };
  DIMENSIONS.forEach((key) => {
    const raw = $('#score-' + key).value;
    review.scores[key] = { value: raw === '' ? null : Number(raw), evidence: $('#evidence-' + key).value };
  });
  return review;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to the clipboard.');
  } catch {
    toast('The clipboard is unavailable. Select the command text instead.', true);
  }
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  try {
    if (button.getAttribute('role') === 'tab') {
      selectTab(button.id.replace('tab-', ''));
      return;
    }
    if (button.dataset.run) {
      state.run = button.dataset.run;
      state.traces.delete(state.run);
      renderRunPicker(); renderRunGroups(); renderRunDetail();
      if (state.tab === 'trace') selectTab('trace');
      return;
    }
    if (button.dataset.copy) { await copyText(button.dataset.copy); return; }
    if (button.id === 'copy-launch') { await copyText(currentRun().launch || ''); return; }
    if (button.id === 'refresh') { await refresh(); return; }
    if (button.dataset.config) {
      state.configMethod = button.dataset.config;
      const method = state.data.methods.find((m) => m.id === state.configMethod);
      $('#config-title').textContent = 'Record the setup for ' + method.label;
      $('#config-json').value = JSON.stringify(method, null, 2);
      $('#config-panel').classList.remove('hidden');
      $('#config-json').focus();
      return;
    }
    if (button.id === 'config-cancel') { $('#config-panel').classList.add('hidden'); return; }
    if (button.id === 'config-save') {
      await api('configure', { method: state.configMethod, definition: JSON.parse($('#config-json').value) });
      $('#config-panel').classList.add('hidden');
      await refresh();
      toast('Method setup saved.');
      return;
    }
    if (button.id === 'add-defect') {
      const container = $('#defects');
      const run = currentRun();
      const existing = Array.from(container.querySelectorAll('fieldset')).map((node) => ({
        severity: $('#defect-severity-' + node.dataset.defect).value,
        evidence: $('#defect-evidence-' + node.dataset.defect).value,
      }));
      existing.push({ severity: 'minor', evidence: '' });
      container.innerHTML = defectRows(existing);
      const last = container.querySelector('fieldset:last-of-type select');
      if (last) last.focus();
      void run;
      return;
    }
    if (button.dataset.removeDefect !== undefined) {
      const container = $('#defects');
      const keep = Array.from(container.querySelectorAll('fieldset'))
        .filter((node) => node.dataset.defect !== button.dataset.removeDefect)
        .map((node) => ({
          severity: $('#defect-severity-' + node.dataset.defect).value,
          evidence: $('#defect-evidence-' + node.dataset.defect).value,
        }));
      container.innerHTML = defectRows(keep);
      $('#add-defect').focus();
      return;
    }
    if (button.id === 'metrics-save') {
      const metrics = { source: $('#metric-source').value, notes: $('#metric-notes').value };
      ['costUSD', 'humanMinutes', 'interventions', 'inputTokens', 'outputTokens'].forEach((key) => {
        const raw = $('#metric-' + key).value;
        metrics[key] = raw === '' ? null : Number(raw);
      });
      await api('metrics', { run: state.run, phase: phase(), metrics });
      await refresh();
      toast('Effort saved. Empty boxes stayed unknown.');
      return;
    }
    if (button.id === 'review-save') {
      const run = currentRun();
      await api('review', { run: run.id, phase: phase(), review: collectReview(run, phaseOf(run)) });
      await refresh();
      toast('Review saved to disk.');
      return;
    }
    if (button.id === 'pair-save') {
      await api('pair', {
        a: $('#pair-a').value, b: $('#pair-b').value, phase: phase(),
        preference: $('#preference').value, evidence: $('#pair-evidence').value,
        reviewer: $('#pair-reviewer').value,
      });
      state.comparison = await api('metrics');
      renderComparison();
      toast('Paired judgment saved.');
      return;
    }
  } catch (error) {
    toast(error.message, true);
  }
});

document.addEventListener('keydown', (event) => {
  const tab = event.target.closest('[role="tab"]');
  if (!tab) return;
  const index = TABS.indexOf(state.tab);
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault();
    const next = (index + (event.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
    selectTab(TABS[next], true);
  } else if (event.key === 'Home') {
    event.preventDefault(); selectTab(TABS[0], true);
  } else if (event.key === 'End') {
    event.preventDefault(); selectTab(TABS[TABS.length - 1], true);
  }
});

/* ------------------------------------------------------------ boot */

function renderAll() {
  renderHeader();
  renderRunPicker();
  renderRunGroups();
  renderRunDetail();
  renderMethods();
  if (state.tab === 'trace') renderTrace();
  if (state.tab === 'compare') renderComparison();
}

async function refresh() {
  state.data = await api('data');
  state.traces.clear();
  const runs = state.data.runs || [];
  if (!state.run || !runs.some((run) => run.id === state.run)) {
    const withTrace = runs.find((run) => run.hasTrace);
    state.run = (withTrace || runs[0] || {}).id || null;
  }
  renderAll();
  if (state.tab === 'trace' && state.run) { await ensureTrace(state.run); renderTrace(); }
  if (state.tab === 'compare') await loadComparison();
}

$('#phase').addEventListener('change', (event) => { state.phase = event.target.value; renderAll(); });
$('#run-picker').addEventListener('change', (event) => {
  state.run = event.target.value;
  renderRunGroups(); renderRunDetail();
  if (state.tab === 'trace') selectTab('trace');
});

refresh().catch((error) => {
  toast(error.message, true);
  $('#exp-title').textContent = 'The experiment could not be loaded';
});
