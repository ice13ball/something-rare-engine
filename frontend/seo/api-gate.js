// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { readFileSync } from 'node:fs';

/**
 * Gate in front of the `/api/*` proxy (seo/api-proxy.js).
 *
 * The proxy attaches the internal ABYSSAL_API_KEY to every request it
 * forwards. Before 2026-10-20 it forwarded EVERY method and EVERY path, so
 * each of the ~224 key-protected backend routes was anonymously public through
 * something-rare.com — e.g. `/api/v1/stats/pageviews` answered 200 while the
 * same route on apiv2 without a key answers 403, and `/api/v2/export/*` ran on
 * the internal key, without the caller's quota (security audit 2026-10-20,
 * A-01/A-04).
 *
 * Now only the routes the site itself calls pass (`api-allowlist.json`: one
 * anchored regex per backend route template, built from the frontend code and
 * 15 days of real BFF traffic). Anything else gets 404 and never reaches the
 * VPS with our key. A new frontend call to a new backend route needs a new
 * entry there — otherwise it 404s on the map, which is loud, not silent.
 *
 * Per-IP limits sit on top: a generous one for everything (a map pan bursts
 * tiles) and tighter ones for the POSTs that create work on the VPS.
 */

const ALLOWLIST = JSON.parse(
  readFileSync(new URL('./api-allowlist.json', import.meta.url), 'utf8'),
).map((e) => ({ method: e.method, re: new RegExp(e.regex) }));

// `req.path` is NOT percent-decoded. An encoded slash, backslash or dot
// segment could match an allowlisted regex here and then be normalised by
// nginx/uvicorn into a different route upstream — refuse them outright.
const SUSPICIOUS = /%2f|%5c|%2e|\\|\/\.{1,2}(\/|$)|\/\//i;

/** Requests per IP per minute. `limit` is per Cloud Run instance. */
const LIMITS = [
  { name: 'reports', method: 'POST', re: /^\/v[12]\/reports\//, limit: 20 },
  { name: 'feedback', method: 'POST', re: /^\/v1\/feedback$/, limit: 10 },
  { name: 'pageview', method: 'POST', re: /^\/v1\/pageview$/, limit: 120 },
  { name: 'all', method: null, re: /^/, limit: 3000 },
];
const WINDOW_MS = 60_000;

/**
 * The visitor's IP as Cloud Run's front end saw it. Google APPENDS the client
 * address to X-Forwarded-For, so the LAST entry is the one a client cannot
 * forge (`req.ip` under `trust proxy` takes the first, which a client can set).
 */
export function clientIp(req) {
  const xff = req.headers['x-forwarded-for'];
  if (typeof xff === 'string' && xff.trim()) {
    const parts = xff.split(',').map((s) => s.trim()).filter(Boolean);
    if (parts.length) return parts[parts.length - 1];
  }
  return req.socket?.remoteAddress || 'unknown';
}

/** null = unknown path; otherwise the methods the path allows. */
function allowedMethods(path) {
  const methods = new Set();
  for (const e of ALLOWLIST) {
    if (e.re.test(path)) {
      methods.add(e.method);
      if (e.method === 'GET') methods.add('HEAD');
    }
  }
  return methods.size ? methods : null;
}

export function createApiGate({ now = () => Date.now() } = {}) {
  // name -> Map(ip -> { start, count })
  const windows = new Map(LIMITS.map((l) => [l.name, new Map()]));
  let lastSweep = now();

  function sweep(t) {
    if (t - lastSweep < WINDOW_MS) return;
    lastSweep = t;
    for (const m of windows.values()) {
      for (const [ip, w] of m) if (t - w.start >= WINDOW_MS) m.delete(ip);
    }
  }

  function overLimit(ip, method, path, t) {
    for (const l of LIMITS) {
      if (l.method && l.method !== method) continue;
      if (!l.re.test(path)) continue;
      const m = windows.get(l.name);
      let w = m.get(ip);
      if (!w || t - w.start >= WINDOW_MS) {
        w = { start: t, count: 0 };
        m.set(ip, w);
      }
      w.count += 1;
      if (w.count > l.limit) return Math.ceil((w.start + WINDOW_MS - t) / 1000);
    }
    return 0;
  }

  return function apiGate(req, res, next) {
    const path = req.path;
    // Marks OUR refusals so they are never confused with the backend's own 404.
    const block = () => res.set('X-Api-Gate', 'blocked');
    if (SUSPICIOUS.test(path)) {
      block();
      return res.status(404).json({ detail: 'Not Found' });
    }
    const methods = allowedMethods(path);
    if (!methods) {
      block();
      return res.status(404).json({ detail: 'Not Found' });
    }
    if (!methods.has(req.method)) {
      block();
      return res.status(405).set('Allow', [...methods].join(', ')).json({ detail: 'Method Not Allowed' });
    }
    const t = now();
    sweep(t);
    const retryAfter = overLimit(clientIp(req), req.method, path, t);
    if (retryAfter > 0) {
      block();
      return res
        .status(429)
        .set('Retry-After', String(retryAfter))
        .json({ detail: 'Too Many Requests' });
    }
    return next();
  };
}
