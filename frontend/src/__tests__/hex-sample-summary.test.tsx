// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect, beforeAll } from "vitest";
import { render } from "@testing-library/react";
import i18n from "../i18n";
import { HexSampleSummary } from "../components/panels/shared/HexSampleSummary";

// legend.json is fetched over HTTP in the real app (see src/i18n.ts); tests
// don't run a server for it, so seed the two keys this component needs
// directly into the already-initialized singleton. Without this, a missing
// translation would fall back to the raw key, which would still happen to
// contain no digits and could hide a broken interpolation.
beforeAll(() => {
  i18n.addResourceBundle(
    "en",
    "legend",
    {
      sampleDate: {
        ofTotal: "of {{total}}",
        decadesShown: "Decades shown",
        undatedSuffix: "undated",
      },
    },
    true,
    true
  );
});

const PROPS = { count: 42, by_decade: { "1980": 3, "1990": 39 }, n_undated: 0 };

describe("HexSampleSummary", () => {
  it("renders only the total when no decade filter is active", () => {
    render(
      <HexSampleSummary
        properties={PROPS}
        selected={new Set()}
        nounOne="cast"
        nounMany="casts"
        numberClass="text-teal-300"
      />
    );
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/\b42\s+casts in this grid cell/);
    expect(text).not.toContain("of 42");
  });

  it("shows both the filtered and total count, plus the active decade, when a filter is active", () => {
    render(
      <HexSampleSummary
        properties={PROPS}
        selected={new Set(["1980"])}
        nounOne="cast"
        nounMany="casts"
        numberClass="text-teal-300"
      />
    );
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/\b3\s+of 42\s+casts in this grid cell/);
    expect(text).toContain("1980s");
  });

  it("names the undated bucket (not a year) when only 'undated' is selected", () => {
    render(
      <HexSampleSummary
        properties={{ count: 7, by_decade: { "1990": 5 }, n_undated: 2 }}
        selected={new Set(["undated"])}
        nounOne="cast"
        nounMany="casts"
        numberClass="text-teal-300"
      />
    );
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/\b2\s+of 7\s+casts in this grid cell/);
    expect(text).toContain("undated");
    expect(text).not.toMatch(/\b19\d0s\b/); // no year-decade token, e.g. not "1990s"
  });

  it("orders multiple selected decades ascending, oldest first", () => {
    render(
      <HexSampleSummary
        properties={PROPS}
        selected={new Set(["1990", "1980"])}
        nounOne="cast"
        nounMany="casts"
        numberClass="text-teal-300"
      />
    );
    const text = document.body.textContent ?? "";
    expect(text).toContain("1980s, 1990s");
  });
});
