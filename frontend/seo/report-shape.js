// Does a float report actually render statistics?
//
// ⛔ Deliberately its own module, importing nothing. `render-page.js` reads
// `dist/index.html` at module scope and throws when the client has not been
// built, so anything importing it needs a build to exist. A pure predicate must
// not need one — a test that passes only because the author happened to have a
// stale `dist/` lying around is a test that passes for the wrong reason. That is
// exactly what happened on 2026-08-23: green locally, red in CI.
//
// Measured on production 2026-08-23 across all 24 /report/ URLs in
// sitemap-core.xml: 17 populated, 7 empty — and all 7 empty ones are `chess:*`
// vent-site ids, while ZERO `chess:*` ids have float data. A vent site is not a
// float; the route was answering for an id family it can never serve.
//
// ⚠️ The predicate is what the PAGE RENDERS, not what the record contains.
// `chess:Snake Pit` carries claim_count = 16 while narrative and key_stats are
// both empty — so a `claim_count > 0` test would call it populated and ship the
// same wall of em dashes. Narrative or key_stats is the whole of the body.
//
// ⚠️ Partial data renders. One key_stat present is a page with something on it;
// only the total absence of both is a soft 404. That boundary is stated here so
// "partial" cannot silently fall back into the 200-with-dashes shape.
//
// 📌 The same rule exists in SQL as `REPORT_SITEMAP_SQL` in
// `backend/domains/seo.py`, which keeps these URLs out of the sitemap. The two
// must agree: a URL advertised in the sitemap that answers 410 is a new defect,
// not a fix.
export function reportHasStatistics(data) {
  if (!data) return false;
  const narrative = typeof data.narrative === 'string' ? data.narrative.trim() : '';
  const stats = data.key_stats && typeof data.key_stats === 'object' ? Object.keys(data.key_stats) : [];
  return narrative.length > 0 || stats.length > 0;
}
