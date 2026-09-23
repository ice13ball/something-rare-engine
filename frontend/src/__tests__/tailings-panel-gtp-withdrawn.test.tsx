// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Global Tailings Portal (GRID-Arendal) fields are withdrawn — decided
// 2026-09-23, see backend/domains/land/common.py TAILINGS_SERVED_WHERE /
// TAILINGS_PORTAL_COLUMNS. The backend no longer sends these fields on ANY
// row, but this test does not trust that: it renders TailingsPanel with a
// feature whose `properties` still carry Portal fields (as if a future bug
// reintroduced them on the wire) and asserts none of those values reach the
// DOM. A source grep for `p.hazard_raw` cannot tell "never read" from "read
// but not rendered", and cannot catch the value reaching the DOM through a
// spread or a helper — this renders the real component instead.
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { TailingsPanel } from "../components/panels/land/TailingsPanel";

afterEach(() => cleanup());

// A row that still carries Global Tailings Portal-derived values — exactly
// what production must never serve again, but the panel must also never
// print if it somehow arrives.
const WITH_PORTAL_FIELDS = {
  id: 900002,
  dam_name: "TEST Enriched Dam",
  country: "Testland",
  data_source: "grid-enriched",
  hazard_raw: "Extreme",
  owner_company: "X Corp",
  classification_system: "ANCOLD 2012",
  disclosure_link: "https://tailing.grida.no/disclosures/TEST2",
};

describe("TailingsPanel — Global Tailings Portal fields withdrawn 2026-09-23", () => {
  it("never renders a Portal-derived value, even when properties still carry one", () => {
    const { container } = render(
      <TailingsPanel properties={WITH_PORTAL_FIELDS as never} />
    );
    const text = container.textContent ?? "";
    expect(text).not.toContain("Extreme");
    expect(text).not.toContain("X Corp");
    expect(text).not.toContain("ANCOLD 2012");
    expect(text).not.toContain("tailing.grida.no");
  });

  it("still renders WAPHA-origin fields — this is a field cut, not a blackout", () => {
    const { container } = render(
      <TailingsPanel properties={WITH_PORTAL_FIELDS as never} />
    );
    expect(container.textContent).toContain("TEST Enriched Dam");
    expect(container.textContent).toContain("Testland");
  });
});
