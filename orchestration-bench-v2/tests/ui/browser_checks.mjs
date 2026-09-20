/* Browser checks for the operator dashboard and the blind review page.
 *
 * Driven by tests/ui/test_browser.py, which builds the synthetic demo experiment and starts
 * both real servers on ephemeral ports. Playwright is loaded from an existing checkout
 * (never installed here) and drives the installed Google Chrome.
 *
 * Environment: BENCH_URL, REVIEW_URL, DEMO_JSON, SHOT_DIR, PLAYWRIGHT_DIR.
 */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const PLAYWRIGHT_DIR = process.env.PLAYWRIGHT_DIR;
const BENCH_URL = process.env.BENCH_URL;
const REVIEW_URL = process.env.REVIEW_URL;
const SHOT_DIR = process.env.SHOT_DIR;
const demo = JSON.parse(fs.readFileSync(process.env.DEMO_JSON, 'utf8'));

const require = createRequire(PLAYWRIGHT_DIR.endsWith('/') ? PLAYWRIGHT_DIR : PLAYWRIGHT_DIR + '/');
const { chromium } = require('playwright');

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 1100 },
  { name: 'mobile', width: 390, height: 844 },
];

const results = [];
let failures = 0;

function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail === undefined ? null : String(detail) });
  if (!ok) failures += 1;
}

function shot(page, name) {
  return page.screenshot({ path: path.join(SHOT_DIR, name + '.png'), fullPage: false });
}

async function overflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
}

async function focusRing(page) {
  return page.evaluate(() => {
    const node = document.activeElement;
    if (!node || node === document.body) return null;
    const style = getComputedStyle(node);
    return {
      tag: node.tagName, id: node.id,
      outlineWidth: style.outlineWidth, outlineStyle: style.outlineStyle,
      boxShadow: style.boxShadow,
    };
  });
}

/** Press Tab until the focused element satisfies `predicate` (evaluated in the page). */
async function tabUntil(page, expression, limit = 80) {
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press('Tab');
    const hit = await page.evaluate(expression);
    if (hit) return i + 1;
  }
  return null;
}

/* ------------------------------------------------------------ dashboard */

