/**
 * Server-side HTML renderer for pSEO pages.
 * Fetches data from backend API and returns semantic HTML for crawlers.
 * Human visitors get the React SPA which hydrates the map.
 */

import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { canonicalUrl, normaliseJsonLd, normaliseUrl } from './urls.js';
import { fetchUpstream, BackendUnavailable } from './upstream-fetch.js';
import { CONSENT_BANNER_HTML } from './consent-banner.js';

// Fallback repointed 2026-08-24 — see the note in server.js. The old default
// named a host that no longer exists.
const BASE_URL = process.env.VPS_API_URL || 'https://apiv2.something-rare.com';
const API_KEY = process.env.ABYSSAL_API_KEY;

// Site-wide JSON-LD graph (WebSite + WebApplication + source Datasets), the SAME
// object the client SPA injects (frontend/src/components/SEO.tsx imports it too).
// Bots get a static SSR snapshot and never run the client JS, so without this the
// rich @graph — every source dataset, its DOI, licence and author — never reached
// Googlebot on the 40k /concession, /vent, /seamount… subpages. Injected once here.
const require = createRequire(import.meta.url);
const _siteGraph = require('./site-graph.json');
const SITE_GRAPH_JSON = JSON.stringify(_siteGraph).replace(/<\//g, '<\\/');

// Citation facts, derived from the SAME single-source graph (never re-typed) so
// the SSR /about + /cite pages can't drift from the JSON-LD or the client copy.
const _wa = _siteGraph['@graph'].find(n => n['@type'] === 'WebApplication') || {};
// ⛔ TWO records, and they are not interchangeable. `identifier` on the
// WebApplication node is the SOFTWARE record (AGPL-3.0-or-later); its
// `citation` is the METHODS documentation (CC-BY-4.0). The software record's
// own Zenodo metadata says `isDocumentedBy` the other one — cite the
// documentation for the method, the code record for the code. Swapping them
// puts a CC-BY licence on AGPL software on a page people quote.
//
// ⚠️ No `||` fallbacks any more. A default that silently substitutes a DOI is
// the one thing a citation surface must never do: a typo in the graph would
// have produced a confident, wrong citation instead of a failure.
const _cite = _wa.citation || {};
function _need(value, what) {
  if (!value) {
    throw new Error(
      `site-graph.json is missing ${what}. The citation blocks on /about and ` +
      `/cite are rendered from it, and a missing value here would otherwise ` +
      `fall back to a hardcoded DOI that nobody would notice was stale.`,
    );
  }
  return value;
}
export const siteCitation = {
  // The code: what the running platform IS.
  doiUrl: _need(_wa.identifier, 'WebApplication.identifier (the code DOI)'),
  doi: _need(_wa.identifier, 'WebApplication.identifier').replace('https://doi.org/', ''),
  zenodoUrl: _need(_wa.sameAs && _wa.sameAs[0], 'WebApplication.sameAs[0]'),
  licenceUrl: _need(_wa.license, 'WebApplication.license'),
  licenceName: 'AGPL-3.0-or-later',
  // The methods documentation: what the platform is DESCRIBED by.
  docsDoiUrl: _need(_cite.identifier, 'WebApplication.citation.identifier (the docs DOI)'),
  docsDoi: _need(_cite.identifier, 'WebApplication.citation.identifier')
    .replace('https://doi.org/', ''),
  docsLicenceName: 'CC-BY-4.0',
  author: _need(_wa.creator && _wa.creator.name, 'WebApplication.creator.name'),
  orcidUrl: _need(_wa.creator && _wa.creator.url, 'WebApplication.creator.url'),
};

/**
 * "The backend could not tell me" — as distinct from "the backend told me no".
 *
 * ⚠️ These are two different facts and they need two different HTTP answers.
 * Until 2026-08-18 every SEO fetch collapsed them into one `null`, and the
 * handler read that `null` as "unknown id" and fell through to the SPA shell,
 * which answers **200**. So a backend outage did not look like an outage to
 * Google: it looked like ~40,300 URLs that had simultaneously become blank
 * pages and were confidently still 200. A 503 says "ask again"; a 200 says
 * "this is the page". Collapsing the two is silent de-indexing.
 *
 * Callers that catch this must answer 503 + Retry-After, never 404 and never
 * 200. See `sendUnavailable` in server.js.
 *
 * The classification itself (which statuses mean "missing" vs "broken", and
 * the single retry on a transient 502/503) lives in `./upstream-fetch.js`,
 * shared with server.js's `fetchEntity` and its hub-index loop — three copies
 * of this decision is how it drifted before.
 */
// A page that exists, resolves, and has nothing to say.
//
// ⛔ Distinct from BackendUnavailable (our failure → 503) and from a null return
// (id unknown → 404). This one means: the id resolved, and the resulting page
// would render its every figure as an em dash. Google calls that a soft 404 and
// it is right; answering 200 is what earned the "Soft 404" reason on 2026-08-23.
export class EntityGone extends Error {
  constructor(message) {
    super(message);
    this.name = 'EntityGone';
  }
}

export { BackendUnavailable };

/**
 * The single discriminator, delegated to the shared `fetchUpstream` (see
 * `./upstream-fetch.js` for the missing/broken status sets and the retry).
 * Returns parsed JSON, or `null` for a genuine "does not exist", and throws
 * BackendUnavailable for everything else.
 */
async function fetchJsonOrThrow(url, timeoutMs = 5000) {
  return fetchUpstream(url, {
    timeoutMs,
    fetchImpl: (u, opts) => fetch(u, { ...opts, headers: { 'X-API-Key': API_KEY } }),
  });
}

async function fetchSeoData(path) {
  return fetchJsonOrThrow(`${BASE_URL}/v1/seo${path}`);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderHead(meta) {
  // ⛔ The ONE place an entity page names itself. Every backend `canonical_url`
  // arrives as a raw f-string — `/report/chess:Snake Pit` with a literal space —
  // so it is normalised here rather than at each of the ten builders, which is
  // how the sitemap and the canonical drifted apart in the first place.
  const canonical = normaliseUrl(meta.canonical_url);
  return `
    <title>${escapeHtml(meta.title)}</title>
    <meta name="description" content="${escapeHtml(meta.description)}" />
    <link rel="canonical" href="${escapeHtml(canonical)}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${escapeHtml(canonical)}" />
    <meta property="og:title" content="${escapeHtml(meta.title)}" />
    <meta property="og:description" content="${escapeHtml(meta.description)}" />
    <meta property="og:image" content="https://something-rare.com/og.jpg" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${escapeHtml(meta.title)}" />
    <meta name="twitter:description" content="${escapeHtml(meta.description)}" />
    <script type="application/ld+json">${JSON.stringify(normaliseJsonLd(meta.json_ld)).replace(/<\//g, '<\\/')}</script>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  `;
}

function renderConcession(data) {
  const d = data;
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>${escapeHtml(d.contractor_name)} — ISA Mining Concession ${escapeHtml(d.isa_id)}</h1>
      <p>${escapeHtml(d.meta.description)}</p>

      <h2>Contract Details</h2>
      <table>
        <tr><td>ISA ID</td><td>${escapeHtml(d.isa_id)}</td></tr>
        <tr><td>Resource Type</td><td>${escapeHtml(d.resource_type || '—')}</td></tr>
        <tr><td>Area</td><td>${d.area_km2 ? d.area_km2.toLocaleString() + ' km²' : '—'}</td></tr>
        <tr><td>Issued</td><td>${escapeHtml(d.act_date || '—')}</td></tr>
        <tr><td>Expires</td><td>${escapeHtml(d.expiry_date || '—')}</td></tr>
        <tr><td>Jurisdiction</td><td>${escapeHtml(d.jurisdiction_text || '—')}</td></tr>
        <!-- This row names what the is_high_risk column measures: an
             ST_Intersects between the concession polygon and an OBIS
             biodiversity hotspot, set in domains/isa.py. It used to carry a
             verdict word instead, which was ours, not the source's. -->
        <tr><td>Biodiversity hotspot overlap</td><td>${d.is_high_risk ? 'Yes (OBIS)' : 'No'}</td></tr>
      </table>

      <h2>Environmental Impact</h2>
      <ul>
        <li>${d.vent_conflicts} hydrothermal vent(s) within 50 km</li>
        <li>${d.nearby_species} deep-sea species documented nearby (OBIS)</li>
        <li>${d.nearby_argo_floats} Argo float(s) monitoring this zone</li>
        ${d.nearest_unesco_site ? `<li>UNESCO site nearby: ${escapeHtml(d.nearest_unesco_site)} (${d.nearest_unesco_dist_km?.toFixed(0)} km)</li>` : ''}
        ${d.nearest_eez_country ? `<li>Nearest EEZ: ${escapeHtml(d.nearest_eez_country)} (${d.nearest_eez_dist_km?.toFixed(0)} km)</li>` : ''}
        ${d.nearby_gbif_species > 0 ? `<li>${d.nearby_gbif_species} additional deep-sea species from GBIF within 50 km</li>` : ''}
        ${d.nearby_onc_stations > 0 ? `<li>${d.nearby_onc_stations} ONC cabled observatory node(s) within 200 km</li>` : ''}
        ${d.nearby_oceansites_moorings > 0 ? `<li>${d.nearby_oceansites_moorings} OceanSITES mooring station(s) within 500 km</li>` : ''}
      </ul>

      <h2>Location</h2>
      <p>Centroid: ${d.centroid_lat?.toFixed(4)}°N, ${d.centroid_lon?.toFixed(4)}°E</p>

      <p><a href="https://something-rare.com/">View on interactive 3D map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: International Seabed Authority, InterRidge v3.4, OBIS, Argo Programme</p>
    </main>
  `;
}

function renderVent(data) {
  const d = data;
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>${escapeHtml(d.name)} — ${escapeHtml(d.status)} Hydrothermal Vent</h1>
      <p>${escapeHtml(d.meta.description)}</p>

      <h2>Physical Data</h2>
      <table>
        <tr><td>Status</td><td>${escapeHtml(d.status)}</td></tr>
        <tr><td>Depth</td><td>${d.depth_m ? d.depth_m.toLocaleString() + ' m' : '—'}</td></tr>
        <tr><td>Latitude</td><td>${d.latitude.toFixed(5)}°</td></tr>
        <tr><td>Longitude</td><td>${d.longitude.toFixed(5)}°</td></tr>
      </table>

      ${d.nearby_concessions.length > 0 ? `
        <h2>Nearby Mining Concessions</h2>
        <ul>${d.nearby_concessions.map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>
        <p>Mining near active hydrothermal vents threatens unique ecosystems found nowhere else on Earth.</p>
      ` : '<p>No mining concessions within 50 km.</p>'}

      <p><a href="https://something-rare.com/">View on interactive 3D map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: InterRidge Database v3.4 (PANGAEA)</p>
    </main>
  `;
}

// v2 shape has no successor for a page that resolves but has nothing to show:
// old `reportHasStatistics` (report-shape.js) tested `narrative` / `key_stats`,
// neither of which exist any more. `summary` is a FIXED three-key struct the
// backend always sends, so "does it have keys" would always be true and the
// soft-404 gate would never fire again. Test the values instead: a headline,
// or at least one nonzero count, means the page has something to say.
function reportHasContent(data) {
  if (!data) return false;
  const headline = typeof data.headline === 'string' ? data.headline.trim() : '';
  if (headline.length > 0) return true;
  const summary = data.summary && typeof data.summary === 'object' ? data.summary : {};
  if (Object.values(summary).some(v => typeof v === 'number' && v > 0)) return true;
  if (typeof data.measurement_count === 'number' && data.measurement_count > 0) return true;
  if (typeof data.concession_count === 'number' && data.concession_count > 0) return true;
  if (Array.isArray(data.claim_summaries) && data.claim_summaries.length > 0) return true;
  return false;
}

function renderReport(data) {
  const d = data;
  const summary = d.summary || {};

  const claimsHtml = (d.claim_summaries || []).map(c => `
    <tr>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.concession_id || '')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.contractor_name || '')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${typeof c.min_distance_km === 'number' ? c.min_distance_km.toFixed(1) + ' km' : '—'}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.attributed_measurement_count ?? '—'}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.profiles_within_50km ?? '—'}</td>
    </tr>
  `).join('');

  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>Environmental Data Report — Argo Float ${escapeHtml(String(d.platform_id))}</h1>
      ${d.headline ? `<p>${escapeHtml(d.headline)}</p>` : ''}

      <h2>Summary</h2>
      <table>
        ${typeof summary.concessions_within_50km === 'number' ? `<tr><td>Concessions within 50 km</td><td>${summary.concessions_within_50km}</td></tr>` : ''}
        ${typeof summary.measurements_below_baseline_p5 === 'number' ? `<tr><td>Measurements below baseline p5</td><td>${summary.measurements_below_baseline_p5}</td></tr>` : ''}
        ${typeof summary.plume_backtracks_intersecting_concession === 'number' ? `<tr><td>Plume backtracks intersecting a concession</td><td>${summary.plume_backtracks_intersecting_concession}</td></tr>` : ''}
        ${typeof d.measurement_count === 'number' ? `<tr><td>Measurements Analyzed</td><td>${d.measurement_count}</td></tr>` : ''}
        ${typeof d.concession_count === 'number' ? `<tr><td>Concessions Referenced</td><td>${d.concession_count}</td></tr>` : ''}
      </table>

      ${d.claim_summaries && d.claim_summaries.length > 0 ? `
        <h2>Nearby Mining Concessions (${d.claim_summaries.length})</h2>
        <table style="width:100%;border-collapse:collapse">
          <tr style="color:#888">
            <th style="text-align:left;padding:4px 8px">Concession ID</th>
            <th style="text-align:left;padding:4px 8px">Contractor</th>
            <th style="text-align:left;padding:4px 8px">Min Distance</th>
            <th style="text-align:left;padding:4px 8px">Attributed Measurements</th>
            <th style="text-align:left;padding:4px 8px">Profiles within 50 km</th>
          </tr>
          ${claimsHtml}
        </table>
      ` : ''}

      <p style="margin-top:2rem"><a href="${escapeHtml(canonicalUrl('/report', d.platform_id))}">View full interactive report →</a></p>
      ${d.generated_at ? `<p style="color:#666;font-size:0.8em">Generated: ${escapeHtml(String(d.generated_at))} | Data: Argo Programme, CMEMS, ISA, InterRidge v3.4, OBIS</p>` : ''}
    </main>
  `;
}

function renderSeamount(data) {
  const d = data;

  // Related links. Only real neighbours: the block is omitted entirely when
  // nothing is within 100 km (2.2% of seamounts — genuinely isolated ones).
  // A filler list would be a link farm with extra steps.
  const nearby = d.nearby_seamounts || [];
  const relatedHtml = nearby.length ? `
      <h2>Nearby seamounts</h2>
      <ul>${nearby.map(n => `<li>
        <a href="https://something-rare.com/seamount/${n.peak_id}">Seamount #${n.peak_id}</a>
        — ${n.dist_km.toLocaleString()} km away${n.height_m ? `, ${Math.round(n.height_m).toLocaleString()} m tall` : ''}
      </li>`).join('')}</ul>` : '';

  const concessionHtml = d.nearby_concession ? `
      <h2>Nearest ISA concession</h2>
      <p><a href="https://something-rare.com/concession/${escapeHtml(d.nearby_concession.isa_id)}">${escapeHtml(d.nearby_concession.isa_id)}</a>
      ${d.nearby_concession.contractor_name ? `(${escapeHtml(d.nearby_concession.contractor_name)})` : ''}
      — ${d.nearby_concession.dist_km.toLocaleString()} km away.
      Proximity is not a statement about this seamount's status.</p>` : '';

  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>Seamount #${d.peak_id}${d.in_concession ? ' — Near an ISA Mining Concession' : ''}</h1>
      <p>${escapeHtml(d.meta.description)}</p>

      <h2>Physical Data</h2>
      <table>
        <tr><td>Height</td><td>${d.height_m ? d.height_m.toLocaleString() + ' m' : '—'}</td></tr>
        <tr><td>Summit Depth</td><td>${d.summit_depth_m ? d.summit_depth_m.toLocaleString() + ' m' : '—'}</td></tr>
        <tr><td>Area</td><td>${d.area_km2 ? d.area_km2.toFixed(1) + ' km²' : '—'}</td></tr>
        <tr><td>Latitude</td><td>${d.latitude.toFixed(5)}°</td></tr>
        <tr><td>Longitude</td><td>${d.longitude.toFixed(5)}°</td></tr>
      </table>

      ${concessionHtml}
      ${relatedHtml}

      <p><a href="https://something-rare.com/">View on interactive 3D map →</a>
       · <a href="https://something-rare.com/seamount">All seamounts</a></p>
      <p style="color:#666;font-size:0.8em">Data: Yesson et al. 2011 / PANGAEA</p>
    </main>
  `;
}

function renderOceansites(data) {
  const d = data;
  const claimLinks = d.nearby_concessions.map(name =>
    `<li>${escapeHtml(name)}</li>`
  ).join('');
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>${escapeHtml(d.name)} — OceanSITES Mooring Station</h1>
      <p>${escapeHtml(d.meta.description)}</p>

      <h2>Station Details</h2>
      <table>
        <tr><td>Station Code</td><td>${escapeHtml(d.ref)}</td></tr>
        <tr><td>Network</td><td>${escapeHtml(d.network)}</td></tr>
        <tr><td>Status</td><td>${escapeHtml(d.status)}</td></tr>
        <tr><td>Latitude</td><td>${d.lat.toFixed(4)}°</td></tr>
        <tr><td>Longitude</td><td>${d.lon.toFixed(4)}°</td></tr>
        ${d.deploy_date ? `<tr><td>Deployed</td><td>${escapeHtml(String(d.deploy_date))}</td></tr>` : ''}
      </table>

      ${d.nearby_concessions.length > 0 ? `
        <h2>Nearby Mining Concessions (within 500 km)</h2>
        <ul>${claimLinks}</ul>
        <p>Long-term climate monitoring baselines at this station may be affected by sediment plumes and seismic noise from nearby deep-sea mining operations.</p>
      ` : '<p>No active mining concessions within 500 km of this station.</p>'}

      <p><a href="https://something-rare.com/">View on interactive 3D map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: OceanSITES network / NDBC (NOAA) — public domain</p>
    </main>
  `;
}

function renderOnc(data) {
  const d = data;
  const claimLinks = d.nearby_concessions.map(name =>
    `<li>${escapeHtml(name)}</li>`
  ).join('');
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>${escapeHtml(d.name)} — ONC Seafloor Observatory</h1>
      <p>${escapeHtml(d.meta.description)}</p>

      <h2>Observatory Details</h2>
      <table>
        <tr><td>Station Code</td><td>${escapeHtml(d.location_code)}</td></tr>
        ${d.depth_m != null ? `<tr><td>Depth</td><td>${Number(d.depth_m).toLocaleString()} m</td></tr>` : ''}
        <tr><td>Latitude</td><td>${d.lat.toFixed(4)}°</td></tr>
        <tr><td>Longitude</td><td>${d.lon.toFixed(4)}°</td></tr>
      </table>

      ${d.description ? `<p>${escapeHtml(d.description)}</p>` : ''}

      ${d.nearby_concessions.length > 0 ? `
        <h2>Nearby Mining Concessions (within 200 km)</h2>
        <ul>${claimLinks}</ul>
        <p>This ONC cabled observatory provides real-time seismic, pressure, and chemistry data that would record any seafloor disturbance from nearby mining operations.</p>
      ` : '<p>No active mining concessions within 200 km of this node.</p>'}

      <p><a href="https://something-rare.com/">View on interactive 3D map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: Ocean Networks Canada — Oceans 3.0 API (CC BY 4.0)</p>
    </main>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// The built client entry, resolved ONCE from dist/index.html.
//
// This file is never processed by Vite, so the `<script src="/src/main.tsx">`
// it used to hardcode — copied from index.html, where Vite rewrites it — shipped
// verbatim to production and 404'd on every SSR page. Confirmed live 2026-08-18:
// /src/main.tsx 404, /assets/index-*.js 200.
//
// ⛔ Never hardcode the hash: it changes every build, and a stale one fails
// silently because a 404 script tag produces no server error. ⛔ Never fall back
// to '/src/main.tsx' on a miss — that restores this bug and hides it again.
// Throwing at module load takes the whole server down loudly instead, which is
// the correct trade for an asset every page depends on.
// Pure so the failure path can be proven. A checker that can only ever go green
// proves nothing, and this throw is the whole safety mechanism.
export function parseBuiltAssets(html) {
  const script = html.match(/<script[^>]+src="(\/assets\/[^"]+\.js)"/);
  if (!script) throw new Error('render-page: cannot resolve the built JS entry from dist/index.html');
  const style = html.match(/<link[^>]+rel="stylesheet"[^>]+href="(\/assets\/[^"]+\.css)"/)
    || html.match(/<link[^>]+href="(\/assets\/[^"]+\.css)"[^>]+rel="stylesheet"/);
  // The stylesheet is optional (a build may inline all CSS); the entry is not.
  return { entry: script[1], style: style ? style[1] : null };
}

export const BUILT_ASSETS = (() => {
  const path = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist', 'index.html');
  let html;
  try {
    html = readFileSync(path, 'utf8');
  } catch (err) {
    throw new Error(
      `render-page: cannot read ${path} — every server-rendered page needs the built `
      + `client entry from it. Run \`npm run build\` before \`npm start\`. (${err.code})`,
    );
  }
  return parseBuiltAssets(html);
})();

// ─────────────────────────────────────────────────────────────────────────────
// The GA4 + Consent Mode v2 bootstrap, copied ONCE from dist/index.html.
//
// Until 2026-09-23 only `/` carried it: every page built here — entity pages,
// hubs, /blog, /about — sent nothing to GA4, so search traffic landing on them
// was invisible (/seamount/4873694: 18 Search Console clicks, 0 GA4 views).
//
// ⛔ Copied, never re-typed. The block's order IS the compliance: consent
// default → stored-choice restore → loader → config. A second hand-written copy
// is a second place where that order can drift. index.html marks the block with
// `ga4-bootstrap:start` / `:end`, and `/` keeps serving it unchanged.
//
// ⛔ A missing block does not throw, unlike BUILT_ASSETS above: without it the
// pages still render correctly and only measurement is lost, which is not worth
// taking the site down for. It is logged loudly, and the render guard in
// src/__tests__/ga4-bootstrap-on-every-page.test.ts fails on it before deploy.
export function parseGa4Bootstrap(html) {
  const m = html.match(/<!-- ga4-bootstrap:start[\s\S]*?-->([\s\S]*?)<!-- ga4-bootstrap:end -->/);
  return m ? m[1].trim() : '';
}

export const GA4_BOOTSTRAP = (() => {
  const path = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist', 'index.html');
  const block = parseGa4Bootstrap(readFileSync(path, 'utf8'));
  if (!block) console.error(`render-page: no ga4-bootstrap block in ${path}; server-rendered pages will not be measured`);
  return block;
})();

/**
 * @param {string} headContent
 * @param {string} bodyContent
 * @param {{hydrate: boolean}} opts  REQUIRED — see the note below.
 *
 * `hydrate` is not a convenience flag; it is the page's declared category, and
 * getting it wrong breaks the page in one of two opposite ways:
 *
 *   hydrate: true  — App.tsx HAS a <Route> for this path. React boots and
 *                    replaces the server DOM with the real application.
 *   hydrate: false — App.tsx has NO route for it. SSR is the only renderer.
 *
 * ⚠️ Emitting the bundle on a path React cannot route is WORSE than the bug it
 * looks like it fixes. main.tsx calls `createRoot(...).render(...)`, which
 * REPLACES #root rather than hydrating it, and App.tsx has no `path="*"` route —
 * so React would boot, match nothing, and blank a page that was rendering fine.
 * The naive "just point the script at the real bundle" fix does exactly that to
 * /onc, /oceansites, /river, /resource, /contractor and /contractors.
 *
 * The category is decided in ONE place — `hydrates()` in server.js, driven by
 * REACT_ROUTES — never per call site, so it cannot drift page by page.
 */
function wrapHtml(headContent, bodyContent, opts) {
  if (!opts || typeof opts.hydrate !== 'boolean') {
    throw new TypeError('wrapHtml: opts.hydrate must be declared explicitly (true | false)');
  }
  let clientAssets;
  if (!opts.hydrate) {
    clientAssets = '  <!-- No client bundle: App.tsx has no route for this path, so booting\n'
      + '       React here would replace the server-rendered page with nothing. -->';
  } else {
    const tags = [];
    if (BUILT_ASSETS.style) tags.push(`  <link rel="stylesheet" crossorigin href="${BUILT_ASSETS.style}" />`);
    tags.push(`  <script type="module" crossorigin src="${BUILT_ASSETS.entry}"></script>`);
    clientAssets = tags.join('\n');
  }
  // AGPL-3.0 §13 and our own §7(b) additional term both require the notice to be
  // reachable from the running program, not only from the repository. Putting it
  // here rather than in each renderer is the whole point: there are fourteen
  // render* functions and every one of them builds its own markup, so a notice
  // added per-renderer is a notice that the fifteenth will not have.
  //
  // Emitted for EVERY page this shell builds, hydrated or not. The first version
  // suppressed it on hydrated pages, assuming React would render FooterLinks
  // there instead — it does not: FooterLinks mounts only inside MapApp, the
  // component for `/`, and `/` is served from the static dist/index.html and
  // never passes through here at all. So the suppression silently stripped the
  // notice from /blog, /rivers, /resources and every entity page and bought
  // nothing. Verified on the deployed dev host before and after.
  // It sits OUTSIDE #root so hydration cannot wipe it.
  const licenceNotice = `  <footer style="padding:24px 16px;color:#5a6a7a;font:12px/1.6 system-ui,sans-serif;text-align:center">
    Abyssal Claims — <a href="https://github.com/ice13ball/something-rare-engine" style="color:#7aa2c2">source code</a>,
    licensed <a href="https://www.gnu.org/licenses/agpl-3.0.html" style="color:#7aa2c2">AGPL-3.0-or-later</a>.
    Based on Abyssal Claims — &copy; 2026 Michal Mazurowski.
  </footer>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  ${GA4_BOOTSTRAP}
  ${headContent}
  <script type="application/ld+json">${SITE_GRAPH_JSON}</script>
</head>
<body style="background:#0a0e14;margin:0">
  <div id="root">${bodyContent}</div>
${licenceNotice}
${CONSENT_BANNER_HTML}
${clientAssets}
</body>
</html>`;
}

async function fetchClaimReportSeoData(isaId) {
  return fetchJsonOrThrow(`${BASE_URL}/v2/reports/seo/concession/${isaId}`);
}

function renderClaimReport(data) {
  const d = data;

  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>Environmental Data Report — ${escapeHtml(d.contractor_name || d.isa_id)} (${escapeHtml(d.isa_id)})</h1>
      ${d.headline ? `<p>${escapeHtml(d.headline)}</p>` : ''}

      <h2>Summary</h2>
      <table>
        ${d.resource_type ? `<tr><td>Resource Type</td><td>${escapeHtml(d.resource_type)}</td></tr>` : ''}
        ${typeof d.area_km2 === 'number' ? `<tr><td>Concession Area</td><td>${d.area_km2.toLocaleString()} km²</td></tr>` : ''}
        ${typeof d.species_count === 'number' ? `<tr><td>Species Documented</td><td>${d.species_count}</td></tr>` : ''}
        ${typeof d.species_inside_count === 'number' ? `<tr><td>Species Documented Inside Concession</td><td>${d.species_inside_count}</td></tr>` : ''}
        ${typeof d.species_search_radius_km === 'number' ? `<tr><td>Species Search Radius</td><td>${d.species_search_radius_km} km</td></tr>` : ''}
        ${typeof d.vent_count === 'number' ? `<tr><td>Hydrothermal Vents</td><td>${d.vent_count}</td></tr>` : ''}
        ${typeof d.seamount_count === 'number' ? `<tr><td>Seamounts</td><td>${d.seamount_count}</td></tr>` : ''}
        ${typeof d.monitoring_float_count === 'number' ? `<tr><td>Monitoring Floats Nearby</td><td>${d.monitoring_float_count}</td></tr>` : ''}
      </table>

      <p style="margin-top:2rem"><a href="https://something-rare.com/claim-report/${escapeHtml(d.isa_id)}">View full interactive report →</a></p>
      ${d.generated_at ? `<p style="color:#666;font-size:0.8em">Generated: ${escapeHtml(String(d.generated_at))} | Data: ISA, InterRidge v3.4, OBIS, Argo Programme</p>` : ''}
    </main>
  `;
}

async function fetchReportSeoData(platformId) {
  return fetchJsonOrThrow(`${BASE_URL}/v2/reports/seo/${platformId}`);
}

// ── Simple markdown → HTML converter (handles article subset only) ────────
function mdToHtml(md) {
  const lines = md.split('\n');
  const out = [];
  let inList = false;
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    // Inline: escape HTML first, then apply formatting
    const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    line = esc(line);
    // inline formatting (after escaping so we don't double-escape)
    line = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    line = line.replace(/\*(.+?)\*/g, '<em>$1</em>');
    line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

    if (line.startsWith('### ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h3>${line.slice(4)}</h3>`);
    } else if (line.startsWith('## ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h2>${line.slice(3)}</h2>`);
    } else if (line.startsWith('# ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h1>${line.slice(2)}</h1>`);
    } else if (line.startsWith('- ')) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${line.slice(2)}</li>`);
    } else if (line.trim() === '') {
      if (inList) { out.push('</ul>'); inList = false; }
      // blank line = paragraph break (handled by next non-empty line)
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<p>${line}</p>`);
    }
  }
  if (inList) out.push('</ul>');
  return out.join('\n');
}

