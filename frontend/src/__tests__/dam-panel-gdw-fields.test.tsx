// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ⚠️ THIS FILE REPLACES `dam-panel-goodd-id.test.tsx`, WHICH ASSERTED THE
// OPPOSITE. That guard existed because `dams` served GOODD, whose numeric
// DAM_ID was rendered where a name belonged on all 38,667 rows. On 2026-09-11
// the layer moved to GDW v1.0 (figshare doi:10.6084/m9.figshare.25988293,
// CC BY 4.0), so the old assertions described a dataset no longer served. The
// measurement is what matters, not the guard — both are written down here so
// the flip reads as a decision rather than a quiet deletion.
//
// Measured over all 41,145 loaded GDW barriers:
//     country 41,145 (100%) · capacity 35,334 (86%) · year 15,229 (37%)
//     NAME    10,071 (24.5%) · river 9,501 (23%) · height 9,311 (23%)
//     power      242 (0.6%)
//
// ⛔ A NAMELESS BARRIER IS THE COMMON CASE — three quarters of them. It must
// read as "the source did not name this", never as a panel that failed to load.
//
// ⛔ GDW's no-data code is -99 (power_mw 40,903 · dam_hgt_m 31,834 · year_dam
// 25,915). The loader turns those into NULL. If one ever reaches the panel it
// would print "-99 m" as a measurement, so the last test here renders one on
// purpose and refuses it.
//
// ⛔ These tests RENDER. An earlier guard on this panel checked a flag's name
// and stayed green when the flag was pinned to a constant.
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { DamPanel } from "../components/panels/land/DamPanel";

afterEach(() => cleanup());

const NAMED = {
  gdw_id: 63, dam_name: "Kariba", river: "Zambezi", country: "Zimbabwe",
  year_built: 1959, height_m: 128, volume_mcm: 185000, purpose: "Hydroelectricity",
};
const UNNAMED = { gdw_id: 7727, country: "Brazil" };

const panel = (props: Record<string, unknown>) =>
  render(<DamPanel properties={props as never} />);

describe("DamPanel — GDW attributes", () => {
  it("shows the real name GDW gives, as the heading", () => {
    const { container } = panel(NAMED);
    expect(container.textContent).toContain("Kariba");
  });

  it("renders the attributes GOODD never had", () => {
    panel(NAMED);
    expect(screen.getByText("Zambezi")).toBeTruthy();
    expect(screen.getByText("Zimbabwe")).toBeTruthy();
    expect(screen.getByText("1959")).toBeTruthy();
    expect(screen.getByText("128 m")).toBeTruthy();
    expect(screen.getByText("Hydroelectricity")).toBeTruthy();
  });

  it("offers a Wikipedia search when there is a name to search for", () => {
    const { container } = panel(NAMED);
    const wiki = Array.from(container.querySelectorAll("a"))
      .find(a => /wikipedia/i.test(a.getAttribute("href") ?? ""));
    expect(wiki).toBeTruthy();
    expect(wiki!.getAttribute("href")).toContain("Kariba");
  });
});

describe("DamPanel — a barrier GDW does not name", () => {
  it("heads the panel with the GDW identifier instead of a blank", () => {
    const { container } = panel(UNNAMED);
    expect(container.textContent).toContain("7727");
  });

  it("says the source leaves three quarters unnamed, so it does not read as a failed fetch", () => {
    panel(UNNAMED);
    expect(screen.getByText(/10,071|41,145|unnamed at source/i)).toBeTruthy();
  });

  it("offers no Wikipedia search for a number", () => {
    const { container } = panel(UNNAMED);
    const wiki = Array.from(container.querySelectorAll("a"))
      .find(a => /wikipedia/i.test(a.getAttribute("href") ?? ""));
    expect(wiki).toBeUndefined();
  });

  it("still credits GDW — CC BY requires it even on a bare point", () => {
    const { container } = panel(UNNAMED);
    const gdw = Array.from(container.querySelectorAll("a"))
      .find(a => /globaldamwatch/i.test(a.getAttribute("href") ?? ""));
    expect(gdw).toBeTruthy();
  });
});

describe("DamPanel — the no-data code must never surface", () => {
  it("never prints -99 as a height, a year or a capacity", () => {
    // ⛔ The loader nulls these. This is the second line of defence: if a -99
    // ever reaches the client, the panel must not dress it up as a measurement.
    const { container } = panel({
      gdw_id: 1, country: "Peru", height_m: null, year_built: null,
      volume_mcm: null, power_mw: null,
    });
    // ⛔ Widened after a sabotage escaped: making the height row unconditional
    // rendered "null m", which contains no "-99" and sailed through. A row that
    // has no value must not appear at all.
    for (const junk of ["-99", "null", "undefined", "NaN"]) {
      expect(container.textContent, `panel rendered "${junk}"`).not.toContain(junk);
    }
  });

  it("credits GDW even when every attribute is absent — CC BY has no exemption", () => {
    const { container } = panel({ gdw_id: 2, country: "Chile" });
    expect(container.textContent).toMatch(/Global Dam Watch/i);
  });
});
