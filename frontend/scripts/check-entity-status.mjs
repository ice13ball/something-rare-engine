#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// Entity routes have THREE outcomes, and only the third was ever tested.
//
// Until 2026-08-18 every entity route collapsed "this id does not exist" and
// "I could not reach the backend" into one `null`, fell through to the SPA
// catch-all, and answered **200 with the empty shell** for both. That is a soft
// 404 on a typo and a silent de-indexing of ~40,300 URLs during an outage —
// Google reads a 200 that renders nothing as a statement about the page, not
// about the server.
//
// So this checker does what `check:render` and `check:seo` do not: it drives
// the FAILURE paths. It boots the real server.js five times against a stub
// backend it controls, once against a backend that is not running at all.
//
//   backend answers 404      → the route must answer 404
//   backend answers 422      → the route must answer 404   (the id cannot BE an id)
//   backend answers 500      → the route must answer 503 + Retry-After
//   backend answers 429      → the route must answer 503   (about us, not the id)
//   backend is not running   → the route must answer 503 + Retry-After
//   backend answers normally → the route must answer 200 with real content
//
// ⚠️ The last case is not decoration. A fix that 404s everything would pass
// every other case and is exactly the "confident de-indexing" the report warns
// against — the working case is what stops it. 422 and 429 are the mirror pair
// that stops the opposite over-correction: both are 4xx, and they must land on
// opposite sides, which is why the rule is a named set and not "any 4xx".
//
//     node scripts/check-entity-status.mjs
// ─────────────────────────────────────────────────────────────────────────────

import { spawn } from 'child_process';
import { createServer } from 'http';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const STUB_PORT = 8791;
const APP_PORT = 8792;
const BOT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)';
const HUMAN = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

const failures = [];
function check(label, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

// Routes that must 404 on an unknown id. Two families, deliberately both:
// the server-only ones render blank under the shell, the React-routed ones
// only render a soft 404 — but both are 200s that should not be.
const SERVER_ONLY = ['/river/nie-ma', '/resource/nie-ma', '/layer/nie-ma',
  '/contractor/nie-ma', '/onc/NIEMA', '/oceansites/nie-ma'];
const REACT_ROUTED = ['/seamount/99999999', '/concession/nie-ma', '/vent/nie-ma'];
const ENTITY_PATHS = [...SERVER_ONLY, ...REACT_ROUTED];

// ⛔ /report/ and /claim-report/ CANNOT join ENTITY_PATHS, and the reason is the
// whole point of this block. They are the last two UA-branching routes
// (`if (!isBot(req)) return next()` in server.js), so a human legitimately gets
// the SPA shell there — a "× 2 agents" assertion would fail on correct code.
//
// They were therefore covered by nothing at all, which is how an audit on
// 2026-08-24 measured the shell with a plain curl and filed it as a regression.
// The routes were fine; the coverage was not. These paths run bot-only, through
// every failure mode, because "backend returned nothing" is exactly the case
// that must never come back as 200-with-shell.
const REPORT_PATHS = ['/report/nie-ma', '/claim-report/nie-ma'];
const BOT_ONLY_PATHS = [...ENTITY_PATHS, ...REPORT_PATHS];

// ── A stub backend whose behaviour this script chooses ───────────────────────
let stubMode = 'missing';
let stubHits = 0;
const pathHits = new Map(); // per-path hit count, for the 'flapping' mode below
const stub = createServer((req, res) => {
  stubHits++;
  if (stubMode === 'missing') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    return res.end('{"detail":"not found"}');
  }
  if (stubMode === 'broken') {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    return res.end('{"detail":"boom"}');
  }
  if (stubMode === 'unprocessable') {
    // FastAPI's answer when the path param cannot be coerced — `peak_id` and
    // `vent_id` are typed `int`, so /seamount/zzz never reaches a query.
    res.writeHead(422, { 'Content-Type': 'application/json' });
    return res.end('{"detail":[{"type":"int_parsing","loc":["path","peak_id"]}]}');
  }
  if (stubMode === 'throttled') {
    res.writeHead(429, { 'Content-Type': 'application/json' });
    return res.end('{"detail":"slow down"}');
  }
  // 'flapping': 503 the first time a path is asked for, 200 (falls through to
  // the 'ok' body below) after that. This is the only mode that proves the
  // retry does something — none of the modes above ever answer a literal 502
  // or 503, so a retry scoped to those statuses would never engage and every
  // check in this file would pass while testing nothing at all.
  if (stubMode === 'flapping') {
    const path = req.url.split('?')[0];
    const n = (pathHits.get(path) || 0) + 1;
    pathHits.set(path, n);
    if (n === 1) {
      res.writeHead(503, { 'Content-Type': 'application/json' });
      return res.end('{"detail":"flap"}');
    }
    // second and later hits on this path fall through to 'ok' below
  }
  // 'down502': 502 every time. The final answer must still be 503, and the
  // stub must have been asked exactly twice — not once (no retry) and not
  // three times (a retry that fires more than once, which looks identical
  // from outside to a working retry unless the hit count is checked).
  if (stubMode === 'down502') {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    return res.end('{"detail":"down"}');
  }
  // 'ok' — enough shape for the renderers we exercise.
  const body = {
    meta: {
      title: 'Stub entity', description: 'Stub description',
      canonical_url: 'https://something-rare.com/stub', json_ld: { '@type': 'Thing' },
    },
    river_name: 'Stub', site_label: 'Mouth', record_start: '2000', record_end: '2020',
    lat: 70, lon: 20, discharge: [], biogeochem: [], summary_stats: {},
  };
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
});

