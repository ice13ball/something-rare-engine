/**
 * /map-sources — server-rendered body, built from the SAME JSON the React page
 * (src/components/MapSourcesPage.tsx) reads: src/content/basemapSources.json.
 * Crawlers and humans receive the same document; React replaces #root with the
 * same content, so there is nothing to diverge.
 *
 * Plain data in, strings out: no I/O except the one JSON read at import time.
 * The runtime image ships no `src/`, so the Dockerfile copies the JSON to the
 * same relative path (see frontend/Dockerfile).
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
export const BASEMAP_SOURCES = JSON.parse(
  readFileSync(join(here, '../src/content/basemapSources.json'), 'utf8'),
);

export const MAP_SOURCES_LANGS = ['en', 'pl', 'de', 'fr'];

const esc = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const a = (url, text) => `<a href="${esc(url)}" rel="noopener" style="color:#22d3ee">${esc(text)}</a>`;

export function pickMapSourcesLang(q) {
  return MAP_SOURCES_LANGS.includes(q) ? q : 'en';
}

export function mapSourcesMeta(lang) {
  const u = BASEMAP_SOURCES.ui[lang];
  return { title: u.title, description: u.description };
}

function creditHtml(src) {
  const link = src.creditLink;
  if (!link) return esc(src.credit);
  const i = src.credit.indexOf(link.text);
  if (i < 0) return esc(src.credit);
  return esc(src.credit.slice(0, i)) + a(link.url, link.text) + esc(src.credit.slice(i + link.text.length));
}

function sourceHtml(src, lang, u, methods) {
  const rows = [];
  const row = (k, v) => rows.push(`<dt style="color:#8b98a8">${esc(k)}</dt><dd style="margin:0 0 .5rem">${v}</dd>`);
  row(u.provider, a(src.providerUrl, src.providerUrl));
  row(u.role, esc(src.role[lang]));
  if (src.version) row(u.version, esc(src.version));
  row(u.licence, a(src.licence.url, src.licence.name));
  row(u.credit, `<q style="quotes:none">${creditHtml(src)}</q>`);
  if (methods) row('Land/sea mask', methods.map((m) => a(m.url, u.landMaskMethod + (methods.length > 1 ? ` — ${m.id}` : ''))).join('<br>'));
  if (src.modified) row(u.modified, `${esc(u.yes)} — ${esc(src.modified.how[lang])}`);
  const warn = src.warning
    ? `<p style="border:1px solid #f59e0b;color:#fbbf24;padding:.5rem .75rem;border-radius:6px"><strong>${esc(src.warning[lang])}</strong></p>`
    : '';
  const note = src.note ? `<p>${esc(src.note[lang])}</p>` : '';
  return `<section style="margin:1rem 0;padding:1rem;border:1px solid #1f2a37;border-radius:8px">
        <h3 style="margin:0 0 .5rem">${esc(src.name)}</h3>
        ${warn}<dl style="margin:0">${rows.join('')}</dl>${note}
      </section>`;
}

function releaseHtml(rel, lang, u) {
  const [first, ...rest] = rel.ids;
  const label = rel.ids.join(' / ') + (rel.includesNextRerender ? ` ${u.also}` : '');
  const cur = rel.current ? ` <small style="color:#22d3ee">(${esc(u.current)})</small>` : '';
  const anchors = rest.map((id) => `<a id="release-${esc(id)}"></a>`).join('');
  const notes = rel.notes ? `<p>${esc(rel.notes[lang])}</p>` : '';
  const srcs = rel.sources.map((id) => sourceHtml(BASEMAP_SOURCES.sources[id], lang, u, id.startsWith('osm-') ? rel.landMaskMethodUrls : undefined)).join('\n      ');
  return `<section>
      <h2 id="release-${esc(first)}">${anchors}${esc(u.release)} ${esc(label)}${cur}</h2>
      ${notes}
      ${srcs}
    </section>`;
}

function creatorHtml(lang) {
  const c = BASEMAP_SOURCES.creator;
  return esc(c.line[lang])
    .replace('{org}', a(c.orgUrl[lang], c.org))
    .replace('{name}', a(c.nameUrl, c.name[lang]));
}

/** Inline syntax of the land-mask text: [text](url), `code`, **bold**. */
function inlineHtml(text) {
  return text.split(/(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*)/).map((part) => {
    let m = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (m) return a(m[2], m[1]);
    m = /^`([^`]+)`$/.exec(part);
    if (m) return `<code>${esc(m[1])}</code>`;
    m = /^\*\*([^*]+)\*\*$/.exec(part);
    if (m) return `<strong>${esc(m[1])}</strong>`;
    return esc(part);
  }).join('');
}

function landMaskHtml(lang) {
  const m = BASEMAP_SOURCES.landMask;
  const blocks = m.method.map((b) => {
    if (b.type === 'p') return `<p>${inlineHtml(b.text)}</p>`;
    const tag = b.type === 'ol' ? 'ol' : 'ul';
    return `<${tag}>${b.items.map((i) => `<li>${inlineHtml(i)}</li>`).join('')}</${tag}>`;
  }).join('\n      ');
  const note = m.note[lang] ? `<p style="color:#8b98a8">${esc(m.note[lang])}</p>` : '';
  return `<section>
      <h2 id="land-mask-method">${esc(m.h[lang])}</h2>
      <p>${inlineHtml(m.intro[lang])}</p>
      ${note}
      ${blocks}
    </section>`;
}

/** Inner HTML of <main> for the given language (no wrapper). */
export function mapSourcesBody(lang) {
  const u = BASEMAP_SOURCES.ui[lang];
  const [cur, ...older] = BASEMAP_SOURCES.releases;
  return `<h1>${esc(u.h1)}</h1>
    <p>${creatorHtml(lang)}</p>
    ${landMaskHtml(lang)}
    <p>${esc(u.intro)}</p>
    <p>${esc(u.fullList)} ${a(BASEMAP_SOURCES.attributionUrl, BASEMAP_SOURCES.attributionUrl)}</p>
    <p style="color:#8b98a8">${esc(u.creditNote)}</p>
    ${releaseHtml(cur, lang, u)}
    <h2>${esc(u.earlier)}</h2>
    <p style="color:#8b98a8">${esc(u.archiveNote)}</p>
    ${older.map((r) => releaseHtml(r, lang, u)).join('\n    ')}
    <section>
      <h2>${esc(u.endorsementHeading)}</h2>
      <p>${esc(u.endorsement)}</p>
    </section>
    <p><a href="/" style="color:#22d3ee">← ${esc(u.back)}</a></p>`;
}
