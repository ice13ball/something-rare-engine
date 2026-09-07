// Allowlist of canonical hosts for the two Host-header redirects in server.js —
// force-HTTPS and www→non-www.
//
// ⛔ Why this file exists: both redirects used to build their target straight
// from the incoming `Host` header with no validation. Behind a proxy that does
// not itself validate Host (nginx `default_server`, plain Docker — exactly what
// the README tells a self-hoster to run), `Host: evil.com` bought a 301 to
// `https://evil.com/...`. Production is not exposed today — Cloud Run rejects
// an unmapped Host with its own 404 before Express ever sees it — but the
// engine ships to people who do not run behind Cloud Run.
//
// The fix is an allowlist, not a blanket reject: an unknown Host must fall
// through to `next()` and be served normally, never 400. A 400 on a host we
// forgot to list takes the site down; skipping the redirect only loses a
// canonicalisation, which is harmless.

// The hosts THIS deployment answers on. Kept here (not invented at the call
// site) so a self-hoster can see exactly what ships and override the whole
// list with one env var instead of patching source.
//   - something-rare.com / www.something-rare.com — production, see SITE in server.js
//   - the dev Cloud Run URL — also hardcoded in backend/main.py and
//     backend/routers/feedback.py's CORS allowlists; keep the three in step
//   - localhost / 127.0.0.1 — `npm start` (server.js's own PORT default, 3000)
//     and a local Docker run publishing that port, so both keep working
//     un-configured
const DEFAULT_CANONICAL_HOSTS = [
  'something-rare.com',
  'www.something-rare.com',
  'something-rare-frontend-dev-3w2whlwtbq-ew.a.run.app',
  'localhost:3000',
  '127.0.0.1:3000',
];

// Comma-separated `CANONICAL_HOSTS` env var replaces the defaults wholesale —
// a self-hoster's own domain never has to coexist with ours in the same list.
export function getCanonicalHosts(env = process.env) {
  const raw = env.CANONICAL_HOSTS;
  if (!raw) return DEFAULT_CANONICAL_HOSTS;
  return raw.split(',').map((h) => h.trim()).filter(Boolean);
}

// Case-insensitive; a `Host` header may legitimately carry a port, so nothing
// beyond casing is normalised — a caller that wants "www." stripped does that
// itself before calling.
export function isAllowedHost(host, hosts = getCanonicalHosts()) {
  if (!host) return false;
  const lower = host.toLowerCase();
  return hosts.some((h) => h.toLowerCase() === lower);
}

// ── Force HTTPS — 301 permanent redirect for any plain-HTTP request ───────
//
// Skips (never redirects, never 400) when `Host` is not one of ours: the
// alternative — redirecting to `https://<attacker Host>/...` — is the open
// redirect this file exists to close.
export function forceHttpsMiddleware(req, res, next) {
  if (req.headers['x-forwarded-proto'] === 'http' && isAllowedHost(req.headers.host)) {
    return res.redirect(301, `https://${req.headers.host}${req.url}`);
  }
  next();
}

// ── www → non-www canonical redirect (301) ────────────────────────────────
//
// Fires only when BOTH the `www.` host and the host it strips to are in the
// allowlist — an attacker-chosen `www.` host must not redirect to whatever
// they put after the prefix, even if that stripped value happens to look
// like a real domain.
export function wwwRedirectMiddleware(req, res, next) {
  const host = req.headers.host || '';
  if (host.toLowerCase().startsWith('www.')) {
    const stripped = host.slice(4);
    const hosts = getCanonicalHosts();
    if (isAllowedHost(host, hosts) && isAllowedHost(stripped, hosts)) {
      return res.redirect(301, `${req.protocol}://${stripped}${req.url}`);
    }
  }
  next();
}
