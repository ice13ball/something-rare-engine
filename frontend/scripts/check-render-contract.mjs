#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// The dual-render contract.
//
// Every server-rendered page belongs to one of two declared categories
// (seo/route-categories.js) and that category decides whether its HTML carries
// the client bundle. This checker exists because BOTH halves of that contract
// were broken at once on 2026-08-18, undetectably:
//
//   - `wrapHtml` hardcoded Vite's DEV entry `/src/main.tsx`, which 404s in
//     production. It shipped on every SSR page for months.
//   - Six routes were un-gated so humans could read them, which handed humans
//     that broken tag. React never booted on them.
//
// Two lessons are encoded here as assertions:
//
//   1. CHECK BOTH USER AGENTS. The bug was invisible from the bot side alone —
//      "wasted crawl request" and "the application does not start" produce the
//      same HTML and differ only in who receives it.
//   2. FETCH THE ASSET. A script tag that looks right proves nothing; the
//      previous one looked entirely plausible.
//
// Static assertions run always. Live assertions need a running server:
//     node scripts/check-render-contract.mjs [baseUrl]
// ─────────────────────────────────────────────────────────────────────────────

import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

import { parseBuiltAssets } from '../seo/render-page.js';
import { REACT_ROUTES, SERVER_ONLY_ROUTES, hydrates } from '../seo/route-categories.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const BASE = (process.argv[2] || '').replace(/\/+$/, '');
const BOT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)';
const HUMAN = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