async function checkDashboard(context, viewport) {
  const tag = viewport.name;
  const page = await context.newPage();
  const consoleErrors = [];
  // The browser asks for /favicon.ico on its own; a 404 for it is not a page defect.
  page.on('console', (message) => {
    const where = (message.location() || {}).url || '';
    if (message.type() === 'error' && !/favicon/.test(where + message.text())) {
      consoleErrors.push(message.text() + ' @ ' + where);
    }
  });
  page.on('pageerror', (error) => consoleErrors.push('pageerror: ' + error.message));

  await page.goto(BENCH_URL, { waitUntil: 'networkidle' });
  await page.waitForSelector('#run-groups table');

  check(`${tag}: dashboard synthetic banner`,
    await page.locator('#synthetic-banner').isVisible());
  check(`${tag}: dashboard readiness blockers listed`,
    (await page.locator('#readiness').innerText()).includes('Not ready to start'));
  check(`${tag}: dashboard names the integrity state`,
    /Integrity (verified|broken)/.test(await page.locator('#integrity-status').innerText()));
  check(`${tag}: dashboard discloses the schedule balance`,
    (await page.locator('#schedule').evaluate((node) => node.textContent)).includes('counterbalanced-rotation/1'));
  check(`${tag}: runs are grouped by pair key`,
    (await page.locator('#run-groups').innerText()).includes('|local-default|r1'));
  check(`${tag}: a stale review is called out`,
    (await page.locator('#run-groups').innerText()).includes('Review is stale'));

  let box = await overflow(page);
  check(`${tag}: dashboard has no horizontal overflow`,
    box.scrollWidth <= box.innerWidth, JSON.stringify(box));
  await shot(page, `dashboard-overview-${tag}`);

  // -- keyboard: reach the tablist, move with arrow keys ------------------
  await page.evaluate(() => { window.scrollTo(0, 0); document.body.focus(); });
  const steps = await tabUntil(page, "document.activeElement && document.activeElement.id === 'tab-runs'");
  check(`${tag}: keyboard reaches the view tabs`, steps !== null, `tab presses: ${steps}`);
  const ring = await focusRing(page);
  check(`${tag}: focus is visible on the tab`,
    ring && (ring.outlineStyle !== 'none' && parseFloat(ring.outlineWidth) > 0),
    JSON.stringify(ring));

  await page.keyboard.press('ArrowRight');
  check(`${tag}: arrow key opens the trace view`,
    await page.locator('#panel-trace').isVisible());
  await page.waitForSelector('#trace-body .timeline li');
  await page.selectOption('#run-picker', 'run-zz0001');
  await page.waitForFunction(() =>
    document.querySelector('#trace-body').innerText.includes('run-zz0001'));

  const traceText = await page.locator('#trace-body').innerText();
  check(`${tag}: trace shows node attempts`, /attempts: 1, 2/.test(traceText), traceText.slice(0, 200));
  check(`${tag}: trace shows the failed node explicitly`,
    traceText.includes('worker-c') && /FAILED/.test(traceText));
  check(`${tag}: trace shows the missing node explicitly`,
    traceText.includes('worker-d') && /MISSING/.test(traceText));
  check(`${tag}: trace marks a stale source revision`, /stale source revision/i.test(traceText));
  check(`${tag}: trace marks a reused artifact`, /reused artifact/i.test(traceText));
  check(`${tag}: trace links evidence references`, /active\.jsonl#L\d+/.test(traceText));
  check(`${tag}: trace names the join state`, /join/i.test(traceText));
  check(`${tag}: trace declares itself synthetic`, /SYNTHETIC TRACE/.test(traceText));
  check(`${tag}: a missing node is never drawn as a success`,
    !/worker-d[^\n]*completed/i.test(traceText));

  box = await overflow(page);
  check(`${tag}: trace view has no horizontal overflow`,
    box.scrollWidth <= box.innerWidth, JSON.stringify(box));
  await shot(page, `trace-view-${tag}`);

  // -- keyboard: operate a disclosure inside the trace view ---------------
  const reached = await tabUntil(page,
    "document.activeElement && document.activeElement.tagName === 'SUMMARY' "
    + "&& document.activeElement.closest('#panel-trace') !== null");
  if (reached !== null) {
    const before = await page.evaluate(() => document.activeElement.parentElement.open);
    await page.keyboard.press('Enter');
    const after = await page.evaluate(() =>
      document.querySelector('#panel-trace details[open]') !== null);
    check(`${tag}: a trace disclosure opens from the keyboard`, before !== after || after, `before=${before}`);
  } else {
    check(`${tag}: a trace disclosure opens from the keyboard`, false, 'no summary reached by Tab');
  }

  // -- unknown values ------------------------------------------------------
  await page.selectOption('#run-picker', 'run-zz0003');
  await page.waitForFunction(() => document.querySelector('#trace-body').innerText.includes('run-zz0003'));
  const unknownRun = await page.locator('#trace-body').innerText();
  check(`${tag}: an unavailable cost renders as "unknown"`, /unknown/.test(unknownRun));
  const costCell = await page.evaluate(() => {
    const terms = Array.from(document.querySelectorAll('#trace-body .kv dt'));
    const dt = terms.find((node) => node.textContent.trim() === 'Cost');
    return dt ? dt.nextElementSibling.innerText.trim() : null;
  });
  check(`${tag}: an unknown cost is not shown as 0`,
    costCell !== null && /unknown/i.test(costCell) && !/^0([.,]0+)?$/.test(costCell), String(costCell));
  check(`${tag}: a partial aggregate says how many values are unknown`,
    /partial \(\d+ unknown\)/.test(unknownRun));
  const provenanceText = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#trace-body .prov'))
      .map((node) => node.textContent.trim() + '|' + (node.dataset.source || '')).join('\n'));
  check(`${tag}: provenance labels are present`, /measured/.test(provenanceText), provenanceText.slice(0, 200));
  check(`${tag}: an estimated value is distinguished from a measured one`,
    /estimated/.test(provenanceText), provenanceText.slice(0, 300));
  check(`${tag}: provenance carries its source as accessible text`,
    (await page.locator('#trace-body').innerText()).includes('provenance:')
    || await page.evaluate(() => Array.from(document.querySelectorAll('#trace-body .vh'))
      .some((node) => node.textContent.includes('provenance:'))));

  // -- comparison ----------------------------------------------------------
  await page.focus('#tab-trace');
  await page.keyboard.press('ArrowRight');
  check(`${tag}: arrow key opens the comparison view`,
    await page.locator('#panel-compare').isVisible());
  await page.waitForSelector('#compare-body table');
  const compareText = await page.locator('#compare-body').innerText();
  check(`${tag}: comparison refuses to name a winner`,
    /No overall winner/i.test(compareText) && /not computed/i.test(compareText));
  check(`${tag}: comparison shows no composite score`, /composite score: null/i.test(compareText));
  check(`${tag}: comparison separates human effort`, /human effort, recorded separately/i.test(compareText));
  check(`${tag}: comparison shows a per-role breakdown`, /per-role breakdown/i.test(compareText));
  check(`${tag}: comparison reports reconciliation`, /Reconciliation/i.test(compareText));
  check(`${tag}: comparison lists incomplete traces`,
    /incomplete/i.test(compareText) && compareText.includes('run-zz0004'));
  check(`${tag}: comparison separates task and repeat variation`,
    /task level/i.test(compareText) && /repeat level/i.test(compareText));
  check(`${tag}: comparison shows paired wins, losses and ties`,
    /wins/i.test(compareText) && /ties/i.test(compareText));
  check(`${tag}: comparison shows raw per-run rows`, /every run, unaggregated/i.test(compareText));

  box = await overflow(page);
  check(`${tag}: comparison has no horizontal overflow`,
    box.scrollWidth <= box.innerWidth, JSON.stringify(box));
  await shot(page, `comparison-${tag}`);

  // -- keyboard: activate a run from the run list --------------------------
  await page.focus('#tab-compare');
  await page.keyboard.press('ArrowRight'); // wraps to the runs tab
  check(`${tag}: arrow keys wrap back to the runs view`,
    await page.locator('#panel-runs').isVisible());
  const inspect = await tabUntil(page,
    "document.activeElement && document.activeElement.dataset "
    + "&& document.activeElement.dataset.run === 'run-zz0002'");
  if (inspect !== null) {
    await page.keyboard.press('Enter');
    check(`${tag}: Enter on a run button selects that run`,
      (await page.locator('#detail-heading').innerText()).includes('run-zz0002'));
  } else {
    check(`${tag}: Enter on a run button selects that run`, false, 'run button not reachable by Tab');
  }
  check(`${tag}: launch text is available`,
    (await page.locator('#run-detail').innerText()).includes('Launch text handed to the session'));

  check(`${tag}: dashboard logged no console error`, consoleErrors.length === 0,
    consoleErrors.join(' | '));
  await page.close();
}