function get(path, ua = BOT) {
  return fetch(`http://127.0.0.1:${APP_PORT}${path}`, { headers: { 'User-Agent': ua } });
}

async function waitForApp(proc) {
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${APP_PORT}/health`);
      if (r.ok) return;
    } catch { /* not up yet */ }
    if (proc.exitCode !== null) throw new Error(`server exited early (${proc.exitCode})`);
    await new Promise(r => setTimeout(r, 150));
  }
  throw new Error('server did not come up');
}

async function withApp(apiUrl, fn) {
  const proc = spawn(process.execPath, ['server.js'], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(APP_PORT), VPS_API_URL: apiUrl, ABYSSAL_API_KEY: 'test-key' },
    stdio: ['ignore', 'ignore', 'ignore'],
  });
  try {
    await waitForApp(proc);
    await fn();
  } finally {
    proc.kill('SIGKILL');
    await new Promise(r => proc.on('exit', r));
  }
}

await new Promise(r => stub.listen(STUB_PORT, '127.0.0.1', r));
const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;

// ── 1. Backend says the id does not exist → 404 ──────────────────────────────
stubMode = 'missing';
await withApp(STUB_URL, async () => {
  const wrong = [];
  for (const p of ENTITY_PATHS) {
    for (const [ua, who] of [[BOT, 'bot'], [HUMAN, 'human']]) {
      const r = await get(p, ua);
      if (r.status !== 404) wrong.push(`${p} (${who}) → ${r.status}`);
    }
  }
  check(`unknown id 404s on every entity route (${ENTITY_PATHS.length} × 2 agents)`,
    wrong.length === 0, wrong.join('; '));

  // The bot-gated pair, crawler UA only. A backend that answers "no such id"
  // must reach the crawler as 404 — never the shell, which is what a 200 here
  // would mean.
  const wrongReports = [];
  for (const p of REPORT_PATHS) {
    const r = await get(p);
    if (r.status !== 404) wrongReports.push(`${p} → ${r.status}`);
  }
  check('unknown id 404s on the bot-gated report routes (crawler UA)',
    wrongReports.length === 0, wrongReports.join('; '));

  // The inverse: a human still gets the shell on those two routes. Asserted so
  // that removing the gate is a deliberate change that fails here first, and so
  // the next auditor reading a 200 + shell from curl can see it is by design.
  const humanShell = [];
  for (const p of REPORT_PATHS) {
    const r = await get(p, HUMAN);
    const body = await r.text();
    if (r.status !== 200 || !/<script[^>]+src="\/assets\//.test(body)) {
      humanShell.push(`${p} → ${r.status}`);
    }
  }
  check('a human still gets the SPA shell on the bot-gated report routes',
    humanShell.length === 0, humanShell.join('; '));

  // The body must not be the SPA shell, or React boots over the 404 message and
  // replaces it with nothing — a decorated soft 404, which looks fixed.
  const html = await (await get('/river/nie-ma')).text();
  check('the 404 body carries no client bundle',
    !/<script[^>]+src="\/assets\//.test(html));
  check('the 404 body is noindex', /name="robots"[^>]*content="noindex"/.test(html));
});

// ── 2. Backend is broken (5xx) → 503, never 404 ──────────────────────────────
stubMode = 'broken';
await withApp(STUB_URL, async () => {
  const wrong = [];
  for (const p of BOT_ONLY_PATHS) {
    const r = await get(p);
    // /layer/ is decided from a local table, so a broken backend cannot change
    // its answer — it is legitimately still 404 for an id that does not exist.
    const want = p.startsWith('/layer/') ? 404 : 503;
    if (r.status !== want) wrong.push(`${p} → ${r.status} (want ${want})`);
  }
  check('a 5xx backend yields 503, not 404 and not 200', wrong.length === 0, wrong.join('; '));

  const r = await get('/river/anything');
  check('the 503 carries Retry-After', r.headers.get('retry-after') !== null,
    `Retry-After: ${r.headers.get('retry-after')}`);
});

// ── 2b. A structurally impossible id (422) → 404, NOT 503 ───────────────────
// ⚠️ This case shipped wrong and production caught it. 422 is FastAPI saying
// the id cannot be an id, which is the most certain non-existence answer
// available — no retry can make `zzz` an integer. Answering 503 tells Google
// "come back in 120 s" forever about a URL shape that can never resolve.
//
// The blind spot was in the checker, not only the code: the stub could answer
// 404 or 500 and nothing else, so this case could not be expressed. When a
// test's vocabulary is narrower than the system's, the gap is invisible.
stubMode = 'unprocessable';
await withApp(STUB_URL, async () => {
  const wrong = [];
  for (const p of BOT_ONLY_PATHS) {
    const r = await get(p);
    if (r.status !== 404) wrong.push(`${p} → ${r.status}`);
  }
  check('a 422 (unparseable id) yields 404, not 503', wrong.length === 0, wrong.join('; '));
});

// ── 2c. Rate-limited (429) → 503, NOT 404 ───────────────────────────────────
// The counterweight to 2b. 429 is also 4xx, but it is about US, not about the
// id — treating it as "missing" would delete the corpus from the index because
// we got throttled. This is why the rule is a named set, not "any 4xx".
stubMode = 'throttled';
await withApp(STUB_URL, async () => {
  const wrong = [];
  for (const p of BOT_ONLY_PATHS) {
    if (p.startsWith('/layer/')) continue; // answered from a local table
    const r = await get(p);
    if (r.status !== 503) wrong.push(`${p} → ${r.status}`);
  }
  check('a 429 (throttled) yields 503, not 404', wrong.length === 0, wrong.join('; '));
});

// ── 2d. A transient 502/503 is retried into a 200 ────────────────────────────
// The only assertion in this file that proves the retry does something. Every
// mode above answers 404, 422, 429 or 500 — never a literal 502 or 503 — so a
// retry scoped to RETRY_STATUSES in seo/upstream-fetch.js would never have
// engaged, and this checker would have gone green while testing nothing.
stubMode = 'flapping';
pathHits.clear();
await withApp(STUB_URL, async () => {
  const r = await get('/river/arcticgro:kolyma');
  check('a flapping upstream is retried into a 200',
    r.status === 200, `expected 200 after retry, got ${r.status}`);
});

// ── 2e. A persistent 502 still answers 503, asked exactly twice ─────────────
// The counterweight to 2d: without counting upstream hits, a retry that fires
// three times — or zero times — looks identical from the outside to one that
// fires exactly once, because the final answer is 503 either way.
stubMode = 'down502';
await withApp(STUB_URL, async () => {
  stubHits = 0;
  const r = await get('/river/anything');
  check('a persistent 502 still answers 503',
    r.status === 503 && r.headers.get('retry-after') !== null,
    `expected 503+Retry-After, got ${r.status}`);
  check('the retry fired exactly once (two upstream hits)',
    stubHits === 2, `expected 2 upstream hits, saw ${stubHits}`);
});

// ── 3. Backend not running at all → 503 ──────────────────────────────────────
// "Prove it by actually stopping it — a code path no test can enter is not a
// guarantee." Port 8799 has nothing on it, so this is a real ECONNREFUSED.
await withApp('http://127.0.0.1:8799', async () => {
  const wrong = [];
  for (const p of BOT_ONLY_PATHS) {
    if (p.startsWith('/layer/')) continue; // answered locally, see above
    const r = await get(p);
    if (r.status !== 503) wrong.push(`${p} → ${r.status}`);
  }
  check('an unreachable backend yields 503 on every entity route',
    wrong.length === 0, wrong.join('; '));
});

// ── 4. The working case still works ──────────────────────────────────────────
// Without this, "404 everything" passes checks 1-3.
stubMode = 'ok';
await withApp(STUB_URL, async () => {
  const r = await get('/river/arcticgro:kolyma');
  const html = await r.text();
  check('a known id still returns 200 with server-rendered content',
    r.status === 200 && html.includes('Stub'), `${r.status}, ${html.length} B`);
  check('the working server-only page still emits no bundle',
    !/<script[^>]+src="\/assets\//.test(html));

  // The catch-all must still 404 a genuinely unknown shape, and must still
  // serve the shell where React can route.
  const nonsense = await get('/nie-ma-takiej-strony');
  check('an unknown path shape is still 404', nonsense.status === 404, String(nonsense.status));
  const spa = await get('/about', HUMAN);
  check('a React route still gets the SPA shell', spa.status === 200, String(spa.status));
});

check('the stub backend was actually consulted', stubHits > 0, `${stubHits} requests`);

stub.close();
console.log(failures.length
  ? `\n${failures.length} check(s) failed`
  : '\nEntity status contract holds');
process.exit(failures.length ? 1 : 0);