const failures = [];
function check(label, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

// ── 1. The resolver, including its failure path ──────────────────────────────
{
  const dist = readFileSync(join(ROOT, 'dist', 'index.html'), 'utf8');
  const parsed = parseBuiltAssets(dist);
  check(
    'entry resolves to the hashed bundle in dist/index.html',
    /^\/assets\/.+\.js$/.test(parsed.entry) && dist.includes(parsed.entry),
    parsed.entry,
  );
  check('resolved entry is not the dev path', parsed.entry !== '/src/main.tsx', parsed.entry);

  // Prove it can go red. A resolver that silently fell back to /src/main.tsx
  // would restore the original bug and hide it again, so the throw IS the fix.
  let threw = false;
  try {
    parseBuiltAssets('<html><head><script type="module" src="/src/main.tsx"></script></head></html>');
  } catch { threw = true; }
  check('resolver throws when dist has no built entry (failure path proven)', threw);

  // Locks the regression the hardcoded path caused: a rebuild changes the hash,
  // and nothing may need editing for the site to keep working.
  check(
    'nothing pins a specific build hash',
    !readFileSync(join(ROOT, 'seo', 'render-page.js'), 'utf8').match(/\/assets\/index-[A-Za-z0-9_-]+\./),
    'render-page.js must derive the hash, never contain one',
  );
}

// ── 2. The two categories cover every route, and match App.tsx ───────────────
{
  const app = readFileSync(join(ROOT, 'src', 'App.tsx'), 'utf8');
  const declared = [...app.matchAll(/<Route\s+path="([^"]+)"/g)].map(m => m[1]);
  check('App.tsx routes were found at all', declared.length > 5, `${declared.length} routes`);

  // Every React route must be recognised as hydrating. A route added to App.tsx
  // without being added here would be served the no-script shell and never boot.
  const sample = p => p.replace(/:[^/]+/g, 'x');
  const missed = declared.map(sample).filter(p => !hydrates(p));
  check('every App.tsx route is in REACT_ROUTES', missed.length === 0, missed.join(' '));

  // And the converse: nothing declared server-only may be routable by React,
  // because then the no-script shell would deny it its own application.
  const contradictions = declared.map(sample)
    .filter(p => SERVER_ONLY_ROUTES.some(re => re.test(p)));
  check('no App.tsx route is marked server-only', contradictions.length === 0, contradictions.join(' '));

  check('categories are disjoint by construction',
    !REACT_ROUTES.some(a => SERVER_ONLY_ROUTES.some(b => String(a) === String(b))));
}

// ── 3. Live: both agents, every SSR route ────────────────────────────────────
if (!BASE) {
  console.log('\n(no base URL given — live checks skipped; pass one to run them)');
} else {
  const fetchAs = (p, ua) => fetch(BASE + p, { headers: { 'User-Agent': ua } });
  const scriptsIn = html => [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map(m => m[1]);

  // Real ids, harvested from the hubs rather than guessed. A guessed id 404s
  // into the SPA fallback, which is byte-identical to a route that never ran —
  // so guessing produces a green check that tested nothing.
  const HUBS = ['/onc', '/oceansites', '/river', '/resource', '/report', '/layer', '/vent', '/concession', '/seamount'];
  const routes = new Set(['/about', '/privacy', '/terms', '/api-docs', '/blog', '/contractors', ...HUBS]);
  for (const hub of HUBS) {
    const html = await (await fetchAs(hub, BOT)).text();
    const m = html.match(/href="https:\/\/something-rare\.com(\/[a-z-]+\/[^"]+)"/);
    if (m) routes.add(decodeURI(m[1]));
  }

  const devPathOffenders = [];
  const categoryOffenders = [];
  const emitted = new Set();

  for (const p of [...routes]) {
    for (const [ua, who] of [[BOT, 'bot'], [HUMAN, 'human']]) {
      const res = await fetchAs(p, ua);
      const html = await res.text();
      if (html.includes('/src/main.tsx')) devPathOffenders.push(`${p} (${who})`);

      const srcs = scriptsIn(html).filter(s => s.startsWith('/assets/'));
      srcs.forEach(s => emitted.add(s));

      // A page that fell through to the SPA shell is not this route's output —
      // exclude it, or the category assertion tests the shell instead.
      const fellThrough = html.includes('Pre-render content for search engine crawlers');
      if (fellThrough) continue;
      const wants = hydrates(p);
      if (wants !== (srcs.length > 0)) {
        categoryOffenders.push(`${p} (${who}) wants hydrate=${wants}, emitted ${srcs.length} bundle(s)`);
      }
    }
  }

  check(`no route serves the dev entry to either agent (${routes.size} routes × 2)`,
    devPathOffenders.length === 0, devPathOffenders.join('; '));
  check('every route matches its declared category',
    categoryOffenders.length === 0, categoryOffenders.join('; '));

  // Fetch what was emitted. This is the assertion the old code would have failed.
  const dead = [];
  for (const src of emitted) {
    const r = await fetchAs(src, HUMAN);
    if (r.status !== 200) dead.push(`${src} → ${r.status}`);
  }
  check(`every emitted bundle is 200 (${emitted.size} distinct)`, dead.length === 0, dead.join('; '));

  // The SSR pages and the SPA shell must name the SAME entry. Compare against
  // the SHELL THE SERVER ITSELF SERVES, never against this machine's dist —
  // a remote server runs its own build with its own hash, so comparing to a
  // local BUILT_ASSETS fails on a correct deploy and passes only by accident
  // when the two happen to match. (Same trap fixed 2026-08-17: a check that
  // read local state and pointed at a remote host was testing the wrong
  // machine.)
  const shell = await (await fetchAs('/', HUMAN)).text();
  const shellEntry = (shell.match(/<script[^>]+src="(\/assets\/[^"]+\.js)"/) || [])[1];
  check('SSR pages emit the same bundle as the SPA shell',
    emitted.size === 0 || (shellEntry && emitted.has(shellEntry)),
    `SSR: ${[...emitted].join(' ') || '(none)'} | shell: ${shellEntry}`);
}

console.log(failures.length
  ? `\n${failures.length} check(s) failed`
  : `\nRender contract holds${BASE ? ` against ${BASE}` : ' (static checks only)'}`);
process.exit(failures.length ? 1 : 0);