// articles is the array returned by GET /v1/blog/articles
function renderBlogIndex(articles) {
  const items = (articles || []).map(a => `
    <article style="border-bottom:1px solid #222;padding:1.5rem 0">
      <h2 style="margin:0 0 0.5rem"><a href="https://something-rare.com/blog/${escapeHtml(a.slug)}" style="color:#22d3ee;text-decoration:none">${escapeHtml(a.title)}</a></h2>
      <p style="color:#888;font-size:0.85em;margin:0 0 0.5rem">${escapeHtml(a.published_at || '')}</p>
      <p style="margin:0;color:#bbb">${escapeHtml(a.description)}</p>
    </article>`).join('');
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1 style="margin-bottom:0.5rem">Abyssal Claims Blog</h1>
      <p style="color:#888;margin-bottom:2rem">Deep-sea mining intelligence: data, policy, and science.</p>
      ${items}
      <p style="margin-top:2rem"><a href="https://something-rare.com/" style="color:#22d3ee">← Back to the interactive map</a></p>
    </main>`;
}

function renderBlogArticle(meta, markdown) {
  const body = mdToHtml(markdown);
  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif;line-height:1.7">
      <p style="margin:0 0 1.5rem"><a href="https://something-rare.com/blog" style="color:#22d3ee;font-size:0.9em">← Blog</a></p>
      <h1 style="margin:0 0 0.5rem;color:#fff">${escapeHtml(meta.title)}</h1>
      <p style="color:#888;font-size:0.85em;margin:0 0 2rem">${escapeHtml(meta.published_at || '')}</p>
      <div style="color:#ccc">${body}</div>
      <p style="margin-top:3rem;border-top:1px solid #222;padding-top:1.5rem">
        <a href="https://something-rare.com/" style="color:#22d3ee">Explore the interactive map →</a>
      </p>
    </main>`;
}

