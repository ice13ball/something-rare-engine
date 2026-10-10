// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PlanktonRow } from "../components/controls/sections/PlanktonRow";
import { useMapStore } from "../store/mapStore";

const s = () => useMapStore.getState();
const row = () => (
  <PlanktonRow expandedFilter="plankton-occurrences" toggleExpand={() => {}}
    toggle={(id) => s().toggleLayer(id)} flyToLayer={null} />
);
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

beforeEach(() => {
  s().resetAllFilters();
  useMapStore.setState({ activeLayers: new Set(["plankton-occurrences"]), enabledLayerIds: null } as any);
});
afterEach(cleanup);

describe("Plankton (OBIS) filter row", () => {
  it("lights every chip by default: five groups, ten decade classes, four depth bands, eDNA on", () => {
    render(row());
    for (const name of ["Copepods", "Krill", "Diatoms", "Coccolithophores", "Dinoflagellates", "No date",
                        "Before 1950", "2010s", "0–200 m", "200–1000 m", "> 1000 m", "No depth"]) {
      expect(pressed(name), name).toBe("true");
    }
    expect((screen.getByLabelText("Show eDNA records") as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByRole("button", { name: "Reset filters" })).toBeNull();
  });

  it("a chip hides its value, and the row's reset link restores everything", () => {
    render(row());
    fireEvent.click(screen.getByRole("button", { name: "Diatoms" }));
    fireEvent.click(screen.getByRole("button", { name: "No date" }));
    fireEvent.click(screen.getByLabelText("Show eDNA records"));
    expect([...s().planktonGroupFilters]).toEqual(["copepoda", "euphausiacea", "coccolithophores", "dinoflagellates"]);
    expect(s().planktonDecadeFilters.has("-1")).toBe(false);
    expect(s().planktonDecadeFilters.size).toBe(9);
    expect(s().planktonShowEdna).toBe(false);
    expect(pressed("Diatoms")).toBe("false");
    expect(pressed("Copepods")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect([s().planktonGroupFilters.size, s().planktonDecadeFilters.size, s().planktonShowEdna]).toEqual([0, 0, true]);
  });
});
