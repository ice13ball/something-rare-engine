#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// Canonical checker  —  probes a running site with a crawler User-Agent
//
// The home page is the only route with no SSR handler: "/" falls through to the
// static handler and gets the raw SPA shell, which deliberately carries no
// canonical (fixed 2026-07-24). Measured on production 2026-08-12, "/",
// "/?utm_source=…" and "/?layer=…" were three byte-identical 200s with nothing
// declaring which one is canonical — so Google had to guess, and the guesses
// surface in the indexing report as "Duplicate, Google chose a different
// canonical" / "Alternative page with proper canonical tag".
//
// Two properties this asserts that a naive check would miss:
//
//   1. Redirects are NOT followed. A client that follows them reports /index.html
//      as 200 and hides the fact that the 301 is doing any work at all.
//   2. /about and one entity route must keep their OWN canonical. The failure
//      mode of "fix the home page" is canonicalising everything to "/", which
//      is strictly worse than the bug — it would deindex every real page.
//
// Usage:  node scripts/check-seo-canonicals.mjs [baseUrl]
//         node scripts/check-seo-canonicals.mjs http://localhost:8080
// Default target is production. Exits non-zero on the first failed assertion.
// ─────────────────────────────────────────────────────────────────────────────

const BASE = (process.argv[2] || 'https://something-rare.com').replace(/\/+$/, '');
const HOME_CANONICAL = 'https://something-rare.com';
const BOT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)';