export async function renderSeoPage(type, id, opts) {
  // `opts.hydrate` is the caller's declared category, not a default we may guess:
  // this one function serves both React-routed types (concession, vent, seamount)
  // and server-only ones (oceansites, onc). Guessing here is how the two ended up
  // sharing a broken script tag in the first place.

  // ⛔ There is deliberately NO try/catch around this body any more.
  //
  // It used to wrap everything and `return null` on any throw, so a backend
  // 5xx, a timeout and a genuinely missing id were indistinguishable to the
  // caller — and the caller answered 200 + SPA shell to all three. Letting a
  // throw escape is what lets the handler answer 503 instead of pretending the
  // page exists and is empty. A rendering bug (malformed payload) also lands
  // here and is likewise a 503: it is our failure, not a statement about the id.
  {
    let data, head, body;
    switch (type) {
      case 'claim-report':
        data = await fetchClaimReportSeoData(id);
        if (!data) return null;
        head = renderHead(data.meta);
        body = renderClaimReport(data);
        break;
      case 'report':
        data = await fetchReportSeoData(id);
        if (!data) return null;
        if (!reportHasContent(data)) {
          throw new EntityGone(`report ${id} has no headline and no nonzero counts`);
        }
        head = renderHead(data.meta);
        body = renderReport(data);
        break;
      default:
        data = await fetchSeoData(`/${type}/${id}`);
        if (!data) return null;
        head = renderHead(data.meta);
        switch (type) {
          case 'concession':  body = renderConcession(data);  break;
          case 'vent':        body = renderVent(data);        break;
          case 'seamount':    body = renderSeamount(data);    break;
          case 'oceansites':  body = renderOceansites(data);  break;
          case 'onc':         body = renderOnc(data);         break;
          default: return null;
        }
    }
    return wrapHtml(head, body, opts);
  }
}

