// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Every HTML-producing path of frontend/server.js, one real URL each, with the
// kind of answer it must give. Enumerated 2026-09-23 from server.js and
// seo/render-page.js (24 code paths). Shared by the GA4 render guard and by
// scripts/record-ssr-upstream.mjs, so the fixture always covers the list.
//
// kind:
//   document — a full <html> page: carries the GA4 bootstrap exactly once
//   fragment — a short error body with no <head> (hub past its last page,
//              catch-all 404, backend outage 503): no page view to measure
//   embed    — /embed/*, rendered inside OTHER sites' iframes; deliberately
//              untagged (a consent decision for someone else's visitors)
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const FIXTURE_PATH = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'ssr-upstream', 'upstream.json');

// A path containing this makes the replay stub answer 500 → the 503 branch.
export const FORCE_OUTAGE = 'force-outage';

export const SSR_ROUTES = [
  // Built shell (dist/index.html) — `/` for humans and for bots, SPA fallback
  { path: '/', kind: 'document' },
  { path: '/report/6904187', kind: 'document' },             // bot: SSR; human: SPA shell
  // wrapHtml — entity pages
  { path: '/seamount/4873694', kind: 'document' },
  { path: '/seamount/28715', kind: 'document' },
  { path: '/concession/BGRPMN1X_East_a', kind: 'document' },
  { path: '/vent/6', kind: 'document' },
  { path: '/oceansites/1400049', kind: 'document' },
  { path: '/onc/AS04', kind: 'document' },
  { path: '/river/arcticgro:kolyma', kind: 'document' },
  { path: '/claim-report/UKSRLPMN2X', kind: 'document' },
  { path: '/vent-report/6', kind: 'document' },
  { path: '/contractor/beijing-minmetals-joint-venture-china', kind: 'document' },
  { path: '/resource/polymetallic-nodules', kind: 'document' },
  { path: '/layer/contracts', kind: 'document' },
  { path: '/contractors', kind: 'document' },
  { path: '/blog', kind: 'document' },
  { path: '/blog/mining-hydrothermal-vents-sulphide-deposits', kind: 'document' },
  { path: '/about', kind: 'document' },
  { path: '/privacy', kind: 'document' },
  { path: '/terms', kind: 'document' },
  { path: '/api-docs', kind: 'document' },
  // wrapHtml — hubs
  ...['seamount', 'concession', 'vent', 'onc', 'oceansites', 'river', 'report', 'layer', 'resource']
    .map((h) => ({ path: `/${h}`, kind: 'document' })),
  // wrapHtml — 404 pages (sendNotFound, company slug)
  { path: '/seamount/999999999999', kind: 'document' },
  { path: '/blog/no-such-article', kind: 'document' },
  { path: '/claim-report/company/no-such-company', kind: 'document' },
  // inline fragments
  { path: '/seamount?page=99999', kind: 'fragment' },
  { path: '/no-such-page-at-all', kind: 'fragment' },
  { path: `/concession/${FORCE_OUTAGE}`, kind: 'fragment' },
  // third-party iframe widget
  { path: '/embed/concession/BGRPMN1X_East_a', kind: 'embed' },
];

export const USER_AGENTS = {
  human: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36',
  bot: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
};