async function probe(path) {
  const res = await fetch(BASE + path, {
    headers: { 'User-Agent': BOT },
    redirect: 'manual', // load-bearing — see header comment
  });
  const html = res.status >= 300 && res.status < 400 ? '' : await res.text();
  const canonicals = [...html.matchAll(/<link[^>]+rel=["']canonical["'][^>]*>/gi)]
    .map(m => (m[0].match(/href=["']([^"']+)["']/i) || [])[1]);
  return { status: res.status, canonicals, location: res.headers.get('location') };
}

const failures = [];
function check(label, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  — ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

// The home page and its two real query-string shapes. They are listed
// separately on purpose: ?utm_source= arrives on external/outreach links,
// ?layer= is how the app links to its own map layers. Different origins, same
// requirement, and a fix that handles one can miss the other.
const HOME_PATHS = ['/', '/?utm_source=check', '/?layer=wdpa'];

for (const p of HOME_PATHS) {
  const { status, canonicals } = await probe(p);
  check(
    `${p} → 200 with exactly one canonical == ${HOME_CANONICAL}`,
    status === 200 && canonicals.length === 1 && canonicals[0] === HOME_CANONICAL,
    `status ${status}, canonicals ${JSON.stringify(canonicals)}`,
  );
}

// Regression guard: fixing the home page must not canonicalise the site to "/".
for (const p of ['/about', '/seamount/28715']) {
  const { status, canonicals } = await probe(p);
  const want = `https://something-rare.com${p}`;
  check(
    `${p} keeps its own canonical`,
    status === 200 && canonicals.length === 1 && canonicals[0] === want,
    `status ${status}, canonicals ${JSON.stringify(canonicals)}`,
  );
}

// /index.html must stay a 301 — the other half of the duplicate-home problem.
{
  const { status, location } = await probe('/index.html');
  check('/index.html → 301', status === 301, `status ${status}, location ${location}`);
}

// ── No route may serve the home page's title ─────────────────────────────────
// A route with no SSR handler falls through to the static handler and gets the
// raw SPA shell — so it competes in the SERP under the HOME page's title and
// description. Found twice this way: "/" (missing canonical, fixed 2026-08-16) and
// /api-docs (position 14.9 under the wrong title, 2026-08-17). Two instances of
// one class is enough to test for the class rather than the instances, so this
// samples one URL per path shape in sitemap-core and fails on a shell title.
{
  const core = await (await fetch(`${BASE}/sitemap-core.xml`, { headers: { 'User-Agent': BOT } })).text();
  const locs = [...core.matchAll(/<loc>(.*?)<\/loc>/g)].map(m => m[1]);
  const shapeOf = u => {
    const seg = (new URL(u).pathname).split('/').filter(Boolean);
    return seg.length ? '/' + seg[0] + (seg.length > 1 ? '/:id' : '') : '/';
  };
  // Sitemap URLs are absolute and always point at production. Rewrite the
  // origin onto BASE, or pointing this script at dev silently tests production
  // and reports a failure the dev deploy has already fixed. (Observed.)
  const oneEach = new Map();
  for (const u of locs) {
    const shape = shapeOf(u);
    if (!oneEach.has(shape)) oneEach.set(shape, BASE + new URL(u).pathname);
  }

  const homeHtml = await (await fetch(BASE + '/', { headers: { 'User-Agent': BOT } })).text();
  const shellTitle = (homeHtml.match(/<title>(.*?)<\/title>/s) || [])[1]?.trim();

  const offenders = [];
  for (const [shape, u] of oneEach) {
    if (shape === '/') continue;
    const html = await (await fetch(u, { headers: { 'User-Agent': BOT } })).text();
    const title = (html.match(/<title>(.*?)<\/title>/s) || [])[1]?.trim();
    if (!title || title === shellTitle) offenders.push(`${shape} (${title || 'no title'})`);
  }
  check(
    `no sitemap-core route serves the shell title (${oneEach.size - 1} shapes checked)`,
    offenders.length === 0,
    offenders.join('; '),
  );
}

// ── The crawl path must exist ────────────────────────────────────────────────
// Measured on production 2026-08-17: the bot copy of "/" contained ZERO anchors
// and each entity page exactly one, back to "/". 40,300 URLs asserted by
// sitemap, none corroborated by a link — which is what GSC's "Discovered –
// currently not indexed" (29,241 URLs) reports. These assertions are about
// REACHABILITY, so they follow links rather than inspecting the router: a route
// table that looks right while the rendered HTML has no <a> is the exact defect.
{
  const anchorsOf = html => [...html.matchAll(/<a\s[^>]*href=["']([^"']+)["']/gi)].map(m => m[1]);
  const fetchBot = async p => (await fetch(BASE + p, { headers: { 'User-Agent': BOT } }));

  const homeHtml = await (await fetchBot('/')).text();
  const homeLinks = anchorsOf(homeHtml);
  check(
    '/ links to something (bot copy)',
    homeLinks.length > 0,
    `${homeLinks.length} anchors`,
  );

  // Hub pages, reached the way a crawler reaches them: by following the home
  // page's links, not from a hardcoded list. A hub that exists but is unlinked
  // is no better than no hub.
  const hubPaths = [...new Set(homeLinks
    .filter(u => /^https:\/\/something-rare\.com\/[a-z-]+$/.test(u))
    .map(u => new URL(u).pathname))]
    .filter(p => !['/about', '/api-docs', '/privacy', '/terms'].includes(p));

  check('/ links to at least 5 hub pages', hubPaths.length >= 5, hubPaths.join(' '));

  const reachedTypes = new Set();
  const badHubs = [];
  for (const p of hubPaths) {
    const res = await fetchBot(p);
    const html = await res.text();
    const links = anchorsOf(html);
    const canonical = (html.match(/<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']/i) || [])[1];
    if (res.status !== 200 || links.length < 2 || canonical !== `https://something-rare.com${p}`) {
      badHubs.push(`${p} (status ${res.status}, ${links.length} links, canonical ${canonical})`);
    }
    for (const l of links) {
      const m = l.match(/^https:\/\/something-rare\.com\/([a-z-]+)\/[^/]+$/);
      if (m) reachedTypes.add(m[1]);
    }
  }
  check('every hub is 200, self-canonical and non-empty', badHubs.length === 0, badHubs.join('; '));
  check(
    'entity pages are reachable from / by links alone',
    reachedTypes.size >= 8,
    `${reachedTypes.size} types: ${[...reachedTypes].sort().join(', ')}`,
  );

  // Paginated hubs: page 2 must be SELF-canonical (canonicalising it to page 1
  // would hide the links the hub exists to expose), and a page past the end must
  // be a real 404 rather than another soft-404.
  const paged = hubPaths.find(p => p === '/seamount') || hubPaths[0];
  const p2 = await fetchBot(`${paged}?page=2`);
  const p2Html = await p2.text();
  const p2Canon = (p2Html.match(/<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']/i) || [])[1];
  check(
    `${paged}?page=2 is self-canonical`,
    p2.status === 200 && p2Canon === `https://something-rare.com${paged}?page=2`,
    `status ${p2.status}, canonical ${p2Canon}`,
  );
  const pOver = await fetchBot(`${paged}?page=99999`);
  check(`${paged}?page=99999 → 404`, pOver.status === 404, `status ${pOver.status}`);

  // Entity pages must link onward, not just back to "/".
  const seamount = await (await fetchBot('/seamount/1204898')).text();
  const sLinks = anchorsOf(seamount).filter(u => /something-rare\.com\/[a-z-]+\//.test(u));
  check(
    '/seamount/1204898 links to related entities',
    sLinks.length > 0,
    `${sLinks.length} entity links`,
  );

  // ── The sitemap and the canonical must name the SAME address ────────────
  //
  // Added 2026-08-23 after 11 live URLs disagreed, in both directions:
  // /river/* over-encoded ':' to '%3A', and /report/chess:* left a raw space in
  // the href. Google's name for that is "Duplicate, Google chose different
  // canonical than user", and it is the whole reason this check exists.
  //
  // ⚠️ Every URL whose path carries anything beyond unreserved characters is
  // checked — not a hand-written list of the ids we already know about. A list
  // would pass forever the day a new id family arrives with a new character.
  const coreXml = await (await fetch(`${BASE}/sitemap-core.xml`, { headers: { 'User-Agent': BOT } })).text();
  const locs = [...coreXml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m =>
    m[1].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"'));
  check('sitemap-core.xml parsed', locs.length > 0, `${locs.length} <loc> entries`);

  const special = locs.filter(loc => {
    const path = loc.slice(loc.indexOf('/', 8));
    return /[^A-Za-z0-9/._~-]/.test(path);
  });
  check('special-character URLs found to check', special.length > 0, `${special.length} of ${locs.length}`);

  let mismatched = 0;
  for (const loc of special) {
    const path = loc.slice(loc.indexOf('/', 8));
    const { canonicals } = await probe(path);
    const canonical = canonicals[0];
    // Byte for byte. "Equivalent after decoding" is precisely the comparison
    // Google does NOT make.
    if (canonical !== loc) {
      mismatched += 1;
      console.log(`      sitemap:   ${loc}`);
      console.log(`      canonical: ${canonical ?? '(none)'}`);
    }
  }
  check(
    'every sitemap <loc> matches that page\'s canonical, byte for byte',
    mismatched === 0,
    `${special.length - mismatched}/${special.length} agree`,
  );

  // ── The report family, the three answers it owes a crawler ──────────────
  //
  // Added 2026-08-24, after an audit measured /report/* returning the homepage
  // byte for byte and filed it as a regression. It was not one: /report/ and
  // /claim-report/ are the last two UA-branching routes (`if (!isBot(req))
  // return next()` in server.js), so a plain curl legitimately gets the SPA
  // shell while a crawler gets SSR. Nothing in this checker said so, because
  // every probe here already sends a crawler UA — the gate was invisible to it.
  //
  // ⚠️ These three assertions are what the audit could not distinguish from
  // breakage. The shell is not asserted here on purpose; it is asserted in
  // check-entity-status.mjs, where a human UA can be sent against a controlled
  // backend. What matters to Google is only this column.
  {
    const reportCases = [
      ['/report/3902749', 200, 'a populated report'],
      ['/report/chess:Snake%20Pit', 410, 'an empty report'],
      ['/report/nie-ma-takiego', 404, 'an id that does not exist'],
      ['/claim-report/nie-ma', 404, 'an unknown claim report'],
    ];
    for (const [path, want, label] of reportCases) {
      const res = await fetch(BASE + path, { headers: { 'User-Agent': BOT }, redirect: 'manual' });
      check(`${label} (${path}) answers ${want} to a crawler`,
        res.status === want, `status ${res.status}`);
    }

    // The measurement the audit actually made, turned into an assertion: the
    // SSR report must not BE the homepage. Comparing against a fetched "/"
    // rather than a hardcoded byte count is the point — a shell that changes
    // size would otherwise walk out from under a numeric threshold.
    const homeBody = await (await fetch(BASE + '/', { headers: { 'User-Agent': BOT } })).text();
    const reportRes = await fetch(BASE + '/report/3902749', { headers: { 'User-Agent': BOT } });
    const reportBody = await reportRes.text();
    check('a populated report is not the homepage served under another URL',
      reportBody !== homeBody, `report ${reportBody.length} B vs home ${homeBody.length} B`);
    const canonical = (reportBody.match(/rel="canonical" href="([^"]+)"/) ?? [])[1];
    check('a populated report is self-canonical',
      canonical === `${BASE}/report/3902749`, canonical ?? '(none)');
  }

  // ── Withdrawn layers answer 410, not 404 ────────────────────────────────
  // WDPA came down 2026-09-03 pending written permission from UNEP-WCMC. Its
  // layer page was indexed, so the withdrawal has to read as deliberate: 404
  // tells Google the URL might return and it keeps it for weeks. A 200 empty
  // shell would be worse still — that is the de-indexing failure mode this
  // whole checker exists to catch.
  {
    const res = await fetch(BASE + '/layer/wdpa',
      { headers: { 'User-Agent': BOT }, redirect: 'manual' });
    check('the withdrawn WDPA layer page answers 410 to a crawler',
      res.status === 410, `status ${res.status}`);
    const body = await res.text();
    check('the withdrawn WDPA page is not a 200 shell',
      res.status !== 200, `status ${res.status}, ${body.length} B`);
  }

  // KBA came down the same day: BirdLife's KBA terms carry the same clause,
  // plus a separate no-commercial-use clause.
  {
    const res = await fetch(BASE + '/layer/kbas',
      { headers: { 'User-Agent': BOT }, redirect: 'manual' });
    check('the withdrawn KBA layer page answers 410 to a crawler',
      res.status === 410, `status ${res.status}`);
    const body = await res.text();
    check('the withdrawn KBA page is not a 200 shell',
      res.status !== 200, `status ${res.status}, ${body.length} B`);
  }

  // ── Security headers ────────────────────────────────────────────────────
  //
  // Added 2026-08-24, when this origin was measured sending none of the six.
  // Checked on three response shapes on purpose: a 200 HTML page, an entity
  // page, and a 410 — error responses are exactly where header middleware gets
  // bypassed, and we introduced a 410 path the day before.
  //
  // ⚠️ /embed/* is excluded from the framing assertion by design. It is a
  // widget for third-party pages; asserting DENY there would enshrine a bug.
  const REQUIRED_HEADERS = [
    ['strict-transport-security', /max-age=\d+/],
    ['x-content-type-options', /^nosniff$/],
    ['referrer-policy', /strict-origin-when-cross-origin/],
    ['permissions-policy', /geolocation=\(\)/],
    ['x-frame-options', /^DENY$/],
    ['content-security-policy-report-only', /frame-ancestors 'none'/],
  ];
  for (const [path, label] of [
    ['/', 'home'],
    ['/river/arcticgro:kolyma', 'entity'],
    ['/report/chess:Snake%20Pit', '410'],
  ]) {
    const res = await fetch(BASE + path, { headers: { 'User-Agent': BOT }, redirect: 'manual' });
    const missing = REQUIRED_HEADERS
      .filter(([name, pattern]) => !pattern.test(res.headers.get(name) ?? ''))
      .map(([name]) => name);
    check(
      `${label} (${path}) carries all six security headers`,
      missing.length === 0,
      missing.length ? `status ${res.status}, missing/wrong: ${missing.join(', ')}` : `status ${res.status}`,
    );
  }

  // The widget must stay embeddable — the inverse assertion, so a future
  // blanket DENY fails here instead of silently breaking third-party pages.
  const embedRes = await fetch(BASE + '/embed/concession/BGRPMN1X_East_a', {
    headers: { 'User-Agent': BOT }, redirect: 'manual',
  });
  check(
    '/embed/* is NOT frame-denied (it is a third-party widget)',
    (embedRes.headers.get('x-frame-options') ?? '') !== 'DENY'
      && !/frame-ancestors 'none'/.test(embedRes.headers.get('content-security-policy-report-only') ?? ''),
    `x-frame-options ${embedRes.headers.get('x-frame-options') ?? '(none)'}`,
  );

  // Crawls request /favicon.ico regardless of the <link rel="icon"> tag.
  const fav = await fetch(BASE + '/favicon.ico', { headers: { 'User-Agent': BOT }, redirect: 'manual' });
  check('/favicon.ico is not a 404', fav.status !== 404, `status ${fav.status}`);
}

console.log(
  failures.length
    ? `\n${failures.length} check(s) failed against ${BASE}`
    : `\nAll canonical checks passed against ${BASE}`,
);
process.exit(failures.length ? 1 : 0);
