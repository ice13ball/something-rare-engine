// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import express from 'express';
import compression from 'compression';
import expressStaticGzip from 'express-static-gzip';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { config } from 'dotenv';
import { SPA_PATHS, hydrates } from './seo/route-categories.js';
import { canonicalUrl, normaliseJsonLd, normaliseUrl } from './seo/urls.js';
import { forceHttpsMiddleware, wwwRedirectMiddleware } from './seo/canonical-hosts.js';
import { renderSeoPage, fetchSeoData, renderBlogIndex, renderBlogArticle, renderContractor, renderResource, renderVentReport, renderRiverPage, wrapHtml, siteCitation, renderHubPage, hubNavHtml, BackendUnavailable, EntityGone } from './seo/render-page.js';
import { fetchUpstream } from './seo/upstream-fetch.js';
import { createApiProxy } from './seo/api-proxy.js';

config();

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3000;
// ⚠️ The fallback used to be api.something-rare.com, whose DNS record pointed
// at a VPS that was retired and answered on no port at all. An unset
// VPS_API_URL would therefore have sent every request to a dangling name — and
// the record itself was a subdomain-takeover risk, so it was deleted on
// 2026-08-24. apiv2 is the live host; keep this in step with it.
const VPS_API_URL = process.env.VPS_API_URL || 'https://apiv2.something-rare.com';
const ABYSSAL_API_KEY = process.env.ABYSSAL_API_KEY;
const SITE = 'https://something-rare.com';
const ORG_SCHEMA = { '@type': 'Organization', name: 'Abyssal Claims', url: SITE };

// Classic search + social crawlers, AND AI-search crawlers (ChatGPT, Perplexity,
// Claude, Apple, Amazon, etc.). AI engines fetch with their own UAs — if they fall
// through to the SPA shell they index nothing, so they MUST be served SSR HTML too.
// Google AI Overviews / Bing Copilot already ride googlebot/bingbot.
const BOT_UA = /googlebot|bingbot|yandex|baiduspider|duckduckbot|slurp|facebot|ia_archiver|semrush|ahref|mj12bot|dotbot|gptbot|oai-searchbot|chatgpt-user|claudebot|claude-searchbot|claude-user|anthropic-ai|perplexitybot|perplexity-user|google-extended|cohere-ai|ccbot|bytespider|amazonbot|applebot|meta-externalagent|meta-externalfetcher|diffbot|youbot|timpibot|imagesiftbot/i;
function isBot(req) {
  return BOT_UA.test(req.headers['user-agent'] || '');
}

// ── The three outcomes an entity route may have ───────────────────────────
// An entity URL of the right shape has exactly three honest answers, and until
// 2026-08-18 it could only give one of them:
//
//   the backend says this id does not exist  → 404 + noindex
//   the backend could not be asked           → 503 + Retry-After
//   the backend answered                     → 200
//
// Before: every non-200 collapsed to `next()`, which reaches the SPA catch-all,
// which answers **200 with the empty shell**. So a typo'd id was a soft 404
// (bad), and a backend outage turned the whole ~40,300-URL corpus into
// 200-with-no-content (far worse — Google reads that as a statement about the
// pages, not about the server, and de-indexes them).
//
// ⛔ Never answer 404 for a failure you did not diagnose. "Missing" and
// "broken" collapsing into one sentinel is the original defect; a fix that
// returns 404 for both only replaces silent de-indexing with confident
// de-indexing.
function sendNotFound(res, message, backHref, backLabel) {
  res.status(404).type('html').send(wrapHtml(
    '<title>Not found | Abyssal Claims</title><meta name="robots" content="noindex" />',
    '<main style="max-width:640px;margin:0 auto;padding:2rem;font-family:system-ui,sans-serif;color:#c9d1d9">'
    + `<h1>404 — not found</h1><p>${escapeHtml(message)}</p>`
    + `<p><a href="${escapeHtml(backHref)}" style="color:#22d3ee">${escapeHtml(backLabel)}</a>`
    + ' · <a href="/" style="color:#22d3ee">Interactive map</a></p></main>',
    // A 404 body, not a route. Booting React over it would replace the message
    // with whatever App.tsx renders for an unroutable path, i.e. nothing.
    { hydrate: false },
  ));
}

// `Retry-After` is the half that does the work: it is the difference between
// "come back" and "this page is blank now". Same shape as the hub 503 below.
function sendUnavailable(res, what) {
  res.status(503).type('html').set('Retry-After', '120').send(
    '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">'
    + '<title>Temporarily unavailable | Abyssal Claims</title>'
    + `<p>${escapeHtml(what)} is temporarily unavailable. <a href="/">Go to the map</a>.</p>`);
}

/**
 * Wraps an entity handler so a throw can never reach Express's default 500
 * handler (which sends an HTML stack trace with no robots directive).
 *
 * Everything that throws lands on 503, deliberately: at this point we know the
 * id was not diagnosed as missing, and an undiagnosed failure is ours.
 */
/**
 * The same discriminator as `fetchJsonOrThrow` in seo/render-page.js, for the
 * handlers that fetch the backend directly rather than through renderSeoPage.
 * Both now delegate to the shared `fetchUpstream` (seo/upstream-fetch.js) so
 * two copies can no longer disagree about what 422 or a transient 503 means.
 */
async function fetchEntity(url, timeoutMs = 5000) {
  return fetchUpstream(url, {
    timeoutMs,
    fetchImpl: (u, opts) => fetch(u, { ...opts, headers: { 'X-API-Key': ABYSSAL_API_KEY } }),
  });
}

function entityRoute(what, handler) {
  return async (req, res, next) => {
    try {
      await handler(req, res, next);
    } catch (err) {
      console.error(`${what} (${req.path}) failed:`,
        err instanceof BackendUnavailable ? err.message : err);
      if (!res.headersSent) sendUnavailable(res, what);
    }
  };
}

if (!ABYSSAL_API_KEY) {
  console.warn('WARNING: ABYSSAL_API_KEY is not set. Proxy will likely fail authentication at VPS.');
}

const app = express();

// Trust Render's reverse proxy so req.protocol and X-Forwarded-Proto are accurate.
app.enable('trust proxy');

// ── Security headers ─────────────────────────────────────────────────────
//
// Measured 2026-08-24: this origin sent NONE of the six standard security
// headers, while apiv2 (nginx) and the sister site (Cloudflare) sent all six.
// Cloud Run puts nothing in front of us, so they have to be set here — in code,
// where they are reviewable and testable, rather than in Cloud Run config.
//
// ⛔ This is NOT an SEO change. Page experience is not a ranking system; nothing
// below will move a position. The reason is clickjacking: without a framing
// rule anyone can iframe the map and present it as their own, and on a platform
// whose whole value is attribution, that is the part that matters.
//
// ⚠️ `/embed/*` is DELIBERATELY framable — it is a widget built for third-party
// pages and already sends `Access-Control-Allow-Origin: *` (see
// /embed/concession/:id below). A blanket DENY would silently break every site
// that has embedded it. The exemption is the whole reason this is a function of
// the request path rather than three constant headers.
const EMBEDDABLE = /^\/embed(\/|$)/;

// Report-Only, deliberately. The app loads map tiles from two CDNs, fonts from
// Google, a tag manager, and a GeoJSON straight off raw.githubusercontent.com;
// index.html carries four inline <script> blocks and the SSR pages emit
// ld+json. An enforcing policy written blind would blank the map. Ship the
// report, read what it would have blocked in a browser console, then enforce.
//
// 📌 No `report-uri`. An unauthenticated public collector on Cloud Run is a
// log-spam and cost vector, and the review this policy exists for is done in a
// real browser anyway — which the definition of done requires regardless.
//
// 🗓 REVIEW FOR ENFORCEMENT once the console has been read on the map, an entity
// page and /api-docs. Until then this header blocks nothing.
const CSP_DIRECTIVES = {
  'default-src': ["'self'"],
  // 'unsafe-inline' is required, not laziness: index.html:46 patches getContext
  // for WebGL, :58 bootstraps Consent Mode, :97 configures gtag, and both
  // index.html and seo/render-page.js emit ld+json — which script-src gates like
  // any other <script>. Removing it needs nonces on all of them.
  'script-src': ["'self'", "'unsafe-inline'", 'https://www.googletagmanager.com'],
  'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
  'font-src': ["'self'", 'data:', 'https://fonts.gstatic.com'],
  'img-src': ["'self'", 'data:', 'blob:', 'https://server.arcgisonline.com', 'https://basemaps.cartocdn.com', 'https://*.basemaps.cartocdn.com', 'https://www.google-analytics.com', 'https://*.google-analytics.com'],
  'connect-src': ["'self'", 'https://apiv2.something-rare.com', 'https://server.arcgisonline.com', 'https://basemaps.cartocdn.com', 'https://*.basemaps.cartocdn.com', 'https://raw.githubusercontent.com', 'https://fonts.googleapis.com', 'https://fonts.gstatic.com', 'https://www.googletagmanager.com', 'https://www.google-analytics.com', 'https://*.google-analytics.com', 'https://analytics.google.com', 'https://*.analytics.google.com'],
  // MapLibre GL and @loaders.gl both spawn workers from blob: URLs, and the
  // CSV/JSON export links are blob: too.
  'worker-src': ["'self'", 'blob:'],
  'child-src': ["'self'", 'blob:'],
  'base-uri': ["'self'"],
  'form-action': ["'self'"],
  'object-src': ["'none'"],
};

function buildCsp(overrides = {}) {
  const merged = { ...CSP_DIRECTIVES };
  for (const [directive, extra] of Object.entries(overrides)) {
    merged[directive] = [...(merged[directive] ?? []), ...extra];
  }
  return Object.entries(merged).map(([k, v]) => `${k} ${v.join(' ')}`).join('; ');
}

const CSP_MAIN = `${buildCsp()}; frame-ancestors 'none'`;
const CSP_EMBED = `${buildCsp()}; frame-ancestors *`;