/* ------------------------------------------------------------ review page */

async function checkReview(context, viewport) {
  const tag = viewport.name;
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const requests = [];
  const bodies = [];
  page.on('console', (message) => {
    const where = (message.location() || {}).url || '';
    if (message.type() === 'error' && !/favicon/.test(where + message.text())) {
      consoleErrors.push(message.text() + ' @ ' + where);
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => requests.push(request.url()));
  page.on('response', async (response) => {
    try {
      const headers = response.headers();
      const type = headers['content-type'] || '';
      if (/json|text|html/.test(type)) bodies.push({ url: response.url(), text: await response.text() });
    } catch { /* a body that cannot be read cannot leak here */ }
  });

  await page.goto(REVIEW_URL, { waitUntil: 'networkidle' });
  await page.waitForSelector('#submission-list button');

  const listText = await page.locator('#submission-list').innerText();
  check(`${tag}: review lists packages by label only`, /B-[0-9A-F]{6}/.test(listText));
  check(`${tag}: review shows the residual-cues notice`,
    (await page.locator('#cues').innerText()).includes('best-effort'));

  let box = await overflow(page);
  check(`${tag}: review list has no horizontal overflow`,
    box.scrollWidth <= box.innerWidth, JSON.stringify(box));

  // -- open a package, read a file, submit a review from the keyboard ------
  await page.selectOption('#phase', demo.submitTarget.phase);
  await page.waitForSelector(`#submission-list button[data-label="${demo.submitTarget.label}"]`);
  await page.click(`#submission-list button[data-label="${demo.submitTarget.label}"]`);
  await page.waitForSelector('#review-form');

  const detailText = await page.locator('#detail').innerText();
  check(`${tag}: review shows automated check results`,
    /automated check results/i.test(detailText) && /Z1/.test(detailText));
  check(`${tag}: review offers a file browser`,
    (await page.locator('#file-list button.file').count()) > 0);

  await page.click('#file-list button.file >> nth=0');
  await page.waitForFunction(() =>
    document.querySelector('#file-view').textContent !== 'Choose a file to read it here.');
  check(`${tag}: a submitted file can be read`,
    (await page.locator('#file-view').innerText()).length > 0);

  box = await overflow(page);
  check(`${tag}: review detail has no horizontal overflow`,
    box.scrollWidth <= box.innerWidth, JSON.stringify(box));
  await shot(page, `blind-review-${tag}`);

  await page.fill('#reviewer', 'anon-browser-check');
  await page.selectOption('#score-correctness', '2');
  await page.fill('#evidence-correctness', 'Ran the submitted module and exercised the filter.');
  const manualId = await page.evaluate(() => {
    const node = document.querySelector('#review-form fieldset select[id^="manual-"]');
    return node ? node.id.replace('manual-', '') : null;
  });
  if (manualId) {
    await page.selectOption('#manual-' + manualId, 'pass');
    await page.fill('#manual-evidence-' + manualId, 'Checked with the keyboard only.');
  }

  const submitSteps = await tabUntil(page,
    "document.activeElement && document.activeElement.id === 'submit-review'");
  check(`${tag}: keyboard reaches the submit button`, submitSteps !== null);
  const submitRing = await focusRing(page);
  check(`${tag}: focus is visible on the review submit button`,
    submitRing && submitRing.outlineStyle !== 'none' && parseFloat(submitRing.outlineWidth) > 0,
    JSON.stringify(submitRing));
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => !document.querySelector('#toast').classList.contains('hidden'));
  const toastText = await page.locator('#toast').innerText();
  check(`${tag}: a review submits from the keyboard`, /Review saved/.test(toastText), toastText);
  // Everything up to here should be clean; the stale step below provokes a 409 on purpose.
  check(`${tag}: review page logged no console error`, consoleErrors.length === 0,
    consoleErrors.join(' | '));

  // -- stale package -------------------------------------------------------
  await page.selectOption('#phase', demo.staleTarget.phase);
  await page.waitForSelector(`#submission-list button[data-label="${demo.staleTarget.label}"]`);
  await page.click(`#submission-list button[data-label="${demo.staleTarget.label}"]`);
  await page.waitForSelector('#review-form');
  await page.fill('#reviewer', 'anon-browser-check');
  // The submission moves under the reviewer, exactly as a re-capture would move it.
  fs.appendFileSync(demo.staleTarget.file, '\nAmended while the review was open.\n');
  await page.click('#submit-review');
  await page.waitForSelector('#stale:not(.hidden)');
  const staleText = await page.locator('#stale').innerText();
  check(`${tag}: a stale package tells the reviewer to reload`,
    /out of date/i.test(staleText) && /Reload/i.test(staleText), staleText);
  check(`${tag}: a stale review is not reported as saved`, !/Review saved/.test(staleText));

  // -- isolation -----------------------------------------------------------
  const foreign = requests.filter((url) => !url.startsWith(REVIEW_URL));
  check(`${tag}: the review page requests nothing outside its own server`,
    foreign.length === 0, foreign.join(' | '));
  const operatorRoutes = requests.filter((url) => /\/api\/(data|metrics|trace|review|configure|pair)/.test(
    url.replace('/review/api/', '/REVIEWAPI/')));
  check(`${tag}: the review page requests no operator endpoint`,
    operatorRoutes.length === 0, operatorRoutes.join(' | '));

  const leaks = [];
  bodies.forEach((body) => {
    demo.identityStrings.forEach((term) => {
      if (body.text.includes(term)) leaks.push(term + ' in ' + body.url);
    });
  });
  check(`${tag}: no method label, model name or run ID reaches the review page`,
    leaks.length === 0, leaks.join(' | '));

  check(`${tag}: review page raised no script error`, pageErrors.length === 0,
    pageErrors.join(' | '));
  await page.close();
}

/* ------------------------------------------------------------ run */

fs.mkdirSync(SHOT_DIR, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const viewport of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      reducedMotion: 'reduce',
      colorScheme: viewport.name === 'mobile' ? 'dark' : 'light',
    });
    await checkDashboard(context, viewport);
    await checkReview(context, viewport);
    await context.close();
  }
} finally {
  await browser.close();
}

const summary = {
  playwright: require('playwright/package.json').version,
  node: process.version,
  checks: results,
  failures,
};
fs.writeFileSync(path.join(SHOT_DIR, 'browser-checks.json'), JSON.stringify(summary, null, 2) + '\n');
console.log(JSON.stringify(summary, null, 2));
process.exit(failures ? 1 : 0);
