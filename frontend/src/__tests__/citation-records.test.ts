// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Abyssal Claims has TWO Zenodo records and the site cites them in FOUR places:
// the JSON-LD graph (seo/site-graph.json), the SSR /about page (server.js via
// render-page.js), the client legal pages (content/legalContent.ts) and the
// Google Scholar meta tags (components/SEO.tsx). Each held its own copy of the
// DOI, so until 2026-09-15 all four named the DOCUMENTATION record — including
// the sentence that says the software is licensed AGPL, and the Scholar tag
// that tells an indexer what this page is.
//
//   10.5281/zenodo.22728476  Software, AGPL-3.0-or-later, v1.0.0
//   10.5281/zenodo.19745884  Software documentation, CC-BY-4.0, v1.6
//
// Verified against the Zenodo API on 2026-09-15: the software record carries
// `isDocumentedBy` pointing at the documentation record. They are a pair, and
// swapping them puts a CC-BY licence on AGPL software on the page people copy
// citations from.
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect } from "vitest";

import siteGraph from "../../seo/site-graph.json";
import {
  ABOUT,
  CODE_DOI,
  CODE_DOI_URL,
  CODE_LICENCE,
  CODE_TITLE,
  DOCS_DOI,
  DOCS_DOI_URL,
  DOCS_LICENCE,
} from "../content/legalContent";

function repoFile(rel: string): string {
  for (const base of [process.cwd(), path.resolve(process.cwd(), "..")]) {
    const p = path.resolve(base, rel);
    if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
  }
  throw new Error(
    `cannot find ${rel} from ${process.cwd()} — this test reads the SSR and ` +
    `licence files directly, and skipping that would make it decorative`,
  );
}

const webApp = (siteGraph["@graph"] as Array<Record<string, unknown>>)
  .find((n) => n["@type"] === "WebApplication") as Record<string, any>;

describe("the two Zenodo records are cited as themselves", () => {
  it("the JSON-LD identifies the platform by the SOFTWARE record", () => {
    expect(webApp).toBeTruthy();
    expect(webApp.identifier).toBe(CODE_DOI_URL);
    expect(webApp.sameAs?.[0]).toContain("22728476");
  });

  it("the JSON-LD carries the documentation record as a companion, not as the identity", () => {
    expect(webApp.citation?.identifier).toBe(DOCS_DOI_URL);
    expect(webApp.citation?.identifier).not.toBe(webApp.identifier);
  });

  it("the two DOIs are never the same value", () => {
    // ⛔ Guards the copy-paste fix: setting both constants to the code DOI
    // would satisfy every "uses CODE_DOI" assertion below.
    expect(CODE_DOI).not.toBe(DOCS_DOI);
    expect(CODE_DOI).toContain("22728476");
    expect(DOCS_DOI).toContain("19745884");
  });

  it("each record keeps its own licence", () => {
    expect(CODE_LICENCE).toBe("AGPL-3.0-or-later");
    expect(DOCS_LICENCE).toBe("CC-BY-4.0");
    expect(webApp.license).toContain("agpl");
    expect(webApp.citation?.license).toContain("creativecommons");
  });
});

describe("the graph carries everything the SSR pages read from it", () => {
  // render-page.js now THROWS on a missing field instead of falling back to a
  // hardcoded DOI, so an incomplete graph takes the server down at import
  // rather than serving a confident wrong citation. These are the fields it
  // requires.
  it.each([
    ["identifier", () => webApp.identifier],
    ["sameAs[0]", () => webApp.sameAs?.[0]],
    ["license", () => webApp.license],
    ["citation.identifier", () => webApp.citation?.identifier],
    ["creator.name", () => webApp.creator?.name],
    ["creator.url", () => webApp.creator?.url],
  ])("has %s", (_label, get) => {
    expect(get()).toBeTruthy();
  });

  it("render-page.js no longer substitutes a DOI when the graph is silent", () => {
    const src = repoFile("frontend/seo/render-page.js");
    const fallback = /\|\|\s*['"]https:\/\/doi\.org/.test(src);
    expect(fallback).toBe(false);
  });
});

describe("no surface re-types a DOI it could import", () => {
  it("SEO.tsx holds no bare Zenodo DOI literal", () => {
    const src = repoFile("frontend/src/components/SEO.tsx");
    const literals = src.match(/10\.5281\/zenodo\.\d+/g) ?? [];
    expect(literals).toEqual([]);
  });

  it("server.js holds no bare Zenodo DOI literal", () => {
    const src = repoFile("frontend/server.js");
    const literals = src.match(/10\.5281\/zenodo\.\d+/g) ?? [];
    expect(literals).toEqual([]);
  });

  it("the SSR about page names both records", () => {
    const src = repoFile("frontend/server.js");
    expect(src).toContain("siteCitation.doi");
    expect(src).toContain("siteCitation.docsDoi");
  });
});

describe("the citation text says what the records actually are", () => {
  const citation = ABOUT.sections.find((s) => s.id === "citation");
  const flat = JSON.stringify(citation);

  it("exists", () => {
    expect(citation).toBeTruthy();
  });

  it("no longer calls the platform a dataset", () => {
    // ⛔ The suggested citation read "[Dataset]". Neither record is one, and
    // the repository's own .zenodo.json states "No scientific data is
    // included" — every layer is fetched at runtime from its provider.
    expect(flat).not.toContain("[Dataset]");
  });

  it("offers the software record and labels it as software", () => {
    expect(flat).toContain(CODE_DOI);
    expect(flat).toContain("[Computer software]");
    expect(flat).toContain(CODE_TITLE);
  });

  it("offers the documentation record and labels it as documentation", () => {
    expect(flat).toContain(DOCS_DOI);
    expect(flat).toContain("[Software documentation]");
  });

  it("the SSR page offers the same two records as the client page", () => {
    // ⚠️ Whitespace-normalised, because the assertion is about what a reader
    // sees. The labels are line-wrapped in the template literal and HTML
    // collapses that run of spaces — matching the raw source would fail on
    // formatting while the page renders correctly, which is a test that
    // reports the wrong thing.
    const rendered = repoFile("frontend/server.js").replace(/\s+/g, " ");
    expect(rendered).toContain("[Computer software]");
    expect(rendered).toContain("[Software documentation]");
    expect(rendered).not.toContain("[Dataset]");
  });
});

describe("the AGPL section 7(b) notice is preserved, not regenerated", () => {
  // ⛔ This block is a licence condition, not a citation: §7(b) requires every
  // redistributor to preserve it verbatim. It must match
  // LICENSE-ADDITIONAL-TERMS.md character for character, and it must NOT be
  // built from the DOI constants — a required notice that changes when a
  // constant changes is not preserved.
  const licence = repoFile("LICENSE-ADDITIONAL-TERMS.md");
  const block = licence.split("```")[1] ?? "";
  const required = block.trim();

  it("the licence file still states a notice", () => {
    expect(required).toContain("Based on Abyssal Claims");
    expect(required.split("\n").length).toBe(3);
  });

  it("the site renders that notice byte for byte", () => {
    const src = repoFile("frontend/src/content/legalContent.ts");
    for (const line of required.split("\n")) {
      expect(src).toContain(line.trim());
    }
  });

  it("the notice is a literal, not an interpolation", () => {
    const src = repoFile("frontend/src/content/legalContent.ts");
    // The notice's DOI line appears as a quoted literal, not `${...}`.
    expect(src).toContain('"https://doi.org/10.5281/zenodo.19745884",');
  });
});
