// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * The Coastdom year filter's reset link read `t("common:reset")` — a key that does not exist (the string
 * lives at `common:actions.reset`), so the button rendered the literal key. Renders the real row with
 * the real bundled English `common` namespace.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { CoastdomRow } from "../components/controls/sections/oceanClimatology/CoastdomRow";
import { useMapStore } from "../store/mapStore";

afterEach(() => { cleanup(); useMapStore.getState().resetAllFilters(); });

describe("Coastdom year filter reset link", () => {
  it("shows the translated word, not the i18n key", () => {
    useMapStore.setState({ coastdomYearBounds: { min: 1978, max: 2022 }, coastdomYearRange: [1990, 2000] });
    render(<CoastdomRow expandedFilter="coastdom" toggleExpand={() => {}} toggle={() => {}} flyToLayer={null} />);
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/common:|reset"/);
  });
});