function renderResource(d) {
  const claimsHtml = (d.claims || []).map(c => `
    <tr>
      <td style="padding:4px 8px;border-bottom:1px solid #222">
        <a href="https://something-rare.com/concession/${escapeHtml(c.isa_id)}" style="color:#22d3ee">${escapeHtml(c.isa_id)}</a>
      </td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.contractor_name || '—')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.area_km2 ? c.area_km2.toLocaleString() + ' km²' : '—'}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.act_date || '—')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.is_high_risk ? '<span style="color:#f59e0b">Overlaps hotspot</span>' : '—'}</td>
    </tr>`).join('');

  const contractorsHtml = (d.contractors || []).map(name => {
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);
    return `<li><a href="https://something-rare.com/contractor/${escapeHtml(slug)}" style="color:#22d3ee">${escapeHtml(name)}</a></li>`;
  }).join('');

  return `
    <main style="max-width:900px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <p style="margin:0 0 1rem"><a href="https://something-rare.com/" style="color:#22d3ee;font-size:0.9em">← Interactive map</a></p>
      <h1 style="margin:0 0 0.5rem;color:#fff">${escapeHtml(d.resource_type)}</h1>
      <p style="color:#888;margin:0 0 2rem">${escapeHtml(d.meta.description)}</p>

      <h2>Overview</h2>
      <table style="margin-bottom:2rem">
        <tr><td style="padding:4px 12px 4px 0;color:#888">Total Concessions</td><td>${d.claim_count}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Total Licensed Area</td><td>${d.total_area_km2 ? d.total_area_km2.toLocaleString() + ' km²' : '—'}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Contractors</td><td>${d.contractor_count}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Concessions overlapping a biodiversity hotspot</td><td>${d.high_risk_count}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Earliest Contract</td><td>${escapeHtml(d.earliest_contract || '—')}</td></tr>
      </table>

      <h2>Environmental Impact</h2>
      <table style="margin-bottom:2rem">
        <tr><td style="padding:4px 12px 4px 0;color:#888">Deep-Sea Species Within 10 km</td><td>${d.species_count.toLocaleString()}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Threatened Species (CR/EN/VU)</td><td>${d.threatened_count.toLocaleString()}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Hydrothermal Vents Within 50 km</td><td>${d.vent_count.toLocaleString()}</td></tr>
      </table>

      <h2>Contractors (${d.contractor_count})</h2>
      <ul style="margin-bottom:2rem;padding-left:1.5rem;line-height:2">${contractorsHtml}</ul>

      <h2>Concessions${d.claims.length < d.claim_count ? ` (top ${d.claims.length} of ${d.claim_count})` : ` (${d.claim_count})`}</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:2rem">
        <tr style="color:#888;font-size:0.85em">
          <th style="text-align:left;padding:4px 8px">ISA ID</th>
          <th style="text-align:left;padding:4px 8px">Contractor</th>
          <th style="text-align:left;padding:4px 8px">Area</th>
          <th style="text-align:left;padding:4px 8px">Issued</th>
          <th style="text-align:left;padding:4px 8px">Status</th>
        </tr>
        ${claimsHtml}
      </table>

      <p><a href="https://something-rare.com/" style="color:#22d3ee">Explore on the interactive map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: International Seabed Authority, InterRidge v3.4, OBIS</p>
    </main>`;
}

