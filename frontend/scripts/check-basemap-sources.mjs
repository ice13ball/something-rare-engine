#!/usr/bin/env node
// Manual sync check (NOT a test, not run in CI): does the CURRENT release in
// src/content/basemapSources.json agree with the machine-readable list the
// basemap itself publishes?
//
//   cd frontend && node scripts/check-basemap-sources.mjs [path-or-url]
//
// For every source of releases[0] it requires that the exact credit sentence
// and the year/version string appear in ATTRIBUTION.txt (whitespace
// normalised; a trailing full stop is optional). Exit 0 = in sync,
// exit 1 = mismatch (each miss is printed), exit 2 = could not fetch.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(readFileSync(join(here, '../src/content/basemapSources.json'), 'utf8'));
const target = process.argv[2] || data.attributionUrl;

const norm = (s) => s.replace(/\s+/g, ' ').trim().toLowerCase();

let text;
try {
  if (/^https?:\/\//.test(target)) {
    const res = await fetch(target, { headers: { 'user-agent': 'abyssal-basemap-sources-check' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    text = await res.text();
  } else {
    text = readFileSync(target, 'utf8');
  }
} catch (e) {
  console.error(`Cannot read ${target}: ${e.message}`);
  process.exit(2);
}
const hay = norm(text);

const current = data.releases[0];
console.log(`Checking release ${current.ids.join(' / ')} against ${target}`);
let misses = 0;
const need = (label, needle) => {
  const n = norm(needle).replace(/\.$/, '');
  if (n && hay.includes(n)) {
    console.log(`  ok    ${label}`);
  } else {
    misses += 1;
    console.log(`  MISS  ${label}: "${needle}"`);
  }
};

for (const id of current.sources) {
  const s = data.sources[id];
  if (!s) {
    misses += 1;
    console.log(`  MISS  ${id}: not defined in "sources"`);
    continue;
  }
  need(`${id} credit`, s.credit);
  if (s.year) need(`${id} year`, s.year);
}

if (misses) {
  console.log(`\n${misses} mismatch(es): fix basemapSources.json or ATTRIBUTION.txt.`);
  process.exit(1);
}
console.log('\nIn sync.');
