// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Same-origin copy of the API's OpenAPI document, for /api-docs.
//
// Why: apiv2.something-rare.com/robots.txt is "Disallow: /", so Google's
// renderer may not fetch apiv2/openapi.json. The Scalar reference on /api-docs
// then rendered an empty frame and Search Console filed the page as "Soft 404"
// (crawl of 2026-11-23, reported 2026-11-26). Served from this origin
// (robots "Allow: /") the renderer can load it.
//
// ⛔ The document's `servers` stays https://apiv2.something-rare.com, so Try-it
// still calls apiv2 directly with the user's own key, never the /api BFF proxy.
//
// The last good copy is kept: an apiv2 outage serves the previous document;
// with no copy at all the answer is 503 + Retry-After, never an empty 200.

import { fetchUpstream } from './upstream-fetch.js';

const TTL_MS = 60 * 60 * 1000;
let cached = null; // { spec, fetchedAt }

export async function getOpenApiSpec(url) {
  if (cached && Date.now() - cached.fetchedAt < TTL_MS) return cached.spec;
  try {
    const spec = await fetchUpstream(url, { timeoutMs: 10000 });
    if (spec && spec.paths) cached = { spec, fetchedAt: Date.now() };
  } catch (err) {
    console.error('openapi mirror: fetch failed:', err.message);
  }
  return cached ? cached.spec : null;
}

export function createOpenApiHandler(url) {
  return async (_req, res) => {
    const spec = await getOpenApiSpec(url);
    res.set('X-Robots-Tag', 'noindex');
    if (!spec) return res.status(503).set('Retry-After', '300').json({ error: 'temporarily unavailable' });
    res.set('Cache-Control', 'public, max-age=3600').json(spec);
  };
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// Endpoint list for the server snapshot of /api-docs, grouped by tag, so the
// pre-JS HTML carries the reference itself and not only a heading.
export async function renderEndpointList(url) {
  const spec = await getOpenApiSpec(url);
  if (!spec) return '';
  const groups = new Map();
  for (const [path, ops] of Object.entries(spec.paths)) {
    for (const [method, op] of Object.entries(ops)) {
      if (!op || typeof op !== 'object' || !op.summary) continue;
      const tag = (op.tags && op.tags[0]) || 'Other';
      if (!groups.has(tag)) groups.set(tag, []);
      groups.get(tag).push(`<li><code>${esc(method.toUpperCase())} ${esc(path)}</code> — ${esc(op.summary)}</li>`);
    }
  }
  if (!groups.size) return '';
  let html = '<h2>Endpoints</h2>';
  for (const [tag, items] of groups) html += `<h3>${esc(tag)}</h3><ul>${items.join('')}</ul>`;
  return html;
}
