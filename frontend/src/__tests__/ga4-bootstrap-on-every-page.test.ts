// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Every page something-rare.com serves must load the GA4 + Consent Mode v2
// bootstrap exactly once, with the consent default ahead of the loader and the
// loader ahead of `config`.
//
// Until 2026-09-23 only `/` did. Server-rendered pages sent nothing to GA4, so
// search traffic was invisible: /seamount/4873694 had 18 Search Console clicks
// (07-20.09) and 0 GA4 page views.
//
// This test runs the REAL server.js — not a renderer called in isolation — and
// requests every HTML-producing path in ssrRoutes.mjs as a browser and as
// Googlebot. The backend is a replay of answers recorded from production by
// scripts/record-ssr-upstream.mjs. The server runs from a temp copy whose
// dist/index.html is the SOURCE index.html (Vite keeps the marked block as is),
// because the gate does not build dist/ before vitest.
//
// The recorded answers are third-party data and are withheld from the public
// mirror (scripts/export-public.sh, NEVER_RULES); without them this skips.
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { SSR_ROUTES, FIXTURE_PATH, FORCE_OUTAGE, USER_AGENTS } from './ssrRoutes.mjs';

const FRONTEND = path.resolve(__dirname, '../..');
const MEASUREMENT = 'G-S5HR4WT0ZG';
const LOADER = `googletagmanager.com/gtag/js?id=${MEASUREMENT}`;
const CONFIG = `gtag('config', '${MEASUREMENT}')`;
const CONSENT_DEFAULT = "gtag('consent', 'default'";

const haveFixture = fs.existsSync(FIXTURE_PATH);

function count(hay: string, needle: string): number {
  return hay.split(needle).length - 1;
}

type Answer = { status: number; body: string };
const answers = new Map<string, Answer>();
let server: ChildProcess | undefined;
let stub: http.Server | undefined;
let tmp = '';

beforeAll(async () => {
  if (!haveFixture) return;
  const recorded: Record<string, { status: number; type: string; body: string }> =
    JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));

  stub = http.createServer((req, res) => {
    const hit = recorded[req.url ?? ''];
    if (!hit || (req.url ?? '').includes(FORCE_OUTAGE)) { res.writeHead(500); res.end(); return; }
    res.writeHead(hit.status, { 'content-type': hit.type });
    res.end(hit.body);
  });
  await new Promise<void>((ok) => stub!.listen(0, '127.0.0.1', ok));

  // A deployable copy: what the Dockerfile ships (server.js, seo/, package.json,
  // node_modules, dist/), with dist/index.html built from the source index.html.
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ga4-ssr-'));
  fs.copyFileSync(path.join(FRONTEND, 'server.js'), path.join(tmp, 'server.js'));
  fs.copyFileSync(path.join(FRONTEND, 'package.json'), path.join(tmp, 'package.json'));
  fs.cpSync(path.join(FRONTEND, 'seo'), path.join(tmp, 'seo'), { recursive: true });
  fs.symlinkSync(path.join(FRONTEND, 'node_modules'), path.join(tmp, 'node_modules'));
  fs.mkdirSync(path.join(tmp, 'dist', 'assets'), { recursive: true });
  const source = fs.readFileSync(path.join(FRONTEND, 'index.html'), 'utf8');
  const built = source.replace(/<script type="module"[^>]*src="\/src\/main\.tsx"[^>]*><\/script>/,
    '<script type="module" crossorigin src="/assets/index-test.js"></script>');
  expect(built).not.toBe(source);
  fs.writeFileSync(path.join(tmp, 'dist', 'index.html'), built);
  fs.writeFileSync(path.join(tmp, 'dist', 'assets', 'index-test.js'), '');

  const port = 4100 + (process.pid % 800);
  server = spawn('node', ['server.js'], {
    cwd: tmp,
    env: { ...process.env, PORT: String(port), VPS_API_URL: `http://127.0.0.1:${(stub.address() as { port: number }).port}` },
    stdio: 'ignore',
  });
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try { await fetch(`${base}/health`); break; } catch { await new Promise((r) => setTimeout(r, 100)); }
  }
  for (const route of SSR_ROUTES) {
    for (const [who, ua] of Object.entries(USER_AGENTS)) {
      const r = await fetch(base + route.path, { redirect: 'manual', headers: { 'User-Agent': ua } });
      answers.set(`${who} ${route.path}`, { status: r.status, body: await r.text() });
    }
  }
}, 60_000);

afterAll(() => {
  server?.kill();
  stub?.close();
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
});

const cases = SSR_ROUTES.flatMap((route) =>
  Object.keys(USER_AGENTS).map((who) => ({ ...route, who, key: `${who} ${route.path}` })));

describe.skipIf(!haveFixture)('GA4 bootstrap on every server-rendered page', () => {
  it('rendered every listed path for both user agents', () => {
    expect(answers.size).toBe(cases.length);
  });

  it.each(cases.filter((c) => c.kind === 'document'))('$who $path: tag exactly once, consent first', ({ key }) => {
    const { body } = answers.get(key)!;
    expect(body).toMatch(/<html[\s>]/);
    expect(count(body, LOADER)).toBe(1);
    expect(count(body, CONFIG)).toBe(1);
    const consent = body.indexOf(CONSENT_DEFAULT);
    expect(consent).toBeGreaterThan(-1);
    expect(consent).toBeLessThan(body.indexOf(LOADER));
    expect(body.indexOf(LOADER)).toBeLessThan(body.indexOf(CONFIG));
  });

  it.each(cases.filter((c) => c.kind === 'fragment'))('$who $path: an error fragment, not a page', ({ key }) => {
    const { status, body } = answers.get(key)!;
    expect(status).toBeGreaterThanOrEqual(400);
    expect(body).not.toMatch(/<html[\s>]/);
    expect(count(body, MEASUREMENT)).toBe(0);
  });

  it.each(cases.filter((c) => c.kind === 'embed'))('$who $path: the third-party widget stays untagged', ({ key }) => {
    const { body } = answers.get(key)!;
    expect(count(body, MEASUREMENT)).toBe(0);
  });
});