function renderContractor(d) {
  const riskBadge = d.high_risk_count > 0
    ? `<span style="background:#78350f;color:#fcd34d;padding:2px 8px;border-radius:4px;font-size:0.8em;margin-left:8px">${d.high_risk_count} overlapping a hotspot</span>`
    : '';
  const claimsHtml = (d.claims || []).map(c => `
    <tr>
      <td style="padding:4px 8px;border-bottom:1px solid #222">
        <a href="https://something-rare.com/concession/${escapeHtml(c.isa_id)}" style="color:#22d3ee">${escapeHtml(c.isa_id)}</a>
      </td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.resource_type || '—')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.area_km2 ? c.area_km2.toLocaleString() + ' km²' : '—'}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.region || '—')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${escapeHtml(c.act_date || '—')}</td>
      <td style="padding:4px 8px;border-bottom:1px solid #222">${c.is_high_risk ? '<span style="color:#f59e0b">Overlaps hotspot</span>' : '—'}</td>
    </tr>`).join('');

  return `
    <main style="max-width:900px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <p style="margin:0 0 1rem"><a href="https://something-rare.com/contractors" style="color:#22d3ee;font-size:0.9em">← All Contractors</a></p>
      <h1 style="margin:0 0 0.5rem;color:#fff">${escapeHtml(d.contractor_name)}${riskBadge}</h1>
      <p style="color:#888;margin:0 0 2rem">${escapeHtml(d.meta.description)}</p>

      <h2>Portfolio Overview</h2>
      <table style="margin-bottom:2rem">
        <tr><td style="padding:4px 12px 4px 0;color:#888">Total Concessions</td><td>${d.claim_count}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Total Area</td><td>${d.total_area_km2 ? d.total_area_km2.toLocaleString() + ' km²' : '—'}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Resource Types</td><td>${escapeHtml((d.resource_types || []).join(', ') || '—')}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Ocean Regions</td><td>${escapeHtml((d.regions || []).join(', ') || '—')}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Earliest Contract</td><td>${escapeHtml(d.earliest_contract || '—')}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Latest Expiry</td><td>${escapeHtml(d.latest_expiry || '—')}</td></tr>
      </table>

      <h2>Environmental Footprint</h2>
      <table style="margin-bottom:2rem">
        <tr><td style="padding:4px 12px 4px 0;color:#888">Deep-Sea Species Within 10 km</td><td>${d.species_count.toLocaleString()}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Threatened Species (CR/EN/VU)</td><td>${d.threatened_count.toLocaleString()}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Hydrothermal Vents Within 50 km</td><td>${d.vent_count.toLocaleString()}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;color:#888">Concessions overlapping a biodiversity hotspot</td><td>${d.high_risk_count}</td></tr>
      </table>

      <h2>All Concessions (${d.claim_count})</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:2rem">
        <tr style="color:#888;font-size:0.85em">
          <th style="text-align:left;padding:4px 8px">ISA ID</th>
          <th style="text-align:left;padding:4px 8px">Resource</th>
          <th style="text-align:left;padding:4px 8px">Area</th>
          <th style="text-align:left;padding:4px 8px">Region</th>
          <th style="text-align:left;padding:4px 8px">Issued</th>
          <th style="text-align:left;padding:4px 8px">Status</th>
        </tr>
        ${claimsHtml}
      </table>

      <p><a href="https://something-rare.com/" style="color:#22d3ee">Explore all concessions on the interactive map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: International Seabed Authority, InterRidge v3.4, OBIS</p>
    </main>`;
}

