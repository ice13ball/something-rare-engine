// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `dams` is loaded from GOODD (GOOD2_dams.shp, 2019-08-16), whose only fields
// are DAM_ID, Count_ID, Latitud and Longitud. Its DAM_ID landed in our
// `dam_name` column. Measured on production 2026-09-10: 38,667 rows, every
// dam_name a bare sequential integer starting at 1000000, and river, country,
// height_m, purpose, year_built and volume_mcm 0% populated — because GOODD
// does not publish them.
//
// ⛔ An internal identifier rendered as a name is worse than an empty field: it
// looks like data. The panel's Wikipedia link searched for "1000000 dam".
//
// ⛔ This test RENDERS the panel. A source check on the flag's name stayed
// green when the flag was set to a constant false — the guard bound the
// identifier, not the behaviour.
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { DamPanel } from "../components/panels/land/DamPanel";

afterEach(() => cleanup());

const goodd = (extra: Record<string, unknown> = {}) =>
  render(<DamPanel properties={{ dam_name: "1000000", ...extra } as never} />);

describe("DamPanel — a GOODD id is not a name", () => {
  it("does not present the bare identifier as the dam's name", () => {
    const { container } = goodd();
    const header = container.querySelector("h2, h3, [class*='text-lg'], [class*='font-semibold']");
    expect(header?.textContent?.trim()).not.toBe("1000000");
  });

  it("shows the identifier, labelled as an identifier", () => {
    goodd();
    expect(screen.getByText(/GOODD dam ID/i)).toBeTruthy();
    expect(screen.getAllByText("1000000").length).toBeGreaterThan(0);
  });

  it("says the source carries locations only, so six empty rows do not read as a failed fetch", () => {
    goodd();
    expect(screen.getByText(/georeferences dam locations only/i)).toBeTruthy();
  });

  it("offers no Wikipedia search for a number", () => {
    // "1000000 dam" cannot match anything.
    const { container } = goodd();
    const wiki = [...container.querySelectorAll("a")].filter(
      a => (a.getAttribute("href") ?? "").includes("wikipedia.org"));
    expect(wiki).toHaveLength(0);
  });

  it("still behaves normally for a real name, if GDW is ever loaded", () => {
    // ⛔ The mirror. Suppressing the header for every dam would satisfy the
    // first test and break the layer the day proper attributes arrive.
    const { container } = render(
      <DamPanel properties={{ dam_name: "Kariba Dam", river: "Zambezi" } as never} />);
    expect(screen.getByText("Kariba Dam")).toBeTruthy();
    expect(screen.getByText("Zambezi")).toBeTruthy();
    expect(screen.queryByText(/GOODD dam ID/i)).toBeNull();
    const wiki = [...container.querySelectorAll("a")].filter(
      a => (a.getAttribute("href") ?? "").includes("wikipedia.org"));
    expect(wiki.length).toBeGreaterThan(0);
  });
});
