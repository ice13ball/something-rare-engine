// Canonical URL construction — ONE encoder, shared by the sitemap and by every
// <link rel="canonical">.
//
// ⛔ Why this file exists: until 2026-08-23 the sitemap and the canonical tag
// were built by two separate code paths, and they disagreed on 11 live URLs —
// in BOTH directions. `/river/arcticgro:kolyma` was declared in the sitemap but
// the page named `/river/arcticgro%3Akolyma` (over-encoded), while
// `/report/chess:Snake Pit` shipped a canonical with a RAW SPACE in the href
// (under-encoded — not a legal URL at all). Google's answer to "the sitemap and
// the page name different addresses" is "Duplicate, Google chose a different
// canonical than the user".
//
// The rule: build every public URL through `canonicalUrl()`, and normalise
// anything arriving pre-assembled through `normaliseUrl()`. Never hand-roll
// `encodeURIComponent` into a URL template again.

export const SITE = 'https://something-rare.com';

// Percent-encode ONE path segment.
//
// Deliberately NOT `new URL().href`, which is a whole-URL parser and therefore
// cannot be trusted with an id: given `a/b` it invents a path separator, given
// `a#b` it invents a fragment, and given `a?b` it invents a query — silently
// turning one id into a different address. encodeURIComponent escapes all three,
// keeping an id an id.
//
// The single exception is `:`. It is a legal path character (RFC 3986 `pchar`
// includes the `:` sub-delim), every id family we publish uses it as a namespace
// separator — `arcticgro:kolyma`, `chess:Snake Pit` — and `new URL()` leaves it
// alone, so the sitemap has always emitted it raw. Encoding it here would fix
// the mismatch by breaking every URL Google has already indexed.
//
// What the encoder does with the characters the brief asked about:
//   ':'  → kept raw          (legal in a segment; matches the live sitemap)
//   ' '  → '%20'
//   '/'  → '%2F'             (an id is one segment; it never splits the path)
//   '#'  → '%23'             (never a fragment)
//   '?'  → '%3F'             (never a query)
//   '%'  → '%25'             (a literal percent, encoded once, not doubled)
//   '°', non-Latin → UTF-8 percent-encoding ('°' → '%C2%B0')
export function encodeSegment(raw) {
  return encodeURIComponent(String(raw)).replace(/%3A/gi, ':');
}

// Reverse of encodeSegment for a segment of unknown provenance. A segment
// carrying a literal '%' that is not a valid escape makes decodeURIComponent
// throw; that is a segment which was never encoded, so use it as it stands.
function decodeSegment(seg) {
  try { return decodeURIComponent(seg); } catch { return seg; }
}

// Build a canonical URL from a path prefix and a RAW (decoded) id.
//   canonicalUrl('/river', 'arcticgro:kolyma')  → 'https://something-rare.com/river/arcticgro:kolyma'
//   canonicalUrl('/report', 'chess:Snake Pit')  → 'https://something-rare.com/report/chess:Snake%20Pit'
export function canonicalUrl(prefix, id) {
  const clean = `/${String(prefix).replace(/^\/+|\/+$/g, '')}`;
  return id === undefined || id === null || id === ''
    ? `${SITE}${clean}`
    : `${SITE}${clean}/${encodeSegment(id)}`;
}

// Normalise a URL that was assembled somewhere else — the backend's
// `canonical_url` fields, and every `<loc>` the sitemap receives.
//
// Decoding each segment before re-encoding is what makes this converge: an
// over-encoded '%3A' and a raw ':' both land on ':', so the two code paths that
// used to disagree now produce the same bytes. Applying it twice changes
// nothing.
//
// ⚠️ Limit worth knowing: a '/' inside an id is already lost by the time a
// pre-assembled URL reaches here — the backend's f-string put it in the path and
// nothing downstream can tell it from a separator. Build such URLs with
// canonicalUrl(), which never had the ambiguity.
export function normaliseUrl(rawUrl) {
  const str = String(rawUrl ?? '');
  const m = /^([a-z][a-z0-9+.-]*:\/\/[^/?#]+)([^?#]*)(.*)$/i.exec(str);
  if (!m) return str;
  const [, origin, path, tail] = m;
  const normalisedPath = path.split('/').map(seg => encodeSegment(decodeSegment(seg))).join('/');
  return `${origin}${normalisedPath}${tail}`;
}

// Normalise every URL inside a JSON-LD graph.
//
// ⚠️ The canonical tag is not the only surface that names the page. Structured
// data carries `url` and `@id`, built by the same raw f-strings on the backend
// and therefore carrying the same defect. On 2026-08-17 a description was fixed
// while the <h1> directly above it was missed across 37,889 pages; fixing the
// canonical while leaving JSON-LD pointing at a differently-encoded address is
// the identical mistake one surface over.
export function normaliseJsonLd(node) {
  if (Array.isArray(node)) return node.map(normaliseJsonLd);
  if (node && typeof node === 'object') {
    const out = {};
    for (const [key, value] of Object.entries(node)) {
      out[key] = (key === 'url' || key === '@id') && typeof value === 'string' && value.startsWith(SITE)
        ? normaliseUrl(value)
        : normaliseJsonLd(value);
    }
    return out;
  }
  return node;
}