// ⚠️ /api-docs needs a LOOSER policy, and this is measured, not assumed. Running
// the page under the report policy in a real browser on 2026-08-24 produced 19
// violations that no amount of reading our own source would have found, because
// they come from inside @scalar/api-reference-react at runtime:
//   * it evaluates strings as JavaScript      → 'unsafe-eval'
//   * it loads its own fonts from fonts.scalar.com
//   * it connects to api.scalar.com on load
// Scoping them here rather than widening CSP_DIRECTIVES keeps 'unsafe-eval' off
// the other 40,000 URLs — the whole point of enforcing this policy one day.
//
// ⛔ SEPARATE ISSUE, NOT FIXED HERE: that connection to api.scalar.com is
// Scalar's default behaviour (no proxyUrl is configured in ApiDocsPage.tsx).
// Worth deciding deliberately, because Try-it sends the reader's own API key.
const CSP_API_DOCS = `${buildCsp({
  'script-src': ["'unsafe-eval'"],
  'font-src': ['https://fonts.scalar.com'],
  'connect-src': ['https://api.scalar.com'],
})}; frame-ancestors 'none'`;

app.use((req, res, next) => {
  res.set('X-Content-Type-Options', 'nosniff');
  res.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  // Verified 2026-08-24: nothing in frontend/src calls navigator.geolocation,
  // getUserMedia or the Payment Request API, so denying all four costs nothing.
  // If a "locate me" button is ever added, geolocation=(self) goes here first.
  res.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()');
  // ⚠️ Short on purpose. HSTS is enforced by the BROWSER, so a mistake cannot be
  // rolled back by redeploying — it has to expire. One day now; raise to a year
  // once this has run clean. ⛔ Never add `preload`: that is effectively
  // permanent. `includeSubDomains` is now viable — the dangling api.* record was
  // deleted 2026-08-24, leaving only apiv2 (HTTPS, its own HSTS) and www — but
  // it is deliberately still absent: widening the commitment and shortening the
  // max-age in the same week is two irreversible bets at once. Add it when the
  // max-age goes up.
  res.set('Strict-Transport-Security', 'max-age=86400');

  if (EMBEDDABLE.test(req.path)) {
    res.set('Content-Security-Policy-Report-Only', CSP_EMBED);
  } else {
    res.set('X-Frame-Options', 'DENY');
    res.set('Content-Security-Policy-Report-Only',
      req.path === '/api-docs' ? CSP_API_DOCS : CSP_MAIN);
  }
  next();
});

// ── Force HTTPS — 301 permanent redirect for any plain-HTTP request ───────
// ── www → non-www canonical redirect (301) ────────────────────────────────
// Both middlewares live in seo/canonical-hosts.js: the redirect target is
// built from the `Host` header, and an unvalidated header is an open
// redirect behind any proxy that does not itself validate Host (nginx
// `default_server`, plain Docker — what the README tells a self-hoster to
// run). An unrecognised Host skips the redirect and falls through to
// `next()` rather than 400ing — see that file for why.
app.use(forceHttpsMiddleware);
app.use(wwwRedirectMiddleware);

// ── /index.html → / (301) ─────────────────────────────────────────────────
// Without this, the static middleware below serves dist/index.html at BOTH `/`
// and `/index.html` — byte-identical, with no canonical to separate them — so
// the home page is indexable twice and its authority is split between the two
// addresses. Measured live 2026-08-09: both 200, both 24 637 B, same sha1.
// The query string is preserved so ?utm_source=… survives the redirect.
app.use((req, res, next) => {
  if (req.path === '/index.html') {
    return res.redirect(301, '/' + req.url.slice(req.path.length));
  }
  next();
});

// ── Compression — gzip/brotli for all text responses ──────────────────────
app.use(compression());

// ── Pre-compressed + immutable cache for hashed Vite assets ───────────────
// /assets/* filenames contain content hashes so they can be cached forever.
// expressStaticGzip checks for .gz/.br sidecars (generated by vite-plugin-compression)
// and serves them with the correct Content-Encoding header when the client
// advertises Accept-Encoding: gzip or br — no CPU cost per request.
app.use('/assets', expressStaticGzip(join(__dirname, 'dist', 'assets'), {
  enableBrotli: true,
  orderPreference: ['br', 'gz'],
  serveStatic: {
    maxAge: '1y',
    immutable: true,
  },
}));

// ── 410 Gone — legacy URLs from previous site ─────────────────────────────
// Exact paths that no longer exist and should never return.
const GONE_EXACT = new Set([
  '/laws',
]);

// ── Withdrawn layers — 410 Gone, deliberately not 404 ─────────────────────
// WDPA came down 2026-09-03: Protected Planet's terms require prior written
// permission from UNEP-WCMC to redistribute through an interactive web map.
// KBA came down the same day: BirdLife's KBA terms carry the same clause,
// plus a separate no-commercial-use clause.
// The rows are still in the database; only the serving stops.
// ⛔ Not 404. A 404 tells Google the URL might come back and it holds it in the
// index for weeks; 410 says withdrawn on purpose. And this must be decided HERE,
// in the early middleware, not in the /layer/:layerId route — that route's
// missing-key branch calls sendNotFound(), so a withdrawal left to it would
// read as an accident.
const WITHDRAWN_LAYER_PATHS = new Set([
  '/layer/wdpa',
  '/layer/kbas',
]);

// Any path starting with these prefixes belongs to the old localised site.
const GONE_PREFIXES = ['/en', '/pl', '/de', '/es'];

app.use((req, res, next) => {
  const path = req.path.replace(/\/+$/, '') || '/'; // normalise trailing slash

  // ?next=1 pagination and ?lang= localisation ghosts from the old site
  if (req.query.next !== undefined || req.query.lang !== undefined) {
    return res.status(410).send('410 Gone');
  }

  if (GONE_EXACT.has(path)) {
    return res.status(410).send('410 Gone');
  }

  if (WITHDRAWN_LAYER_PATHS.has(path)) {
    return res.status(410).send('410 Gone — layer withdrawn pending permission');
  }

  for (const prefix of GONE_PREFIXES) {
    if (path === prefix || path.startsWith(prefix + '/')) {
      return res.status(410).send('410 Gone');
    }
  }

  next();
});
// ─────────────────────────────────────────────────────────────────────────────

// `robots.txt` is `Allow: /`, so anything reachable is indexable unless it says
// otherwise. These two say otherwise: a JSON health probe and an iframe widget
// are not pages, and an indexed one competes with the real page for the same
// entity. `X-Robots-Tag` is the only way to say it for a non-HTML response.
//
// ⛔ Not `/api-docs` — that one is deliberately indexable and has its own
// title, description and canonical (added 2026-08-17 for exactly that reason).
app.get('/health', (req, res) => res.set('X-Robots-Tag', 'noindex').json({ status: 'ok' }));

// The widget is a standalone document embedded on third-party pages. It must
// never be indexed in its own right: it duplicates /concession/:id with none of
// the context. noindex rather than a canonical — Google ignores a canonical on
// a noindex page, and combining the two is contradictory signalling.
app.use('/embed', (req, res, next) => {
  res.set('X-Robots-Tag', 'noindex');
  next();
});

// /admin/* is intentionally NOT exposed via the public Cloud Run frontend.
// The admin dashboard is reachable only via Tailscale at:
//   http://<tailscale-host>:8088/admin/dashboard?token=<TOKEN>
// nginx on the VPS already returns 404 for public /admin/* requests, but the
// SPA fallback below would otherwise serve the index.html shell with HTTP 200,
// which is misleading. Return 404 here so the public surface is clean.
app.use('/admin', (req, res) => {
  res.status(404).type('text/plain').send('Not Found');
});

// The generic /api/* proxy lives in seo/api-proxy.js — see the comment there
// for the 2026-09-18 incident (Googlebot 504s) this timeout value fixes and
// why `timeout` (the client-facing socket) is deliberately absent.
app.use('/api', createApiProxy({ target: VPS_API_URL, apiKey: ABYSSAL_API_KEY }));

// IndexNow verification key
const INDEXNOW_KEY = process.env.INDEXNOW_KEY;
if (INDEXNOW_KEY) {
  app.get(`/${INDEXNOW_KEY}.txt`, (req, res) => res.type('text').send(INDEXNOW_KEY));
}

// ── pSEO pages — serve SSR HTML to bots, SPA shell to humans ──────────
// Two groups, and the difference is whether App.tsx has a route for the path.
// concession/vent/seamount have real React pages, so humans keep the SPA and the
// SSR copy is for crawlers only. oceansites/onc do NOT — the bot gate meant a
// person opening one got a blank React shell, which was tolerable only while
// nothing linked to them. The hub pages now do, so serving everyone the SSR page
// is the difference between a working link and a dead one.
// ONE loop again. The two were split on 18.08 because the audience differed;
// now the only difference is the declared category, which `hydrates()` reads —
// so both agents receive the SAME document and a per-agent divergence has
// nowhere left to hide. concession/vent/seamount emit the bundle and React
// takes over; oceansites/onc do not, because App.tsx cannot route them.
const ENTITY_HUB = {
  concession: ['/concession', 'All concessions'],
  vent:       ['/vent',       'All hydrothermal vents'],
  seamount:   ['/seamount',   'All seamounts'],
  oceansites: ['/oceansites', 'All OceanSITES moorings'],
  onc:        ['/onc',        'All ONC observatories'],
};

for (const type of ['concession', 'vent', 'seamount', 'oceansites', 'onc']) {
  const [hubHref, hubLabel] = ENTITY_HUB[type];
  app.get(`/${type}/:id`, entityRoute(`This ${type} page`, async (req, res) => {
    const html = await renderSeoPage(type, req.params.id, { hydrate: hydrates(req.path) });
    // `null` now means ONE thing — the backend answered 404 for this id. Any
    // other failure threw and `entityRoute` turned it into 503. Previously
    // this line read `return next()`, which handed the id to the SPA catch-all
    // and answered 200 with an empty shell: a soft 404 on the three React
    // routes, and a genuinely blank page on the two server-only ones (App.tsx
    // cannot route /onc or /oceansites and has no `path="*"`).
    if (!html) return sendNotFound(res, `No ${type} page for “${req.params.id}”.`, hubHref, hubLabel);
    res.type('html').send(html);
  }));
}

