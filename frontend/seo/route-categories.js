/**
 * Which renderer owns a path — the declaration that did not exist before.
 *
 * Every server-rendered page belongs to exactly one of two categories, and the
 * category decides whether its HTML may carry the client bundle. Getting it
 * wrong breaks the page in opposite directions:
 *
 *   REACT_ROUTES        App.tsx has a <Route path=…>. React boots and REPLACES
 *                       the server DOM with the real application, so the bundle
 *                       must be emitted or the page can never become the app.
 *
 *   SERVER_ONLY_ROUTES  App.tsx has no route, and there is no `path="*"`
 *                       catch-all. `main.tsx` calls createRoot().render(), which
 *                       replaces #root rather than hydrating it — so emitting the
 *                       bundle here boots React, matches nothing, and BLANKS a
 *                       page that renders perfectly well without it.
 *
 * ⚠️ This file exists because the absence of that declaration is what produced
 * two defects in one week. On 18.08 six server-only routes were un-gated so
 * humans could read them (correct) — and thereby handed humans the crawler's
 * HTML, whose script tag had pointed at Vite's dev path `/src/main.tsx` since
 * the SSR layer was written. It 404'd on every page, and nobody noticed while
 * only crawlers saw it. Nobody could say from memory which routes React could
 * render, because it was written down nowhere.
 *
 * ⛔ Do not add a path here without checking `src/App.tsx`. Do not guess.
 * `scripts/check-render-contract.mjs` parses App.tsx and fails on any drift —
 * the runtime image ships no `src/`, so the check cannot live in the server.
 */

export const REACT_ROUTES = [
  /^\/$/,
  /^\/(about|privacy|terms|blog|api-docs)$/,
  /^\/blog\/[^/]+$/,
  /^\/(concession|vent|seamount)\/[^/]+$/,
  /^\/report\/[^/]+$/,
  /^\/report\/v1\/[^/]+$/,
  /^\/report\/v2\/(argo|concession)\/[^/]+$/,
  /^\/claim-report\/[^/]+$/,
  /^\/claim-report\/v1\/[^/]+$/,
  /^\/vent-report\/[^/]+$/,
  /^\/chess-report\/[^/]+$/,
];

/**
 * The nine hub indexes. Server-only like the rest, but kept separate for a
 * second reason: they ALWAYS answer for themselves — 200, a real 404 for a page
 * number past the end, or 503 if the backend is down. They must therefore never
 * reach the SPA catch-all, or `/seamount?page=99999` becomes a 200 soft-404,
 * which is the exact defect fixed 2026-08-09. (It briefly came back on
 * 2026-08-18 when this file was first written with the hubs folded into
 * SPA_PATHS; `npm run check:seo` caught it.)
 */
export const HUB_PATHS = [
  /^\/(seamount|concession|vent|onc|oceansites|river|report|layer|resource)$/,
];

/**
 * Server-only routes. Their handlers ALWAYS answer for themselves — 200, 404
 * for an id the backend does not know, or 503 when it could not be asked.
 *
 * ⚠️ They used to call `next()` on anything that was not a clean 200, which
 * reached the SPA catch-all below and answered **200 with the empty shell**.
 * On these paths that is a literally blank page (App.tsx cannot route them and
 * has no `path="*"`), and on a backend outage it was ~40,300 blank 200s at
 * once. See `entityRoute` / `sendNotFound` / `sendUnavailable` in server.js.
 */
const SERVER_ONLY_FALLTHROUGH = [
  /^\/contractors$/,
  /^\/(oceansites|onc|river|resource|contractor|layer)\/[^/]+$/,
  // The iframe widget is a standalone document on purpose: no site chrome, no
  // bundle, embedded on third-party pages. It is not a content page.
  /^\/embed\/concession\/[^/]+$/,
];

export const SERVER_ONLY_ROUTES = [...SERVER_ONLY_FALLTHROUGH, ...HUB_PATHS];

/**
 * The single decision point. Never decide this at a call site — nine call sites
 * each making the judgement is how they drift apart.
 */
export function hydrates(path) {
  const p = path.replace(/\/index\.html$/, '').replace(/\/+$/, '') || '/';
  return REACT_ROUTES.some(re => re.test(p));
}

/**
 * Paths that legitimately reach the SPA catch-all; everything else is a 404.
 *
 * **This is REACT_ROUTES and nothing else, and the identity is the point:**
 * the shell may answer only where React can route. Anywhere else it renders an
 * empty `#root` — a 200 that says "this page exists and is blank", which is the
 * single worst answer available.
 *
 * ⚠️ It was `REACT_ROUTES + SERVER_ONLY_FALLTHROUGH` until 2026-08-18. The
 * union read as "all the real pages" rather than as "and these may answer 200
 * with no content", which is why the soft-404 survived being written down: the
 * hubs were excluded for exactly this reason and the entity routes were not, so
 * `/seamount?page=99999` correctly 404'd while `/river/nie-ma` returned 200.
 * "Who renders this page" and "may the shell answer here" are still two
 * different questions — the answer to the second is now just narrower.
 *
 * ⛔ Do not add a server-only path here to "make it work". If a server-only
 * route needs the shell, its handler is missing or broken; fix that instead.
 */
export const SPA_PATHS = [...REACT_ROUTES];