function renderVentReport(vent) {
  const speciesRows = (vent.chess_species || [])
    .map(s => `<tr><td>${s.species || '—'}</td><td>${s.phylum || '—'}</td><td>${s.depth_m != null ? s.depth_m + ' m' : '—'}</td><td>${s.institution || '—'}</td></tr>`)
    .join('');

  const claimRows = (vent.nearby_claims || [])
    .map(c => `<tr><td>${c.contractor_name}</td><td>${c.resource_type}</td><td>${c.distance_km} km</td></tr>`)
    .join('');

  return `
    <h1>${vent.name}</h1>
    <p>${escapeHtml(vent.status || 'activity not stated')} Hydrothermal Vent</p>
    ${vent.name_aliases ? `<p>Also known as: ${escapeHtml(vent.name_aliases)}</p>` : ''}
    ${vent.vent_sites ? `<p>Named sites: ${escapeHtml(vent.vent_sites)}</p>` : ''}
    <h2>Physical</h2>
    <p>Depth: ${vent.depth_m != null ? vent.depth_m.toFixed(0) + ' m' : '—'} · Lat: ${vent.latitude.toFixed(5)}° · Lon: ${vent.longitude.toFixed(5)}°${vent.full_spreading_rate_mm_a != null ? ` · Full spreading rate: ${vent.full_spreading_rate_mm_a} mm/a` : ''}</p>
    ${vent.description_notes ? `<h2>Field description (source notes)</h2><p>${escapeHtml(vent.description_notes)}</p>` : ''}
    ${vent.biology_notes ? `<h2>Biology notes (source)</h2><p>${escapeHtml(vent.biology_notes)}</p>` : ''}
    ${vent.discovery_references || vent.other_references ? `<h2>References</h2>${
        vent.discovery_references ? `<p>Discovery: ${escapeHtml(vent.discovery_references)}</p>` : ''
      }${
        vent.other_references ? `<p>Other: ${escapeHtml(vent.other_references)}</p>` : ''
      }` : ''}
    <h2>ChEssBase Species (${vent.chess_count})</h2>
    ${speciesRows ? `<table><tr><th>Species</th><th>Phylum</th><th>Depth</th><th>Institution</th></tr>${speciesRows}</table>` : '<p>No ChEssBase species within 5 km.</p>'}
    <h2>Nearby Mining Claims</h2>
    ${claimRows ? `<table><tr><th>Contractor</th><th>Resource</th><th>Distance</th></tr>${claimRows}</table>` : '<p>No active mining claims within 100 km.</p>'}
    ${vent.source_url ? `<p><a href="${vent.source_url}">InterRidge Database</a></p>` : ''}
  `;
}