// ── Hub (index) pages — the crawl path ────────────────────────────────
// /seamount, /concession, /vent and /layer all returned 404 until now, while
// Google was asking for exactly those parent paths on seeing /seamount/12345.
// Combined with a home page that served bots ZERO anchors, nothing in the
// 40,300-page corpus was reachable by link — only asserted by sitemap, which is
// what "Discovered – currently not indexed" (29,241 URLs, GSC 2026-08-17) means.
//
// Unlike the older SSR routes these are served to EVERYONE. The bot gate exists
// so humans get the interactive map instead of a static snapshot; a directory
// page has no map to give them, and seven bot-gated routes already render blank
// for humans (see seo/route-categories.js). Adding nine more would be deliberate breakage.
const HUB_KINDS = ['seamount', 'concession', 'vent', 'onc', 'oceansites', 'river', 'report', 'layer', 'resource'];

// The hub list is on every hub page and on the bot copy of "/", so it is cached:
// otherwise each of those renders costs a round trip plus nine COUNT(*)s.
let hubIndexCache = { at: 0, hubs: null };
const HUB_INDEX_TTL_MS = 10 * 60 * 1000;

async function fetchHubIndex() {
  if (hubIndexCache.hubs && Date.now() - hubIndexCache.at < HUB_INDEX_TTL_MS) {
    return hubIndexCache.hubs;
  }
  try {
    const r = await fetch(`${VPS_API_URL}/v1/seo/hubs`, {
      headers: API_HEADERS, signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) throw new Error(`API ${r.status}`);
    const { hubs } = await r.json();
    hubIndexCache = { at: Date.now(), hubs };
    return hubs;
  } catch (err) {
    console.error('hub index fetch failed:', err.message);
    // Serve the last good copy rather than a page with no navigation. Null only
    // on a cold start that has never succeeded.
    return hubIndexCache.hubs;
  }
}

for (const kind of HUB_KINDS) {
  app.get(`/${kind}`, async (req, res) => {
    const page = Math.max(1, parseInt(req.query.page, 10) || 1);
    try {
      const [hub, hubs] = await Promise.all([
        fetchUpstream(`${VPS_API_URL}/v1/seo/hub/${kind}?page=${page}`, {
          timeoutMs: 10000,
          fetchImpl: (u, opts) => fetch(u, { ...opts, headers: API_HEADERS }),
        }),
        fetchHubIndex(),
      ]);
      // A page number past the end is a genuine 404. Answer it HERE rather than
      // via next(): the hubs are excluded from SPA_PATHS precisely so the shell
      // cannot turn this into a 200 soft-404 (the defect fixed 2026-08-09).
      if (!hub) {
        return res.status(404).type('html').send(
          '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">'
          + `<title>Page not found | Abyssal Claims</title>`
          + `<p>No such page in this index. <a href="https://something-rare.com/${kind}">Back to page 1</a>.</p>`);
      }
      res.type('html').set('Cache-Control', 'public, max-age=1800').send(renderHubPage(hub, hubs));
    } catch (err) {
      // NOT next(): these paths are in sitemap-core, and the catch-all 404s
      // anything it does not recognise. A backend blip would otherwise tell
      // Google the hub is gone. 503 means "ask again", which is the truth.
      console.error(`hub ${kind} failed:`, err.message);
      res.status(503).type('html').set('Retry-After', '120').send(
        '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">'
        + '<title>Temporarily unavailable | Abyssal Claims</title>'
        + '<p>This index is temporarily unavailable. <a href="/">Go to the map</a>.</p>');
    }
  });
}

// ── Report SSR for bots ───────────────────────────────────────────────
app.get('/report/:platformId', entityRoute('This report', async (req, res, next) => {
  // ── Still bot-gated, and this is a declared exception, not an oversight ──
  // React does something structurally different here that a static page cannot
  // represent: ReportRouter picks between the v1 and v2 report stacks, and
  // ClaimReportRedirect navigates away. Serving humans the SSR copy would show
  // them content and then move them, which is worse than the shell + spinner.
  // Revisit only as its own piece of work, with the v1 freeze in mind.
  if (!isBot(req)) return next(); // Humans get SPA
  let html;
  try {
    html = await renderSeoPage('report', req.params.platformId, { hydrate: hydrates(req.path) });
  } catch (err) {
    // 410, not 404 and not 200. The id resolves, so "not found" would be a lie;
    // the page has no statistics to show, so 200 is the soft 404 Search Console
    // flagged on 2026-08-23. 410 says "this existed and is deliberately gone",
    // which is the only one of the three that is true — and unlike 404, Google
    // treats it as final and stops re-crawling.
    if (err instanceof EntityGone) {
      console.warn(`report ${req.params.platformId}: ${err.message} — 410`);
      return res.status(410).type('html').send(
        '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">'
        + '<title>Report no longer available | Abyssal Claims</title>'
        + `<p>No float report exists for \u201c${escapeHtml(String(req.params.platformId))}\u201d. `
        + '<a href="https://something-rare.com/report">All reports</a>.</p>');
    }
    throw err;
  }
  // Only crawlers reach this line, so only crawlers can be told 404 — a human
  // was already handed the SPA above and never caused a lookup. That asymmetry
  // is inherited from the bot gate, not introduced here: React routes /report/
  // and can render its own not-found state.
  if (!html) return sendNotFound(res, `No report for “${req.params.platformId}”.`, '/report', 'All reports');
  res.type('html').send(html);
}));

// ── Claim report by company name — legacy alias → contractor page ─────────
// No longer emitted in the sitemap. The incoming slug is the same
// _contractor_slug used by /contractor/{slug}, so this 301s straight there
// (a real 200 page). It NEVER redirects to / — a company with no page is a
// genuine 404, not a bounce to the homepage (which Google reads as soft-404
// and re-crawls forever, burning crawl budget on the 40k pages we want indexed).
app.get('/claim-report/company/:slug', async (req, res) => {
  const slug = req.params.slug;
  try {
    const apiRes = await fetch(`${VPS_API_URL}/v1/seo/contractor/${encodeURIComponent(slug)}`, {
      headers: { 'X-API-Key': ABYSSAL_API_KEY },
      signal: AbortSignal.timeout(5000),
    });
    if (apiRes.ok) return res.redirect(301, `/contractor/${slug}`);
  } catch { /* fall through to 404 */ }
  return res.status(404).type('html').send(wrapHtml(
    '<title>Not found — Abyssal Claims</title><meta name="robots" content="noindex" />',
    '<main style="max-width:640px;margin:0 auto;padding:2rem;font-family:system-ui,sans-serif;color:#c9d1d9"><h1>404 — Not found</h1><p>No contractor page for that company.</p><p><a href="/contractors">Browse all contractors</a> · <a href="/">Interactive map</a></p></main>',
    // A 404 body, not a route: booting React over it would replace the message
    // with whatever App.tsx renders for an unroutable path, i.e. nothing.
    { hydrate: false },
  ));
});

// ── Claim report SSR for bots ─────────────────────────────────────────
app.get('/claim-report/:isaId', entityRoute('This claim report', async (req, res, next) => {
  // ── Still bot-gated, and this is a declared exception, not an oversight ──
  // React does something structurally different here that a static page cannot
  // represent: ReportRouter picks between the v1 and v2 report stacks, and
  // ClaimReportRedirect navigates away. Serving humans the SSR copy would show
  // them content and then move them, which is worse than the shell + spinner.
  // Revisit only as its own piece of work, with the v1 freeze in mind.
  if (!isBot(req)) return next();
  const html = await renderSeoPage('claim-report', req.params.isaId, { hydrate: hydrates(req.path) });
  if (!html) return sendNotFound(res, `No claim report for “${req.params.isaId}”.`, '/concession', 'All concessions');
  res.type('html').send(html);
}));

// ── Blog SSR for bots — fetches live content from backend API ──────────
app.get('/blog', entityRoute('The blog index', async (req, res) => {
  {
    // Index page, no id — a 404 from the backend is a broken endpoint, not an
    // absent entity, so it belongs on the 503 path like /contractors.
    const articles = await fetchEntity(`${VPS_API_URL}/v1/blog/articles`);
    if (!articles) throw new BackendUnavailable('blog index returned 404');
    const head = `
      <title>Abyssal Claims Blog — Ocean & Land Environmental Intelligence</title>
      <meta name="description" content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, air quality, and ocean-land policy." />
      <link rel="canonical" href="https://something-rare.com/blog" />
      <meta property="og:type" content="website" />
      <meta property="og:url" content="https://something-rare.com/blog" />
      <meta property="og:title" content="Abyssal Claims Blog" />
      <meta property="og:description" content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, air quality, and ocean-land policy." />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content="Abyssal Claims Blog" />
      <meta name="twitter:description" content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, air quality, and ocean-land policy." />
      <meta name="twitter:image" content="https://something-rare.com/og.jpg" />
      <script type="application/ld+json">${JSON.stringify({
        "@context": "https://schema.org",
        "@type": "Blog",
        name: "Abyssal Claims Blog",
        description: "Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, air quality, and ocean-land policy.",
        url: `${SITE}/blog`,
        publisher: ORG_SCHEMA,
        blogPost: articles.slice(0, 10).map(a => ({
          "@type": "BlogPosting",
          headline: a.title,
          description: a.description,
          url: `${SITE}/blog/${a.slug}`,
          datePublished: a.published_at,
        })),
      }).replace(/<\//g, '<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, renderBlogIndex(articles), { hydrate: hydrates(req.path) }));
  }
}));

app.get('/blog/:slug', entityRoute('This article', async (req, res) => {
  {
    const article = await fetchEntity(`${VPS_API_URL}/v1/blog/articles/${encodeURIComponent(req.params.slug)}`);
    if (!article) return sendNotFound(res, `No article “${req.params.slug}”.`, '/blog', 'All articles');
    const head = `
      <title>${escapeHtml(article.title)} — Abyssal Claims</title>
      <meta name="description" content="${escapeHtml(article.description)}" />
      <link rel="canonical" href="${escapeHtml(canonicalUrl('/blog', article.slug))}" />
      <meta property="og:type" content="article" />
      <meta property="og:url" content="${escapeHtml(canonicalUrl('/blog', article.slug))}" />
      <meta property="og:title" content="${escapeHtml(article.title)}" />
      <meta property="og:description" content="${escapeHtml(article.description)}" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content="${escapeHtml(article.title)}" />
      <meta name="twitter:description" content="${escapeHtml(article.description)}" />
      <script type="application/ld+json">${JSON.stringify({
        "@context": "https://schema.org",
        "@type": "Article",
        headline: article.title,
        description: article.description,
        datePublished: article.published_at,
        dateModified: article.updated_at ? article.updated_at.slice(0, 10) : article.published_at,
        author: ORG_SCHEMA,
        publisher: ORG_SCHEMA,
        url: `${SITE}/blog/${article.slug}`,
        image: `${SITE}/og.jpg`,
        mainEntityOfPage: { "@type": "WebPage", "@id": `${SITE}/blog/${article.slug}` },
      }).replace(/<\//g, '<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, renderBlogArticle(article, article.content_md), { hydrate: hydrates(req.path) }));
  }
}));

// ── Vent report SSR for bots — ChEssBase species + nearby claims ──────────
app.get('/vent-report/:ventId', entityRoute('This vent report', async (req, res, next) => {
  // ── Still bot-gated, and this is a declared exception, not an oversight ──
  // React does something structurally different here that a static page cannot
  // represent: ReportRouter picks between the v1 and v2 report stacks, and
  // ClaimReportRedirect navigates away. Serving humans the SSR copy would show
  // them content and then move them, which is worse than the shell + spinner.
  // Revisit only as its own piece of work, with the v1 freeze in mind.
  if (!isBot(req)) return next();
  {
    const vent = await fetchEntity(`${VPS_API_URL}/v1/seo/vent-report/${encodeURIComponent(req.params.ventId)}`);
    if (!vent) return sendNotFound(res, `No vent report for “${req.params.ventId}”.`, '/vent', 'All hydrothermal vents');
    const body = renderVentReport(vent);
    const title = `${vent.name} — Hydrothermal Vent Report`;
    // ⚠️ `status` is InterRidge's own Activity string since 2026-09-21 — "active,
    // confirmed" / "active, inferred" / "inactive" — and it can be null when the
    // source leaves it blank. Interpolating it bare printed the word "null" into
    // the meta description Google indexes. It is quoted rather than folded into
    // the sentence because it is the source's wording, not ours.
    const activity = vent.status ? `recorded by InterRidge as “${vent.status}”` : 'with no activity value recorded by InterRidge';
    const description = `Hydrothermal vent ${activity}, at ${vent.depth_m ? vent.depth_m.toFixed(0) + ' m' : 'unknown depth'}. ${vent.chess_count} ChEssBase species. ${vent.nearby_claims.length} nearby mining claims.`;
    const head = `
      <title>${escapeHtml(title)}</title>
      <meta name="description" content="${escapeHtml(description)}" />
      <link rel="canonical" href="${escapeHtml(canonicalUrl('/vent-report', req.params.ventId))}" />
      <meta property="og:type" content="website" />
      <meta property="og:url" content="${escapeHtml(canonicalUrl('/vent-report', req.params.ventId))}" />
      <meta property="og:title" content="${escapeHtml(title)}" />
      <meta property="og:description" content="${escapeHtml(description)}" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content="${escapeHtml(title)}" />
      <meta name="twitter:description" content="${escapeHtml(description)}" />
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, body, { hydrate: hydrates(req.path) }));
  }
}));

// ── Arctic river station pages ────────────────────────────────────────────
app.get('/river/:id', entityRoute('This river station page', async (req, res) => {
  // Served to everyone: App.tsx has no route for this path, so the bot gate
  // meant a person following a link here got a blank React shell. The hub
  // pages link to these, so the gate is now the difference between a working
  // link and a dead one.
  {
    const data = await fetchEntity(`${VPS_API_URL}/v1/seo/river/${encodeURIComponent(req.params.id)}`);
    if (!data) return sendNotFound(res, `No river station “${req.params.id}”.`, '/river', 'All river stations');
    const title = `${data.river_name} River at ${data.site_label} — Arctic River Inputs | Abyssal Claims`;
    const description = `Discharge and land-to-ocean biogeochemistry fluxes at the ${data.river_name} River (${data.site_label}). Record: ${data.record_start || '?'}–${data.record_end || '?'}. Mean annual discharge: ${data.mean_annual_discharge_km3 != null ? Number(data.mean_annual_discharge_km3).toFixed(1) + ' km³/yr' : 'see data'}. Source: ArcticGRO / PANGAEA.`;
    const canonical = canonicalUrl('/river', req.params.id);
    const jsonLd = {
      '@context': 'https://schema.org',
      '@type': 'Dataset',
      name: `${data.river_name} River at ${data.site_label} — Arctic River Inputs`,
      description,
      url: canonical,
      creator: { '@type': 'Organization', name: 'Arctic Great Rivers Observatory (ArcticGRO)', url: 'https://arcticgreatrivers.org' },
      license: 'https://creativecommons.org/licenses/by/4.0/',
      isAccessibleForFree: true,
      variableMeasured: ['River discharge', 'Dissolved organic carbon', 'Nutrients'],
      ...(data.lat != null && data.lon != null ? {
        spatialCoverage: {
          '@type': 'Place',
          name: `${data.river_name} River at ${data.site_label}`,
          geo: { '@type': 'GeoCoordinates', latitude: Number(data.lat), longitude: Number(data.lon) },
        },
      } : {}),
      ...(data.record_start && data.record_end ? { temporalCoverage: `${data.record_start}/${data.record_end}` } : {}),
    };
    const head = `
      <title>${escapeHtml(title)}</title>
      <meta name="description" content="${escapeHtml(description)}" />
      <link rel="canonical" href="${escapeHtml(canonical)}" />
      <meta property="og:type" content="website" />
      <meta property="og:url" content="${escapeHtml(canonical)}" />
      <meta property="og:title" content="${escapeHtml(title)}" />
      <meta property="og:description" content="${escapeHtml(description)}" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content="${escapeHtml(title)}" />
      <meta name="twitter:description" content="${escapeHtml(description)}" />
      <script type="application/ld+json">${JSON.stringify(jsonLd).replace(/<\//g, '<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, renderRiverPage(data), { hydrate: hydrates(req.path) }));
  }
}));

// ── Resource type pages ───────────────────────────────────────────────────
app.get('/resource/:slug', entityRoute('This resource page', async (req, res) => {
  // Served to everyone: App.tsx has no route for this path, so the bot gate
  // meant a person following a link here got a blank React shell. The hub
  // pages link to these, so the gate is now the difference between a working
  // link and a dead one.
  {
    const resource = await fetchEntity(`${VPS_API_URL}/v1/seo/resource/${encodeURIComponent(req.params.slug)}`, 10000);
    if (!resource) return sendNotFound(res, `No resource type “${req.params.slug}”.`, '/resource', 'All resource types');
    const head = `
      <title>${escapeHtml(resource.meta.title)}</title>
      <meta name="description" content="${escapeHtml(resource.meta.description)}" />
      <link rel="canonical" href="${escapeHtml(normaliseUrl(resource.meta.canonical_url))}" />
      <meta property="og:type" content="website" />
      <meta property="og:url" content="${escapeHtml(normaliseUrl(resource.meta.canonical_url))}" />
      <meta property="og:title" content="${escapeHtml(resource.meta.title)}" />
      <meta property="og:description" content="${escapeHtml(resource.meta.description)}" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary" />
      <script type="application/ld+json">${JSON.stringify(normaliseJsonLd(resource.meta.json_ld)).replace(/<\//g, '<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, renderResource(resource), { hydrate: hydrates(req.path) }));
  }
}));

// ── Contractor directory — list all contractors (bots only) ───────────────
// Served to everyone, not just bots: this is a directory page, and App.tsx has
// no /contractors route — the bot gate meant humans got a blank React shell.
// Same reasoning as the hub pages above.
app.get('/contractors', entityRoute('The contractor directory', async (req, res) => {
  {
    // A directory with no id cannot be "missing": a 404 from the backend here
    // is a broken endpoint, not an absent entity, so this stays on the 503 path.
    const contractors = await fetchEntity(`${VPS_API_URL}/v1/seo/contractors`);
    if (!contractors) throw new BackendUnavailable('contractor directory returned 404');
    const rows = contractors.map(c => `
      <tr>
        <td><a href="https://something-rare.com/contractor/${escapeHtml(c.slug)}" style="color:#22d3ee">${escapeHtml(c.contractor_name)}</a></td>
        <td>${c.claim_count}</td>
        <td>${c.total_area_km2 ? c.total_area_km2.toLocaleString() + ' km²' : '—'}</td>
        <td>${escapeHtml((c.resource_types || []).join(', ') || '—')}</td>
        <td>${c.high_risk_count > 0 ? `<span style="color:#f87171">${c.high_risk_count} high-risk</span>` : '0'}</td>
      </tr>`).join('');
    const head = `
      <title>ISA Deep-Sea Mining Contractors | Abyssal Claims</title>
      <meta name="description" content="All ${contractors.length} contractors holding ISA deep-sea mining licences. Explore concession portfolios, environmental footprints, and risk profiles." />
      <link rel="canonical" href="https://something-rare.com/contractors" />
      <meta property="og:title" content="ISA Deep-Sea Mining Contractors" />
      <meta property="og:description" content="All ${contractors.length} contractors holding ISA deep-sea mining licences." />
      <meta property="og:url" content="https://something-rare.com/contractors" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content="ISA Deep-Sea Mining Contractors" />
      <meta name="twitter:description" content="All ${contractors.length} contractors holding ISA deep-sea mining licences." />
      <meta name="twitter:image" content="https://something-rare.com/og.jpg" />
      <script type="application/ld+json">${JSON.stringify({"@context":"https://schema.org","@type":"ItemList","name":"ISA Deep-Sea Mining Contractors","description":`All ${contractors.length} contractors holding ISA deep-sea mining licences`,"url":"https://something-rare.com/contractors","numberOfItems":contractors.length}).replace(/<\//g,'<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    const body = `
      <main style="max-width:900px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
        <h1 style="margin:0 0 0.5rem;color:#fff">ISA Deep-Sea Mining Contractors</h1>
        <p style="color:#888;margin:0 0 2rem">${contractors.length} entities hold active or historical ISA exploration licences in international seabed areas.</p>
        <table style="width:100%;border-collapse:collapse">
          <tr style="color:#888;font-size:0.85em">
            <th style="text-align:left;padding:4px 8px">Contractor</th>
            <th style="text-align:left;padding:4px 8px">Concessions</th>
            <th style="text-align:left;padding:4px 8px">Total Area</th>
            <th style="text-align:left;padding:4px 8px">Resources</th>
            <th style="text-align:left;padding:4px 8px">Risk</th>
          </tr>
          ${rows}
        </table>
        <p style="margin-top:2rem"><a href="https://something-rare.com/" style="color:#22d3ee">← Interactive map</a></p>
        <p style="color:#666;font-size:0.8em">Data: International Seabed Authority</p>
      </main>`;
    res.type('html').send(wrapHtml(head, body, { hydrate: hydrates(req.path) }));
  }
}));

// ── Individual contractor profile page ────────────────────────────────────
app.get('/contractor/:slug', entityRoute('This contractor page', async (req, res) => {
  // Served to everyone: App.tsx has no route for this path, so the bot gate
  // meant a person following a link here got a blank React shell. The hub
  // pages link to these, so the gate is now the difference between a working
  // link and a dead one.
  {
    const contractor = await fetchEntity(`${VPS_API_URL}/v1/seo/contractor/${encodeURIComponent(req.params.slug)}`, 8000);
    if (!contractor) return sendNotFound(res, `No contractor page for “${req.params.slug}”.`, '/contractors', 'All contractors');
    const head = `
      <title>${escapeHtml(contractor.meta.title)}</title>
      <meta name="description" content="${escapeHtml(contractor.meta.description)}" />
      <link rel="canonical" href="${escapeHtml(normaliseUrl(contractor.meta.canonical_url))}" />
      <meta property="og:type" content="profile" />
      <meta property="og:url" content="${escapeHtml(normaliseUrl(contractor.meta.canonical_url))}" />
      <meta property="og:title" content="${escapeHtml(contractor.meta.title)}" />
      <meta property="og:description" content="${escapeHtml(contractor.meta.description)}" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary" />
      <script type="application/ld+json">${JSON.stringify(normaliseJsonLd(contractor.meta.json_ld)).replace(/<\//g, '<\\/')}</script>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
    res.type('html').send(wrapHtml(head, renderContractor(contractor), { hydrate: hydrates(req.path) }));
  }
}));

// ── Layer SSR pages for bots ─────────────────────────────────────────────
const LAYER_META = {
  // Ocean layers
  'contracts':           { label: 'Mining Concessions',          source: 'International Seabed Authority (ISA)',          category: 'ocean', desc: 'All active ISA exploration and exploitation contracts for deep-sea minerals, with contractor details, expiry dates, and environmental risk assessments.' },
  'reserved-areas':      { label: 'Reserved Areas',              source: 'International Seabed Authority (ISA)',          category: 'ocean', desc: 'Areas set aside by the ISA for future use by developing states.' },
  'apeis':               { label: 'Protected Areas (APEIs)',     source: 'International Seabed Authority (ISA)',          category: 'ocean', desc: 'Areas of Particular Environmental Interest designated to protect representative deep-sea habitats from mining.' },
  'relinquished-areas':  { label: 'Relinquished Areas',          source: 'International Seabed Authority (ISA)',          category: 'ocean', desc: 'Former mining exploration areas voluntarily returned to the ISA.' },
  'biodiversity-hotspots': { label: 'Biodiversity Hotspots',     source: 'Ocean Biodiversity Information System (OBIS)',  category: 'ocean', desc: 'Deep-sea species observation density from the global OBIS network, highlighting areas of exceptional marine biodiversity.' },
  // ⛔ No hard-coded count here. This description used to open "19,617
  // underwater mountains" while the same page printed "Currently tracking
  // 37,889 features" three lines below it, from the live backend. 19,617 is
  // not a subset either — measured 2026-08-18, `in_2011` splits 32,340 / 5,549,
  // so the figure matched no partition of the data. It was simply stale.
  // The live count is rendered below by `countText`; do not restate it here.
  'seamounts':           { label: 'Seamounts',                   source: 'Yesson et al. 2011 / PANGAEA',                 category: 'ocean', desc: 'Underwater mountains mapped from global bathymetry — primary targets for cobalt-crust mining and biodiversity hotspots.' },
  'argo':                { label: 'Argo Floats',                 source: 'International Argo Programme / ArgoVis',        category: 'ocean', desc: 'Real-time autonomous ocean profiling floats measuring temperature, salinity, oxygen, and pH across the global ocean.' },
  'hydrothermal-vents':  { label: 'Hydrothermal Vents',          source: 'InterRidge Database v3.4 / PANGAEA',           category: 'ocean', desc: '721 hydrothermal vent fields worldwide — unique ecosystems hosting species found nowhere else on Earth.' },
  'eez':                 { label: 'EEZ Boundaries',              source: 'MarineRegions.org World EEZ v12',              category: 'ocean', desc: 'Exclusive Economic Zones — maritime boundaries defining national jurisdiction over ocean resources.' },
  // `source` also becomes the JSON-LD Dataset `creator` Organization, so it must name
  // whoever actually built the dataset. VLIZ compiled these boundaries from the UNESCO
  // World Heritage Marine Programme and Protected Planet; naming the UNESCO World
  // Heritage Centre as creator was both factually wrong and the closest thing on the
  // site to asserting an affiliation UNESCO has not granted.
  'protected-marine-sites': { label: 'UNESCO Marine Heritage',   source: 'MarineRegions.org (VLIZ) — compiled from the UNESCO World Heritage Marine Programme', category: 'ocean', desc: 'UNESCO-designated marine World Heritage sites of outstanding universal value.' },
  'noise-risk':          { label: 'Noise Risk Grid',             source: 'ICES / EMODnet + OBIS-SEAMAP',                 category: 'ocean', desc: 'Underwater noise pollution risk grid combining shipping, sonar, and seismic survey data with cetacean habitat sensitivity.' },
  'oceansites':          { label: 'OceanSITES Moorings',         source: 'OceanSITES / OceanOPS',                        category: 'ocean', desc: 'Long-term ocean reference stations providing sustained time-series of ocean-atmosphere observations.' },
  'onc':                 { label: 'ONC Observatories',           source: 'Ocean Networks Canada',                        category: 'ocean', desc: 'Cabled deep-sea observatories delivering real-time data from the ocean floor.' },
  'gbif':                { label: 'GBIF Species (Deep)',         source: 'Global Biodiversity Information Facility',     category: 'ocean', desc: 'Deep-sea species occurrence records from the global GBIF network.' },
  'chess':               { label: 'Chemosynthetic Sites',        source: 'ChEssBase / OBIS',                            category: 'ocean', desc: 'Chemosynthetic ecosystem sites — hydrothermal vents, cold seeps, and whale falls supporting unique biological communities.' },
  'submarine-cables':    { label: 'Submarine Cables',            source: 'EMODnet Human Activities WFS',                 category: 'ocean', desc: 'Undersea telecommunications cable routes — critical global infrastructure crossing the ocean floor.' },
  'ports':               { label: 'Port Locations',              source: 'tayljordan/ports (GitHub)',                    category: 'ocean', desc: 'Global port locations relevant to maritime logistics and deep-sea mining supply chains.' },
  'tectonic-plates':     { label: 'Tectonic Plates',             source: 'Peter Bird 2003',                              category: 'ocean', desc: 'Global tectonic plate boundaries — the geological framework driving hydrothermal activity and mineral formation.' },
  // Land layers
  'mining-footprints':   { label: 'Global Mining Footprints',    source: 'Maus et al. 2022/2023 (Sentinel-2)',           category: 'land', desc: 'Mine polygons (pits, tailings, waste dumps, processing sites) derived from Sentinel-2 satellite imagery at 10m resolution.' },
  'forest-loss':         { label: 'Tree Cover Loss',             source: 'University of Maryland / WRI Global Forest Watch', category: 'land', desc: 'Annual deforestation at 30m resolution (2001–2024) with weekly GLAD/RADD alerts tracking forest loss worldwide.' },
  'tailings':            { label: 'Tailings Dams',               source: 'Hudson-Edwards et al. 2023 (WAPHA, Dryad)',   category: 'land', desc: '11,587 mine tailings dam locations — tracking one of mining\'s greatest environmental hazards. Global Tailings Portal hazard-rating and ownership fields are withdrawn pending permission from GRID-Arendal.' },
  'fires':               { label: 'Active Fires (FIRMS)',        source: 'NASA LANCE / EOSDIS',                         category: 'land', desc: 'Near-real-time fire detection from MODIS and VIIRS satellites, updated within 3 hours of observation.' },
  'air-quality':         { label: 'Air Quality Stations',        source: 'OpenAQ',                                      category: 'land', desc: 'Real-time PM2.5, SO₂, NO₂, O₃, and CO measurements from government air quality monitoring stations worldwide.' },
  'landslides':          { label: 'Landslide Catalog',           source: 'NASA COOLR / Goddard Space Flight Center',     category: 'land', desc: 'Rainfall-triggered landslide events since 2007 — linking precipitation, terrain instability, and land use change.' },
  'surface-water':       { label: 'Global Surface Water',        source: 'JRC / European Commission',                   category: 'land', desc: 'Surface water occurrence and change from 1984–2021 at 30m resolution — tracking lakes, rivers, and reservoirs.' },
  'dams':                { label: 'Global Dams',                 source: 'Global Dam Watch',                            category: 'land', desc: 'River barriers and reservoir polygons — mapping humanity\'s impact on freshwater systems.' },
  'carbon-flux':         { label: 'Forest Carbon Flux',          source: 'WRI / Global Forest Watch',                   category: 'land', desc: 'CO₂ emissions and removals per hectare at 30m resolution — tracking how forests absorb and release carbon.' },
  'soil-carbon':         { label: 'Soil Organic Carbon',         source: 'ISRIC SoilGrids',                             category: 'land', desc: 'Global soil organic carbon content in the top 0–5cm at ~250m resolution — the largest terrestrial carbon pool.' },
  'water-risk':          { label: 'Water Risk (Aqueduct)',       source: 'WRI Aqueduct',                                category: 'land', desc: 'Global water stress, drought risk, and flood risk indicators for every watershed.' },
};

app.get('/layer/:layerId', async (req, res, next) => {
  // Served to everyone: App.tsx has no route for this path, so the bot gate
  // meant a person following a link here got a blank React shell. The hub
  // pages link to these, so the gate is now the difference between a working
  // link and a dead one.
  const meta = LAYER_META[req.params.layerId];
  // The most certain 404 on the site: LAYER_META is a local object, so this is
  // decided without asking anything. It nonetheless answered 200 + blank shell
  // until 2026-08-18, because `next()` reached the SPA catch-all and App.tsx
  // has no /layer/:id route.
  if (!meta) return sendNotFound(res, `No data layer “${req.params.layerId}”.`, '/layer', 'All data layers');

  // Try to get feature count from backend
  let countText = '';
  try {
    const apiRes = await fetch(`${VPS_API_URL}/v1/seo/sitemap/core`, {
      headers: { 'X-API-Key': ABYSSAL_API_KEY },
      signal: AbortSignal.timeout(5000),
    });
    if (apiRes.ok) {
      const { layer_counts } = await apiRes.json();
      const cnt = layer_counts?.[req.params.layerId];
      if (cnt) countText = `Currently tracking ${cnt.toLocaleString()} features.`;
    }
  } catch { /* count unavailable */ }

  const title = `${meta.label} — Abyssal Claims`;
  const description = meta.desc;
  const canonical = canonicalUrl('/layer', req.params.layerId);
  const categoryLabel = meta.category === 'ocean' ? 'Ocean Data Layer' : 'Land Data Layer';

  // Was the FOURTH server shell — a hand-rolled <!DOCTYPE> that, alone among
  // them, emitted no script tag at all. That was never a decision anybody made;
  // it just differed. It is now the shared shell with the category stated:
  // App.tsx has no /layer/:id route, so this page is server-rendered only.
  const head = `
    <title>${escapeHtml(title)}</title>
    <meta name="description" content="${escapeHtml(description)}" />
    <link rel="canonical" href="${canonical}" />
    <meta property="og:title" content="${escapeHtml(title)}" />
    <meta property="og:description" content="${escapeHtml(description)}" />
    <meta property="og:url" content="${canonical}" />
    <meta property="og:type" content="website" />
    <meta property="og:image" content="https://something-rare.com/og.webp" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${escapeHtml(title)}" />
    <meta name="twitter:description" content="${escapeHtml(description)}" />
    <meta name="twitter:image" content="https://something-rare.com/og.webp" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <script type="application/ld+json">${JSON.stringify({
      "@context": "https://schema.org",
      "@type": "Dataset",
      name: meta.label,
      description: description,
      url: canonical,
      creator: { "@type": "Organization", name: meta.source },
      keywords: `${meta.label}, ${meta.category === 'ocean' ? 'ocean' : 'land'} environmental data, environmental monitoring, ${meta.source}`,
      isPartOf: { "@type": "WebApplication", name: "Abyssal Claims", url: "https://something-rare.com" },
    }).replace(/<\//g, '<\\/')}</script>`;

  const body = `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <a href="/">← Back to map</a>
      <p style="color:#888;font-size:0.85rem;margin:1rem 0 0.25rem">${categoryLabel}</p>
      <h1>${escapeHtml(meta.label)}</h1>
      <p>${escapeHtml(description)}</p>
      ${countText ? `<p><strong>${countText}</strong></p>` : ''}
      <p><strong>Source:</strong> ${escapeHtml(meta.source)}</p>
      <p><a href="/?layer=${req.params.layerId}">View on interactive map →</a>
       · <a href="/layer">All data layers</a></p>
      <hr style="border-color:#333" />
      <!-- Was "31 data layers", which is LAYER_META.length — the number of
           layers that have an SEO page, not the number the platform maps. The
           site's own claim, in SEO.tsx and legalContent.ts, is 50+. Three
           numbers for one quantity; this one was both the odd one out and the
           one describing something else. -->
      <p style="font-size:0.85rem;color:#666">Abyssal Claims is an environmental transparency platform mapping 50+ data layers across ocean and land.</p>
    </main>`;

  res.type('html').send(wrapHtml(head, body, { hydrate: hydrates(req.path) }));
});

// ── Legal / about pages SSR for bots ──────────────────────────────────────
// These are SPA-only routes (no backend fetch): the client renders the full
// text via LegalPage.tsx + react-helmet-async. But a crawler's first read is
// the static index.html shell, which used to carry a homepage canonical — so
// Google filed each under "Alternative page with proper canonical tag" and
// indexed "/" instead. Emitting the correct self-canonical + title/description
// (and a real intro body) server-side fixes that. Full policy text still comes
// from the JS-rendered DOM for engines that execute it.
// Static routes that get a bot-facing SSR snapshot. Named for what it is rather
// than "LEGAL_PAGES": /api-docs joined 2026-08-17 and is not a legal page.
const STATIC_SSR_PAGES = {
  privacy: {
    title: 'Privacy Policy | Abyssal Claims',
    description: 'Privacy policy for Abyssal Claims — how we collect, use, and protect your data.',
    heading: 'Privacy Policy',
    intro: 'How Abyssal Claims collects, uses, and protects your data on the deep-sea and land mining transparency platform.',
  },
  terms: {
    title: 'Terms of Use | Abyssal Claims',
    description: 'Terms of use for Abyssal Claims, the deep-sea mining transparency platform.',
    heading: 'Terms of Use',
    intro: 'The terms governing your use of Abyssal Claims, the deep-sea and land mining transparency platform.',
  },
  about: {
    title: 'About | Abyssal Claims',
    description: 'Abyssal Claims is a deep-sea mining transparency platform visualising ISA concession data, environmental risks, and ocean monitoring on an interactive 3D map.',
    heading: 'About Abyssal Claims',
    intro: 'Abyssal Claims is a deep-sea and land mining transparency platform visualising ISA concession data, environmental risks, and ocean monitoring on an interactive 3D globe.',
  },
  // /api-docs had NO SSR handler until 2026-08-17, so crawlers fell through to
  // expressStaticGzip and received the raw SPA shell — 24 471 B carrying the
  // HOME page's title and description. It was competing in the SERP at position
  // 14.9 under a title describing a different page. Same root cause as the
  // home-page canonical defect (fixed 2026-08-16); that fix covered "/" only.
  // Title and description are copied verbatim from ApiDocsPage.tsx's <Helmet>
  // so the pre-JS snapshot and the rendered page cannot disagree.
  'api-docs': {
    title: 'API Documentation | Abyssal Claims',
    description: 'REST API for Abyssal Claims: ISA mining concessions, hydrothermal vents, biodiversity, ocean chemistry and land layers. Requires an organisation-issued API key.',
    heading: 'Abyssal Claims API',
    intro: 'A REST API over the same datasets the map renders: ISA mining concessions and contractors, hydrothermal vents, seamounts, biodiversity occurrences, ocean chemistry fields, and land mining layers.',
  },
};

app.get(['/privacy', '/terms', '/about', '/api-docs'], (req, res, next) => {
  const tab = req.path.slice(1);
  const page = STATIC_SSR_PAGES[tab];
  if (!page) return next();
  const url = `${SITE}/${tab}`;
  const head = `
      <title>${escapeHtml(page.title)}</title>
      <meta name="description" content="${escapeHtml(page.description)}" />
      <link rel="canonical" href="${url}" />
      <meta property="og:type" content="website" />
      <meta property="og:url" content="${url}" />
      <meta property="og:title" content="${escapeHtml(page.title)}" />
      <meta property="og:description" content="${escapeHtml(page.description)}" />
      <meta property="og:image" content="${SITE}/og.jpg" />
      <meta name="twitter:card" content="summary" />
      <meta name="twitter:title" content="${escapeHtml(page.title)}" />
      <meta name="twitter:description" content="${escapeHtml(page.description)}" />
      <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    `;
  // Bots get a static SSR snapshot, so the rich /about content (author, DOI,
  // citation) that lives in the client SPA must be mirrored here or crawlers see
  // only two sentences. Author/DOI come from the single-source site-graph.json.
  const orcid = siteCitation.orcidUrl.replace('https://orcid.org/', '');
  const aboutExtra = tab === 'about' ? `
      <p>Abyssal Claims is an independent, non-commercial platform that brings 50+ public
         scientific and regulatory datasets — ISA deep-sea mining contracts, biodiversity,
         ocean chemistry, mine footprints, tailings, deforestation, fires, and more — onto a
         single interactive 3D globe. It surfaces data and links every layer back to its
         source; it does not advocate a policy position.</p>
      <h2 id="citation">How to cite</h2>
      <p>Built and maintained by ${escapeHtml(siteCitation.author)}
         (ORCID <a href="${escapeHtml(siteCitation.orcidUrl)}">${escapeHtml(orcid)}</a>).</p>
      <p>There are <strong>two</strong> archived records on Zenodo and they are not
         interchangeable. Cite the one that matches what you used.</p>
      <ul>
        <li><strong>The software</strong> — the engine that runs this platform, source
            published under ${escapeHtml(siteCitation.licenceName)}:
            <a href="${escapeHtml(siteCitation.doiUrl)}">${escapeHtml(siteCitation.doi)}</a></li>
        <li><strong>The methods and data documentation</strong> — sources, refresh
            strategies, derived products and known limitations,
            ${escapeHtml(siteCitation.docsLicenceName)}:
            <a href="${escapeHtml(siteCitation.docsDoiUrl)}">${escapeHtml(siteCitation.docsDoi)}</a></li>
      </ul>
      <p>Citing the platform as a whole? Cite the software record; it declares the
         documentation record as its companion.</p>
      <p><strong>Suggested citation (APA) — software:</strong><br />
         Mazurowski, M. (2026). <em>Abyssal Claims: source code of a FAIR-aligned integration
         platform for deep-sea and terrestrial mining transparency</em> (v1.0.0) [Computer
         software]. Zenodo. ${escapeHtml(siteCitation.doiUrl)}</p>
      <p><strong>Suggested citation (APA) — methods documentation:</strong><br />
         Mazurowski, M. (2026). <em>Abyssal Claims: A FAIR-aligned integration platform for
         deep-sea and terrestrial mining transparency</em> (Version 1.6) [Software
         documentation]. Zenodo. ${escapeHtml(siteCitation.docsDoiUrl)}</p>
      <pre style="white-space:pre-wrap;background:#111826;padding:1rem;border-radius:6px;overflow-x:auto;font-size:13px">@software{mazurowski_abyssal_claims_code_2026,
  author       = {Mazurowski, Michal},
  title        = {Abyssal Claims: source code of a FAIR-aligned integration
                  platform for deep-sea and terrestrial mining transparency},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {v1.0.0},
  doi          = {${escapeHtml(siteCitation.doi)}},
  url          = {${escapeHtml(siteCitation.doiUrl)}}
}

@misc{mazurowski_abyssal_claims_docs_2026,
  author       = {Mazurowski, Michal},
  title        = {Abyssal Claims: A FAIR-aligned integration platform for
                  deep-sea and terrestrial mining transparency},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {1.6},
  doi          = {${escapeHtml(siteCitation.docsDoi)}},
  url          = {${escapeHtml(siteCitation.docsDoiUrl)}}
}</pre>
      <p>Contact: <a href="mailto:m.mazurowski@ai-wall.com">m.mazurowski@ai-wall.com</a> · <a href="/api-docs">API documentation</a></p>` : '';
  // The interactive reference is rendered client-side by Scalar, so without this
  // a crawler sees a heading and one sentence. Keep it to what is actually true
  // of the API — access is approved-organisation only, there is no self-signup.
  const apiDocsExtra = tab === 'api-docs' ? `
      <h2>Access</h2>
      <p>Requests authenticate with an <code>X-API-Key</code> header. Keys are issued to
         approved organisations, which then mint keys for their own members; there is no
         self-signup. Responses are GeoJSON in EPSG:4326, with vector tiles for the layers
         that are too large to serve whole.</p>
      <h2>Machine-readable schema</h2>
      <p>The full OpenAPI document is public and generated from the live routes, so it
         cannot drift from the running service:
         <a href="https://apiv2.something-rare.com/openapi.json">openapi.json</a>.</p>
      <p>Every dataset carries its upstream source, licence and citation. Attribution
         requirements travel with the data — see <a href="/about#citation">how to cite</a>.</p>` : '';
  const body = `
    <main style="max-width:720px;margin:0 auto;padding:2rem;font-family:system-ui,sans-serif;color:#c9d1d9">
      <h1>${escapeHtml(page.heading)}</h1>
      <p>${escapeHtml(page.intro)}</p>
      ${aboutExtra}
      ${apiDocsExtra}
      <p><a href="/">← Abyssal Claims interactive map</a></p>
    </main>`;
  res.type('html').send(wrapHtml(head, body, { hydrate: hydrates(req.path) }));
});

// /cite is a URL researchers guess — make it a real 301 to the citation section
// of /about (where the DOI + APA + BibTeX live), not a soft catch-all to the SPA.
app.get('/cite', (req, res) => res.redirect(301, '/about#citation'));

// Every crawl asks for /favicon.ico regardless of the <link rel="icon"> tag, and
// it 404'd on all of them (confirmed live 2026-08-17). We ship an SVG icon, and
// Google supports SVG favicons — so redirect rather than invent an .ico.
app.get('/favicon.ico', (req, res) => res.redirect(301, '/favicon.svg'));

// ── Dynamic sitemap index + sub-sitemaps ─────────────────────────────────
const API_HEADERS = { 'X-API-Key': ABYSSAL_API_KEY };

// Percent-encode the URI (spaces, non-ASCII in the path) BEFORE XML-escaping.
// escapeHtml only protects the XML document (& < > "); it does NOT make a raw
// space or a ° a valid URI. Two orthogonal layers — a <loc> needs both.
// new URL().href leaves legal path sub-delims (`:` `/`) untouched.
// Shared with every <link rel="canonical"> — see frontend/seo/urls.js. This
// used to be a private `new URL().href`, and the canonical builders used a
// different rule; the sitemap and the page then named different addresses.
const encodeLoc = normaliseUrl;

// ⚠️ `lastmod` is OPTIONAL here, and omitting it is the correct answer far more
// often than it looks. Google ignores the field entirely on a site whose values
// it has learned not to trust, and stamping today's date on a page that has not
// changed since April is exactly how a site teaches it that. Hub pages and the
// sitemap index used `new Date()` — i.e. "everything changed today", every day.
// Omit unless a real modification date is known.
function renderUrlset(entries) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries.map(e => `  <url>
    <loc>${escapeHtml(encodeLoc(e.loc))}</loc>${e.lastmod ? `
    <lastmod>${e.lastmod}</lastmod>` : ''}
    <changefreq>${e.changefreq}</changefreq>
    <priority>${e.priority}</priority>
  </url>`).join('\n')}
</urlset>`;
}

// Sitemap index — points to sub-sitemaps
app.get('/sitemap.xml', async (req, res) => {
  // No <lastmod>. It is optional in a sitemap index, and the only value we
  // could put here is today's date — which would claim both sub-sitemaps change
  // daily. They do not, and a lastmod Google has learned to distrust is worth
  // less than none: it stops reading the field for the whole site.
  const sitemaps = [
    { loc: `${SITE}/sitemap-core.xml` },
    { loc: `${SITE}/sitemap-seamounts.xml` },
  ];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${sitemaps.map(s => `  <sitemap>
    <loc>${escapeHtml(s.loc)}</loc>${s.lastmod ? `
    <lastmod>${s.lastmod}</lastmod>` : ''}
  </sitemap>`).join('\n')}
</sitemapindex>`;
  res.type('application/xml').set('Cache-Control', 'public, max-age=3600').send(xml);
});

// Sub-sitemap: core (everything except seamounts + blog)
app.get('/sitemap-core.xml', async (req, res) => {
  try {
    const apiRes = await fetch(`${VPS_API_URL}/v1/seo/sitemap/core`, {
      headers: API_HEADERS, signal: AbortSignal.timeout(15000),
    });
    if (!apiRes.ok) throw new Error(`API ${apiRes.status}`);
    const { entries } = await apiRes.json();

    // Append blog articles
    try {
      const blogRes = await fetch(`${VPS_API_URL}/v1/blog/articles`, {
        headers: API_HEADERS, signal: AbortSignal.timeout(5000),
      });
      if (blogRes.ok) {
        const articles = await blogRes.json();
        const today = new Date().toISOString().slice(0, 10);
        const capDate = d => (!d || d > today) ? today : d;
        entries.push(
          { loc: `${SITE}/blog`, lastmod: capDate(articles[0]?.published_at), changefreq: 'weekly', priority: '0.8' },
          ...articles.map(a => ({
            loc: `${SITE}/blog/${a.slug}`,
            lastmod: capDate(a.published_at),
            changefreq: 'monthly',
            priority: '0.7',
          }))
        );
      }
    } catch { /* blog skipped */ }

    // Hub pages + every pagination page. Both halves matter: the hub is the
    // parent path Google probes, and pages 2..N are where 37,389 of the 37,889
    // seamount links actually live — omitting them would leave the corpus
    // reachable only by walking `rel=next` 76 times.
    try {
      const hubs = await fetchHubIndex();
      // No lastmod: a hub's contents change when its dataset syncs, which is
      // not today, and we do not track that per hub. `changefreq` already says
      // what we actually know.
      for (const h of hubs || []) {
        for (let p = 1; p <= h.pages; p++) {
          entries.push({
            loc: p === 1 ? h.url : `${h.url}?page=${p}`,
            changefreq: 'weekly',
            // Page 1 is the entry point; deeper pages are pure plumbing.
            priority: p === 1 ? h.priority : '0.3',
          });
        }
      }
      entries.push({ loc: `${SITE}/contractors`, changefreq: 'monthly', priority: '0.7' });
    } catch (err) { console.error('sitemap hub entries skipped:', err.message); }

    res.type('application/xml').set('Cache-Control', 'public, max-age=3600').send(renderUrlset(entries));
  } catch (err) {
    console.error('sitemap-core failed:', err);
    res.status(500).send('Sitemap generation failed');
  }
});

// Sub-sitemap: seamounts (37k+ entries — separate to stay under 50k limit)
app.get('/sitemap-seamounts.xml', async (req, res) => {
  try {
    const apiRes = await fetch(`${VPS_API_URL}/v1/seo/sitemap/seamounts`, {
      headers: API_HEADERS, signal: AbortSignal.timeout(15000),
    });
    if (!apiRes.ok) throw new Error(`API ${apiRes.status}`);
    const { entries } = await apiRes.json();
    res.type('application/xml').set('Cache-Control', 'public, max-age=86400').send(renderUrlset(entries));
  } catch (err) {
    console.error('sitemap-seamounts failed:', err);
    res.status(500).send('Sitemap generation failed');
  }
});

// ── HTML escape helper ─────────────────────────────────────────────────
function escapeHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Embeddable risk widget — CORS-enabled, cacheable ───────────────────
app.get('/embed/concession/:id', async (req, res) => {
  try {
    const apiUrl = `${VPS_API_URL}/v1/seo/widget/concession/${encodeURIComponent(req.params.id)}`;
    const apiRes = await fetch(apiUrl, {
      headers: { 'X-API-Key': ABYSSAL_API_KEY },
      signal: AbortSignal.timeout(5000),
    });
    if (!apiRes.ok) return res.status(apiRes.status).send('Not found');
    const data = await apiRes.json();

    // ⛔ This card showed "High Risk (72%)" until 2026-09-21. The percentage came
    // from a backend formula — vent count × 0.3 + species × 0.005 + a flag × 0.3 —
    // whose weights nobody derived, and the card is EMBEDDABLE: that number went
    // onto other people's pages carrying our name. Backend no longer computes it.
    //
    // What replaces it is the one thing the flag actually means: whether the
    // concession polygon intersects an OBIS biodiversity hotspot. A fact, stated
    // as a fact, with the counts underneath it unchanged.
    const overlaps = data.data.overlaps_biodiversity_hotspot === true;
    const badgeColor = overlaps ? '#f59e0b' : 'rgba(255,255,255,0.18)';
    const badgeLabel = overlaps ? 'Overlaps a biodiversity hotspot' : 'No biodiversity-hotspot overlap';

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:system-ui,sans-serif; background:#0a0e14; color:#ccc; padding:16px; }
    .card { border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:16px; background:rgba(0,0,0,0.5); max-width:380px; }
    .name { font-size:14px; font-weight:600; color:#fff; margin-bottom:4px; }
    .risk { display:inline-block; font-size:11px; font-weight:600; padding:2px 8px; border-radius:4px; color:#fff; background:${badgeColor}; margin-bottom:12px; }
    .row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:12px; }
    .row:last-child { border:none; }
    .label { color:rgba(255,255,255,0.4); }
    .value { color:rgba(255,255,255,0.8); font-family:monospace; }
    .link { display:block; margin-top:12px; text-align:center; color:#22d3ee; font-size:11px; text-decoration:none; }
    .link:hover { color:#a5f3fc; }
  </style>
</head>
<body>
  <div class="card">
    <div class="name">${escapeHtml(data.name)}</div>
    <span class="risk">${badgeLabel}</span>
    <div class="row"><span class="label">ISA ID</span><span class="value">${escapeHtml(data.data.isa_id)}</span></div>
    <div class="row"><span class="label">Resource</span><span class="value">${escapeHtml(data.data.resource_type || '—')}</span></div>
    <div class="row"><span class="label">Area</span><span class="value">${data.data.area_km2 ? escapeHtml(data.data.area_km2.toLocaleString()) + ' km²' : '—'}</span></div>
    <div class="row"><span class="label">Vent conflicts</span><span class="value">${escapeHtml(String(data.data.vent_conflicts))}</span></div>
    <div class="row"><span class="label">Species nearby</span><span class="value">${escapeHtml(String(data.data.nearby_species))}</span></div>
    <a class="link" href="${escapeHtml(normaliseUrl(data.canonical_url))}" target="_blank" rel="noopener">View on Abyssal Claims →</a>
  </div>
</body>
</html>`;

    res.type('html')
      .set('Cache-Control', 'public, max-age=86400')
      .set('Access-Control-Allow-Origin', '*')
      .set('X-Frame-Options', 'ALLOWALL')
      .send(html);
  } catch (err) {
    console.error('Widget error:', err);
    res.status(500).send('Widget unavailable');
  }
});

// ── Home-page canonical, for crawlers only ───────────────────────────────
// The home page is the ONLY route with no SSR handler: /about and every entity
// page go through render-page.js (which emits a canonical), while "/" falls all
// the way through to the static handler below and gets the raw SPA shell. That
// shell deliberately carries no canonical (fixed 2026-07-24), so a crawler saw
// "/", "/?utm_source=…" and "/?layer=…" as three 200-byte-identical documents
// with nothing saying which is canonical. Measured 2026-08-12: all three
// 24 471 B, zero canonical tags, while /about had its own.
//
// ⚠️ Bot-only, and that is the whole design. Injecting this into the shell for
// everyone would recreate exactly the bug fixed 2026-07-24: a human loading "/"
// then client-side navigating to /privacy keeps this tag (react-helmet-async
// does not remove static tags) and /privacy declares itself a duplicate of "/".
// Crawlers fetch each URL independently and never SPA-navigate, so they cannot
// hit that. Do not "simplify" this by dropping the isBot check.
//
// The value must stay byte-identical to SEO.tsx's SITE_URL (no trailing slash).
// If Googlebot renders the JS it will also get helmet's canonical; two tags
// that disagree is worse than one, so they must agree exactly.
const HOME_CANONICAL = 'https://something-rare.com';
let homeShellForBots;

app.get('/', async (req, res, next) => {
  if (!isBot(req)) return next();
  try {
    if (homeShellForBots === undefined) {
      const raw = readFileSync(join(__dirname, 'dist', 'index.html'), 'utf8');
      if (/rel=["']canonical["']/i.test(raw)) {
        // A static canonical is back in the shell — injecting a second one
        // would be worse than doing nothing. Serve as-is and make the noise
        // visible: this also means every client-side route is once again
        // declaring itself a duplicate of "/" (the regression fixed 2026-07-24).
        console.warn('index.html already has a canonical — not injecting; check for the 2026-07-24 per-route-canonical regression');
        homeShellForBots = raw;
      } else {
        homeShellForBots = raw.replace(
          '<head>',
          `<head>\n    <link rel="canonical" href="${HOME_CANONICAL}" />`,
        );
      }
    }
    // The pre-render below `<main>` is a rich description of the corpus that
    // contains not one anchor — measured 2026-08-17, the bot copy of "/" had
    // ZERO `<a>` elements, so no crawler could reach any of the 40,300 entity
    // pages by following links. The hub nav is injected here rather than baked
    // into index.html because its counts are live.
    const hubs = await fetchHubIndex();
    const html = hubs
      ? homeShellForBots.replace(
          '</main>',
          `<h2>Browse the data</h2>${hubNavHtml(hubs, null)}</main>`,
        )
      : homeShellForBots; // never block the home page on the API
    return res.type('html').send(html);
  } catch (err) {
    // Never let this break the home page — fall through to the static handler,
    // which serves the same shell minus the canonical.
    console.error('home canonical injection failed:', err);
    return next();
  }
});

// Serve remaining dist files (index.html, robots.txt, etc.) with brotli/gzip if available.
app.use(expressStaticGzip(join(__dirname, 'dist'), {
  enableBrotli: true,
  orderPreference: ['br', 'gz'],
}));

// ── SPA shell for real routes, 404 for everything else ────────────────────
// This catch-all used to answer 200 with the shell for ANY path, so every
// mistyped or stale link became an indexable "page" that renders no content —
// a soft-404 factory (measured 2026-08-09: /foo/bar/baz returned 200 + 24 637 B).
//
// SPA_PATHS is now REACT_ROUTES + SERVER_ONLY_ROUTES from seo/route-categories.js,
// which is the same union this list always was — only now the two halves are named
// and the naming is load-bearing elsewhere (it decides who gets the client bundle).
// Adding a route to App.tsx without adding it to REACT_ROUTES turns it into a 404.

app.get('*', (req, res) => {
  // Two normalisations, both load-bearing:
  //  - trailing slash, so /about/ keeps working (same as the 410 block);
  //  - a trailing /index.html, because expressStaticGzip above REWRITES req.url
  //    for directory-ish paths while hunting for .br/.gz sidecars and does not
  //    restore it — so this handler sees "/about/index.html" for a request to
  //    "/about/". Verified by logging req.path here. Without this strip, /about/
  //    and /seamount/123/ 404 while /blog/ survives by accidentally matching
  //    the /blog/:slug pattern against the literal segment "index.html".
  const path = req.path.replace(/\/index\.html$/, '').replace(/\/+$/, '') || '/';
  if (SPA_PATHS.some(re => re.test(path))) {
    return res.sendFile(join(__dirname, 'dist', 'index.html'));
  }
  res.status(404).type('html').send(
    '<!doctype html><meta charset="utf-8">' +
    '<meta name="robots" content="noindex">' +
    '<title>Page not found | Abyssal Claims</title>' +
    '<style>body{background:#0b1220;color:#e2e8f0;font:16px/1.6 system-ui,sans-serif;' +
    'display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}' +
    'a{color:#22d3ee}</style>' +
    '<div><h1>404 — page not found</h1>' +
    '<p><a href="/">Go to the map</a></p></div>'
  );
});

process.on('uncaughtException', (err) => {
  console.error('Uncaught exception:', err);
  process.exit(1);
});

process.on('unhandledRejection', (reason) => {
  console.error('Unhandled rejection:', reason);
  process.exit(1);
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`BFF Proxy running on port ${PORT}`);
  console.log(`Forwarding /api to ${VPS_API_URL}`);
});
