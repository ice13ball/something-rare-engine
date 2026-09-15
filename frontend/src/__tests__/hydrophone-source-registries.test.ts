// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// hydrophone-stations' `source` column feeds THREE independent frontend
// registries: a filter chip list (SensorsSection, now HYDROPHONE_SOURCE_DEFS
// in controls/filterDefs.ts), a map colour lookup (HYDROPHONE_SOURCE_COLOR in
// components/map3d/colors.ts) and a panel label map (HYDROPHONE_SOURCE_LABEL
// in panels/ocean/HydrophoneStationPanel.tsx). Nothing enforced they agree —
// a source could have a chip but no colour, a colour but no label, or a
// label keyed under the wrong case. This test imports and executes the real
// registries (not a text scrape) and fails on any three-way disagreement.
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect } from "vitest";

import { HYDROPHONE_SOURCE_DEFS } from "../components/controls/filterDefs";
import { HYDROPHONE_SOURCE_COLOR, hydrophoneSourceColor } from "../components/map3d/colors";
import { HYDROPHONE_SOURCE_LABEL } from "../components/panels/ocean/HydrophoneStationPanel";

// ⛔ The backend list is READ, not transcribed.
//
// A hand-copied fixture here would be the same defect this file exists to
// catch, moved one level up: the backend could add a source and every
// assertion below would keep passing against a stale copy. Vitest runs in
// Node, so the two files that define the real source names are simply read
// off disk. They are Python, so this is a regex — which is why
// `_mustFind` refuses to return an implausibly small set. ⛔ An extractor
// that silently matches nothing turns every check below into "the empty set
// is covered", which passes forever.
function _repoFile(rel: string): string {
  for (const base of [process.cwd(), path.resolve(process.cwd(), "..")]) {
    const p = path.resolve(base, rel);
    if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
  }
  throw new Error(
    `cannot find ${rel} from ${process.cwd()} — this test reads the backend's ` +
    `own source lists, and silently skipping that would make it decorative`,
  );
}

function _mustFind(src: string, re: RegExp, atLeast: number, what: string): string[] {
  const found = [...src.matchAll(re)].map((m) => m[1]);
  if (found.length < atLeast) {
    throw new Error(
      `extracted only ${found.length} ${what} (expected at least ${atLeast}): ` +
      `${JSON.stringify(found)}. The backend file's shape changed and this ` +
      `regex no longer matches — every check below would pass vacuously.`,
    );
  }
  return found;
}

// The NOAA-archive programs: keys of the PROGRAMS dict.
const _programsPy = _repoFile("backend/ingestion/acoustic_noaa_archive_ingest.py");
const _archiveSources = _mustFind(
  _programsPy.slice(_programsPy.indexOf("PROGRAMS: dict")),
  /^ {4}"([a-z0-9_]+)": \{$/gm,
  20,
  "PROGRAMS keys",
);

// The non-archive sources: the `("name", module.fetch_…)` rows in the sync
// chain. `station_sources()` also splices the archive programs in, but those
// arrive through the list above.
const _acousticPy = _repoFile("backend/domains/acoustic.py");
const _otherSources = _mustFind(
  _acousticPy.slice(_acousticPy.indexOf("def station_sources")),
  /\("([a-z0-9_]+)", *\s*acoustic_\w+\.fetch_/g,
  11,
  "non-archive sync sources",
);

const KNOWN_BACKEND_SOURCES = new Set([..._archiveSources, ..._otherSources]);

const DEFAULT_COLOR = hydrophoneSourceColor("__not_a_real_source__");

describe("hydrophone source registries agree with each other", () => {
  const chipKeys: Set<string> = new Set(HYDROPHONE_SOURCE_DEFS.map((d): string => d.key));
  const colorKeys = new Set(Object.keys(HYDROPHONE_SOURCE_COLOR));
  const labelKeys = new Set(Object.keys(HYDROPHONE_SOURCE_LABEL));

  it("every filter chip has a colour that is not the default fallback", () => {
    const missing = HYDROPHONE_SOURCE_DEFS
      .filter((d) => !colorKeys.has(d.key))
      .map((d) => d.key);
    expect(missing).toEqual([]);

    const fallsBackToDefault = HYDROPHONE_SOURCE_DEFS
      .filter((d) => hydrophoneSourceColor(d.key).join(",") === DEFAULT_COLOR.join(","))
      .map((d) => d.key);
    expect(fallsBackToDefault).toEqual([]);
  });

  it("every filter chip has a label distinct from its raw key", () => {
    const missing = HYDROPHONE_SOURCE_DEFS
      .filter((d) => !(d.key in HYDROPHONE_SOURCE_LABEL))
      .map((d) => d.key);
    expect(missing).toEqual([]);
  });

  it("every colour entry has a matching chip and label (no orphans)", () => {
    const orphanFromChips = [...colorKeys].filter((k) => !chipKeys.has(k));
    expect(orphanFromChips).toEqual([]);
    const orphanFromLabels = [...colorKeys].filter((k) => !labelKeys.has(k));
    expect(orphanFromLabels).toEqual([]);
  });

  it("every label entry has a matching chip and colour (no orphans)", () => {
    const orphanFromChips = [...labelKeys].filter((k) => !chipKeys.has(k));
    expect(orphanFromChips).toEqual([]);
    const orphanFromColors = [...labelKeys].filter((k) => !colorKeys.has(k));
    expect(orphanFromColors).toEqual([]);
  });

  it("all three registries expose exactly the same key set", () => {
    expect([...chipKeys].sort()).toEqual([...colorKeys].sort());
    expect([...chipKeys].sort()).toEqual([...labelKeys].sort());
  });

  it(`every known backend source (${KNOWN_BACKEND_SOURCES.size} total) is covered by all three registries`, () => {
    const uncovered = [...KNOWN_BACKEND_SOURCES].filter(
      (k) => !chipKeys.has(k) || !colorKeys.has(k) || !labelKeys.has(k),
    );
    expect(uncovered).toEqual([]);
  });

  it("md_wea_cpod is registered lowercase, matching acoustic_stations.source — not the bucket's MD_WEA_CPOD casing", () => {
    expect(chipKeys.has("md_wea_cpod")).toBe(true);
    expect(colorKeys.has("md_wea_cpod")).toBe(true);
    expect(labelKeys.has("md_wea_cpod")).toBe(true);
    expect(chipKeys.has("MD_WEA_CPOD")).toBe(false);
  });

  it("no two of the 8 sources added 2026-09-15 share a colour with each other or with any pre-existing source", () => {
    const added = [
      "afsc", "cornell", "mbarc_socal", "mbarc_arctic", "mbarc_flip",
      "swfsc", "rutgers_njrmi", "md_wea_cpod",
    ];
    const seen = new Map<string, string>();
    for (const [key, rgba] of Object.entries(HYDROPHONE_SOURCE_COLOR)) {
      const sig = rgba.join(",");
      if (seen.has(sig) && (added.includes(key) || added.includes(seen.get(sig)!))) {
        throw new Error(`Colour collision: ${key} and ${seen.get(sig)} share ${sig}`);
      }
      if (!seen.has(sig)) seen.set(sig, key);
    }
  });
});
