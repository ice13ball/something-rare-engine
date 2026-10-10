// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it } from "vitest";
import { LAYER_DEFAULTS, sortDeckLayers } from "../utils/layerConfig";

describe("argo-oxygen-points deck layer order (real nested layersRaw shape)", () => {
  it("sorts after every oxygen-deox bitmap tile, which arrive as a nested array", () => {
    const layers = [{ id: "argo-oxygen-points" }, [{ id: "oxygen-deox-bitmap-recent-500-0" }, { id: "oxygen-deox-bitmap-recent-500-1" }]];
    const sorted = sortDeckLayers(layers, LAYER_DEFAULTS).map((l: any) => l.id);
    expect(sorted).toHaveLength(3);
    expect(sorted[sorted.length - 1]).toBe("argo-oxygen-points");
  });
});
