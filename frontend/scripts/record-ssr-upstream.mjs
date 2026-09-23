// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Records the backend answers that server.js needs to render one real page of
// every server-rendered kind, for src/__tests__/ga4-bootstrap-on-every-page.test.ts.
//
// How: a local stub stands in for VPS_API_URL and forwards each request to the
// public BFF (https://something-rare.com/api/...), which adds its own key. The
// real server.js runs against that stub while every route in SSR_ROUTES is
// requested once; each upstream answer is saved. Arrays longer than 50 are cut
// to 50 so the fixture stays small and keeps its shape.
//
// Usage (needs a built dist/):  node scripts/record-ssr-upstream.mjs
import http from 'node:http';
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SSR_ROUTES, FIXTURE_PATH, FORCE_OUTAGE, USER_AGENTS } from '../src/__tests__/ssrRoutes.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, '..');
const PUBLIC_BFF = 'https://something-rare.com/api';

function trim(v) {
  if (Array.isArray(v)) return v.slice(0, 50).map(trim);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, trim(x)]));
  return v;
}

const recorded = {};
const stub = http.createServer(async (req, res) => {
  if (req.url.includes(FORCE_OUTAGE)) { res.writeHead(500); res.end(); return; }
  const r = await fetch(PUBLIC_BFF + req.url, { headers: { 'User-Agent': 'ssr-fixture-recorder' } });
  const type = r.headers.get('content-type') || '';
  let body = await r.text();
  if (type.includes('json')) {
    try { body = JSON.stringify(trim(JSON.parse(body))); } catch { /* keep raw */ }
  }
  recorded[req.url] = { status: r.status, type, body };
  res.writeHead(r.status, { 'content-type': type });
  res.end(body);
});
await new Promise((ok) => stub.listen(0, '127.0.0.1', ok));

const port = 3900 + Math.floor(process.pid % 90);
const server = spawn('node', ['server.js'], {
  cwd: FRONTEND,
  env: { ...process.env, PORT: String(port), VPS_API_URL: `http://127.0.0.1:${stub.address().port}` },
  stdio: 'ignore',
});
try {
  for (let i = 0; i < 50; i++) {
    try { await fetch(`http://127.0.0.1:${port}/health`); break; } catch { await new Promise((r) => setTimeout(r, 200)); }
  }
  for (const route of SSR_ROUTES) {
    for (const [who, ua] of Object.entries(USER_AGENTS)) {
      const r = await fetch(`http://127.0.0.1:${port}${route.path}`, { redirect: 'manual', headers: { 'User-Agent': ua } });
      console.log(r.status, who, route.path);
    }
  }
} finally {
  server.kill();
  stub.close();
}
mkdirSync(dirname(FIXTURE_PATH), { recursive: true });
writeFileSync(FIXTURE_PATH, JSON.stringify(recorded, null, 1));
console.log(`${Object.keys(recorded).length} upstream answers -> ${FIXTURE_PATH}`);