function renderRiverPage(data) {
  const d = data;
  const fluxRows = d.annual_fluxes && Object.keys(d.annual_fluxes).length > 0
    ? Object.entries(d.annual_fluxes)
        .map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`)
        .join('')
    : '';

  return `
    <main style="max-width:800px;margin:0 auto;padding:2rem;color:#ccc;font-family:system-ui,sans-serif">
      <h1>${escapeHtml(d.river_name)} River at ${escapeHtml(d.site_label)} — Arctic River Inputs</h1>
      <p>Land-to-ocean freshwater, carbon, and nutrient fluxes at the mouth of the ${escapeHtml(d.river_name)} River. Data source: ArcticGRO / PANGAEA.</p>

      <h2>Station Details</h2>
      <table>
        <tr><td>Site</td><td>${escapeHtml(d.site_label)}</td></tr>
        <tr><td>River</td><td>${escapeHtml(d.river_name)}</td></tr>
        <tr><td>Latitude</td><td>${Number(d.lat).toFixed(4)}°</td></tr>
        <tr><td>Longitude</td><td>${Number(d.lon).toFixed(4)}°</td></tr>
        ${d.record_start ? `<tr><td>Record start</td><td>${escapeHtml(String(d.record_start))}</td></tr>` : ''}
        ${d.record_end ? `<tr><td>Record end</td><td>${escapeHtml(String(d.record_end))}</td></tr>` : ''}
        ${d.mean_annual_discharge_km3 != null ? `<tr><td>Mean annual discharge</td><td>${Number(d.mean_annual_discharge_km3).toLocaleString('en-US', {maximumFractionDigits: 1})} km³/yr</td></tr>` : ''}
      </table>

      ${fluxRows ? `
        <h2>Annual Land-to-Ocean Fluxes</h2>
        <p>Approximate flux estimates (mean concentration × annual discharge).</p>
        <table>
          <tr><th>Constituent</th><th>Flux</th></tr>
          ${fluxRows}
        </table>
      ` : ''}

      ${d.citation ? `
        <h2>Citation</h2>
        <p>${escapeHtml(d.citation)}</p>
      ` : ''}

      <p><a href="https://something-rare.com/">View on the interactive 3D map →</a></p>
      <p style="color:#666;font-size:0.8em">Data: ArcticGRO (arcticgreatrivers.org/data) and PANGAEA — open access, CC-BY-4.0 where applicable</p>
    </main>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hub (index) pages — /seamount, /concession, /vent, /layer, …
//
// These are the crawl path. Before them (measured 2026-08-17, Googlebot UA) the
// home page served ZERO anchors and each entity page exactly one, back to "/":
// 40,300 URLs asserted by sitemap, none corroborated by a link, and 29,241 of
// them parked in "Discovered – currently not indexed".
//
// They render for HUMANS TOO, unlike the older bot-gated SSR routes. That is
// deliberate: /contractors and six siblings are already documented in server.js
// as rendering nothing for humans, and adding nine more to that pile to save a
// React route would be shipping a known defect on purpose. A directory page is
// also the one thing on this site that genuinely does not need the map.
//
// Hence its own shell rather than `wrapHtml`, whose `<script src="/src/main.tsx">`
// is a dev-server path that 404s in production — invisible while only bots saw
// it, a real broken request the moment a person does.
// ─────────────────────────────────────────────────────────────────────────────

const HUB_CSS = `
  :root{color-scheme:dark}
  body{background:#0a0e14;color:#cbd5e1;margin:0;
       font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
  main{max-width:1100px;margin:0 auto;padding:2rem 1.25rem 4rem}
  a{color:#22d3ee}
  h1{color:#fff;margin:0 0 .25rem;font-size:1.9rem}
  .intro{color:#94a3b8;margin:0 0 .25rem;max-width:60ch}
  .count{color:#64748b;font-size:.9rem;margin:0 0 2rem}
  ul.items{list-style:none;padding:0;margin:0;display:grid;gap:.15rem;
           grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
  ul.items li{padding:.35rem .5rem;border-bottom:1px solid #16202e}
  ul.items .meta{color:#64748b;font-size:.85rem;display:block}
  nav.pages{margin:2rem 0;display:flex;flex-wrap:wrap;gap:.4rem;align-items:baseline}
  nav.pages a,nav.pages strong{padding:.15rem .5rem;border:1px solid #1e293b;border-radius:4px}
  nav.pages strong{color:#fff;background:#132030}
  nav.hubs{margin-top:3rem;border-top:1px solid #16202e;padding-top:1.25rem;
           display:flex;flex-wrap:wrap;gap:.9rem;font-size:.9rem}
`;

/** Numbered pagination. Every page links to every other when the run is short
 *  enough, so any page is two clicks from any other — the point of the exercise
 *  is link reachability, not aesthetics. Long runs get a window plus the ends,
 *  so page 76 never becomes unreachable from page 1. */
function hubPagination(kind, page, pages) {
  if (pages <= 1) return '';
  const href = p => `https://something-rare.com/${kind}${p > 1 ? `?page=${p}` : ''}`;
  const cell = p => (p === page
    ? `<strong>${p}</strong>`
    : `<a href="${href(p)}">${p}</a>`);

  let nums;
  if (pages <= 40) {
    nums = Array.from({ length: pages }, (_, i) => cell(i + 1));
  } else {
    const around = new Set([1, pages, page]);
    for (let d = 1; d <= 4; d++) { around.add(page - d); around.add(page + d); }
    for (const step of [10, 25, 50]) {
      for (let p = step; p <= pages; p += step) around.add(p);
    }
    const sorted = [...around].filter(p => p >= 1 && p <= pages).sort((a, b) => a - b);
    nums = [];
    let last = 0;
    for (const p of sorted) {
      if (p - last > 1) nums.push('<span style="color:#475569">…</span>');
      nums.push(cell(p));
      last = p;
    }
  }
  const prev = page > 1 ? `<a href="${href(page - 1)}" rel="prev">← Previous</a>` : '';
  const next = page < pages ? `<a href="${href(page + 1)}" rel="next">Next →</a>` : '';
  return `<nav class="pages">${prev}${nums.join('')}${next}</nav>`;
}

/** The cross-hub footer. Present on every hub AND on the bot copy of the home
 *  page, so the whole corpus is reachable from anywhere in it. */
export function hubNavHtml(hubs, currentKind) {
  const links = (hubs || [])
    .filter(h => h.kind !== currentKind)
    .map(h => `<a href="${escapeHtml(h.url)}">${escapeHtml(h.heading)}`
      + (h.total ? ` <span style="color:#475569">(${h.total.toLocaleString()})</span>` : '')
      + '</a>')
    .join('');
  // Inline styles as well as the class: this nav is also injected into the home
  // page's pre-render, which carries none of the hub stylesheet.
  return `<nav class="hubs" style="display:flex;flex-wrap:wrap;gap:.9rem;margin-top:2rem">`
    + `<a href="https://something-rare.com/">Interactive map</a>`
    + `${links}<a href="https://something-rare.com/contractors">Contractors</a>`
    + `<a href="https://something-rare.com/blog">Blog</a>`
    + `<a href="https://something-rare.com/about">About</a>`
    + `<a href="https://something-rare.com/api-docs">API</a></nav>`;
}

export function renderHubPage(hub, hubs) {
  const { kind, page, pages, total, items } = hub;
  const base = `https://something-rare.com/${kind}`;
  // Page N is SELF-canonical. Pointing 2..N at page 1 would hide exactly the
  // links this page exists to expose — see the DoD in
  // docs/seo-discovered-not-indexed-2026-08-17.md.
  const canonical = page > 1 ? `${base}?page=${page}` : base;
  const pageSuffix = pages > 1 ? ` — page ${page} of ${pages}` : '';
  const description = `${hub.intro} ${total.toLocaleString()} entries.`.slice(0, 300);

  const list = items.map(i => `<li><a href="${escapeHtml(i.url)}">${escapeHtml(i.label)}</a>`
    + (i.meta ? `<span class="meta">${escapeHtml(i.meta)}</span>` : '')
    + '</li>').join('');

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: hub.heading,
    description: hub.intro,
    url: canonical,
    isPartOf: { '@type': 'WebSite', name: 'Abyssal Claims', url: 'https://something-rare.com' },
    mainEntity: {
      '@type': 'ItemList',
      numberOfItems: total,
      itemListElement: items.slice(0, 100).map((i, n) => ({
        '@type': 'ListItem',
        position: (page - 1) * (hub.per_page || items.length) + n + 1,
        url: i.url,
        name: i.label,
      })),
    },
  };

  // One shell for every server-rendered page. The hub used to carry its own —
  // the third of four — which is how three of them drifted apart on the script
  // tag alone. `hydrate: false` is the hub's declared category: App.tsx has no
  // route for /seamount, /concession, … so booting React here would replace a
  // working index with a blank page.
  const head = `
  <title>${escapeHtml(hub.title.replace(' | Abyssal Claims', pageSuffix + ' | Abyssal Claims'))}</title>
  <meta name="description" content="${escapeHtml(description)}" />
  <link rel="canonical" href="${canonical}" />
  ${page > 1 ? `<link rel="prev" href="${page - 1 > 1 ? `${base}?page=${page - 1}` : base}" />` : ''}
  ${page < pages ? `<link rel="next" href="${base}?page=${page + 1}" />` : ''}
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${canonical}" />
  <meta property="og:title" content="${escapeHtml(hub.heading)}" />
  <meta property="og:description" content="${escapeHtml(description)}" />
  <meta property="og:image" content="https://something-rare.com/og.jpg" />
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <style>${HUB_CSS}</style>
  <script type="application/ld+json">${JSON.stringify(jsonLd).replace(/<\//g, '<\\/')}</script>`;

  const body = `
  <main>
    <h1>${escapeHtml(hub.heading)}</h1>
    <p class="intro">${escapeHtml(hub.intro)}</p>
    <p class="count">${total.toLocaleString()} entries${pages > 1 ? ` · page ${page} of ${pages}` : ''}</p>
    <ul class="items">${list}</ul>
    ${hubPagination(kind, page, pages)}
    ${hubNavHtml(hubs, kind)}
  </main>`;

  return wrapHtml(head, body, { hydrate: false });
}

export { fetchSeoData, renderBlogIndex, renderBlogArticle, renderContractor, renderResource, renderVentReport, renderRiverPage, mdToHtml, wrapHtml };
