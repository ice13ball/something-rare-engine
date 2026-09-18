// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { createProxyMiddleware } from 'http-proxy-middleware';

/**
 * The generic `/api/*` → VPS_API_URL proxy, extracted from server.js so it can
 * be unit-tested in isolation (server.js self-starts `app.listen()` at import
 * time and installs process-level uncaughtException/unhandledRejection
 * handlers that call `process.exit(1)` — not something a test runner should
 * import directly).
 *
 * ── The 2026-09-18 incident, and why this file looks the way it does ──────
 *
 * This proxy used to set BOTH `timeout` (the INCOMING, client-facing socket —
 * i.e. Googlebot/browser ↔ this BFF) and `proxyTimeout` (the OUTGOING socket —
 * this BFF ↔ VPS_API_URL) to the same 120000ms. Two independent defects came
 * out of that one number:
 *
 * 1. Cloud Run's own request deadline is 30s (`--timeout=30` in
 *    deploy-gcp.yml). 120000ms is twelve times that, so Cloud Run always cut
 *    the connection first and returned its OWN bare 504 — our `error` handler
 *    below never got to run, so the client never saw the JSON body or the
 *    Retry-After header it sets.
 * 2. Setting `timeout` and `proxyTimeout` to the SAME value is its own bug,
 *    independent of Cloud Run: it races the two timers. Reproduced locally
 *    with a slow upstream and both at 500ms — the request fails with a raw
 *    ECONNRESET instead of the clean response the `error` handler writes.
 *    Dropping `timeout` entirely (Cloud Run already bounds the client-facing
 *    side; we do not need to duplicate that) and keeping only `proxyTimeout`
 *    fixes both at once.
 *
 * ⛔ "Missing" and "broken" must never share a code path (see
 * .claude/rules/subsystems/seo-ssr-sitemap.md). A 4xx from VPS_API_URL is a
 * statement about the request (bad id, bad shape, …) and passes through
 * untouched. A 5xx, a timeout, or a connection failure is OUR failure to hide
 * behind — rewritten to 503 + Retry-After so callers can retry rather than
 * conclude the resource itself is broken.
 */
export function createApiProxy({ target, apiKey, proxyTimeoutMs = 20000 }) {
  return createProxyMiddleware({
    target,
    changeOrigin: true,
    pathRewrite: { '^/api': '' },
    // 20s default — comfortably under Cloud Run's 30s deadline, leaving
    // headroom to write the 503 back before Cloud Run's own timeout fires.
    proxyTimeout: proxyTimeoutMs,
    on: {
      proxyReq: (proxyReq, req) => {
        console.log(`Proxying: ${req.method} ${req.url} -> ${target}${proxyReq.path}`);
        if (apiKey) {
          proxyReq.setHeader('X-API-Key', apiKey);
        }
        // ⛔ ALWAYS ask the origin for gzip, whatever the client asked for.
        //
        // Cloud Run refuses a response over 32 MiB and enforces it on the bytes
        // it RECEIVES from the origin. /v1/map/argo/trails is 40.1 MB
        // uncompressed and 4.69 MB gzipped, so the header decides whether the
        // request works at all. Measured 2026-09-09:
        //
        //     curl --compressed  -> 200, 4,687,536 B
        //     curl (no header)   -> 500, 0 B
        //
        // Browsers always advertise gzip, so the map looked fine while every
        // script, curl and API consumer got a 500. Forwarding the client's
        // header made that difference invisible from here — the origin hop is
        // ours, and it should never depend on what a caller happened to send.
        // Express `compression()` re-encodes for the client, so a client that
        // cannot take gzip still gets plain bytes.
        proxyReq.setHeader('Accept-Encoding', 'gzip');
      },
      proxyRes: (proxyRes, req) => {
        console.log(`VPS response: ${proxyRes.statusCode} for ${req.url}`);
        if (proxyRes.statusCode >= 500) {
          proxyRes.statusCode = 503;
          proxyRes.headers['retry-after'] = '60';
        }
      },
      error: (err, req, res) => {
        console.error('Proxy Error:', err);
        // A response can already be underway (headers flushed, body partially
        // streamed) if the upstream connection dropped mid-response rather
        // than failing to connect at all — writing again would throw.
        if (res.headersSent) return;

        const body = JSON.stringify({
          error: 'Upstream temporarily unavailable',
          details: err.message,
        });
        // ⛔ The handler that reports the failure must not BE a failure.
        // `res.status()/.set()/.json()` are Express's, not node's. Mounted
        // under `app.use('/api', …)` they are there — but this handler also
        // runs for requests that never reached Express's response wrapper, and
        // when it threw (`TypeError: res.status is not a function`, caught by
        // a test on 2026-09-18) nothing was ever written: the client hung until
        // ITS timeout, which is precisely the 504 this file exists to prevent.
        if (typeof res.status === 'function') {
          res.status(503).set('Retry-After', '60').type('application/json').send(body);
        } else {
          res.writeHead(503, {
            'Retry-After': '60',
            'Content-Type': 'application/json',
          });
          res.end(body);
        }
      },
    },
  });
}
