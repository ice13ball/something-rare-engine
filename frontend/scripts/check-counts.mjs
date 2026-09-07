#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// Numbers we state in static copy, checked against the backend that owns them.
//
// `index.html`'s bot pre-render said "19,617 underwater mountains" while the
// sitemap carried 37,889 URLs and `/layer/seamounts` printed the live 37,889
// three lines under the same sentence. It was wrong by a factor of 1.9 on the
// site's headline dataset, in public, for months — because no two of those
// three places were ever compared.
//
// ⚠️ It was not a stale subset either: `in_2011` splits 32,340 / 5,549, so the
// figure matched no partition of the data. Worth knowing before "fixing" a
// count by reaching for whichever other number is nearby.
//
// A hard-coded count in static copy is a claim with no owner. Either delete it
// (preferred — /layer/:id already renders the live count) or assert it here.
//
// ⚠️ Comments are stripped before the source is searched, because this script's
// own explanatory text quotes the number it exists to keep out. That exemption
// has a sharp edge, found on production 2026-08-19: an HTML comment in
// index.html DOES ship to every visitor, so the stale figure was still being
// served — invisible to this check by construction. Keep the narrative here, in
// a file nobody downloads, and leave index.html a bare pointer to it.
//
//     node scripts/check-counts.mjs            # needs ABYSSAL_API_KEY
// ─────────────────────────────────────────────────────────────────────────────

import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const API = process.env.VPS_API_URL || 'https://apiv2.something-rare.com';
const KEY = process.env.ABYSSAL_API_KEY || (() => {
  try {
    return (readFileSync(join(ROOT, '.env'), 'utf8').match(/^ABYSSAL_API_KEY=(.*)$/m) || [])[1];
  } catch { return undefined; }
})();

const failures = [];
function check(label, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

const stripHtmlComments = s => s.replace(/<!--[\s\S]*?-->/g, '');
const stripJsComments = s => s.replace(/^\s*\/\/.*$/gm, '');

const indexHtml = stripHtmlComments(readFileSync(join(ROOT, 'index.html'), 'utf8'));
const serverJs = stripJsComments(readFileSync(join(ROOT, 'server.js'), 'utf8'));

// ── Static: the stale figure may not come back ───────────────────────────────
check('the stale seamount figure is not served from index.html', !/19[,.]?617/.test(indexHtml));
check('the stale seamount figure is not served from server.js', !/19[,.]?617/.test(serverJs));

// ── Live: every stated figure must match its owner ───────────────────────────
if (!KEY) {
  // ⛔ "Could not check" is not "checked" — say so loudly rather than exiting 0
  // on a green-looking run. That conflation is the defect this batch is about.
  console.log('\n⚠️  no ABYSSAL_API_KEY — the live comparison did NOT run.');
  console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nStatic checks passed; counts NOT verified');
  process.exit(failures.length ? 1 : 0);
}

async function api(path) {
  const r = await fetch(`${API}${path}`, { headers: { 'X-API-Key': KEY }, signal: AbortSignal.timeout(30000) });
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json();
}

let hubs, layerCounts;
try {
  ({ hubs } = await api('/v1/seo/hubs'));
  ({ layer_counts: layerCounts } = await api('/v1/seo/sitemap/core'));
} catch (err) {
  console.error(`FAIL  cannot reach ${API} — ${err.message}`);
  process.exit(1);
}

// 1. The bot pre-render's per-dataset counts, against the hub totals.
const CLAIMS = [
  { label: 'seamounts', kind: 'seamount', re: /<strong>Seamounts<\/strong>\s*—\s*([\d,]+)/ },
  { label: 'vents',     kind: 'vent',     re: /<strong>Hydrothermal Vents<\/strong>\s*—\s*([\d,]+)/ },
];
for (const c of CLAIMS) {
  const m = indexHtml.match(c.re);
  const stated = m ? Number(m[1].replace(/,/g, '')) : null;
  const live = (hubs.find(h => h.kind === c.kind) || {}).total;
  check(`index.html's ${c.label} count matches the backend`,
    stated !== null && live !== undefined && stated === live,
    `stated ${stated?.toLocaleString() ?? '(not found)'} · live ${live?.toLocaleString() ?? '(no hub)'}`);
}

// 2. LAYER_META descriptions that open with a number. These sit directly above
//    a live "Currently tracking N features" line on the same page, so a stale
//    one does not merely age — it contradicts the paragraph beneath it.
const metaBlock = (serverJs.match(/const LAYER_META = \{[\s\S]*?\n\};/) || [''])[0];
const stated = [...metaBlock.matchAll(/'([a-z0-9-]+)':\s*\{[^}]*?desc:\s*'([\d,]+)\s/g)]
  .map(m => ({ id: m[1], n: Number(m[2].replace(/,/g, '')) }));
const drifted = stated.filter(s => layerCounts?.[s.id] !== s.n)
  .map(s => `${s.id}: says ${s.n.toLocaleString()}, live ${layerCounts?.[s.id]?.toLocaleString() ?? '(none)'}`);
check(`every hard-coded LAYER_META count matches the backend (${stated.length} found)`,
  drifted.length === 0, drifted.join('; '));

console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nStated counts match the backend');
process.exit(failures.length ? 1 : 0);
