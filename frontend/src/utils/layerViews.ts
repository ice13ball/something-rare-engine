// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/layerViews.ts
// Per-layer "view" (display-state) registry — the source of truth for which display
// settings a startup profile can override, and how applyProfile applies them.
// KEEP IN SYNC with store/mapStore.ts (setter names + defaults) and
// admin-panel/src/layerViews.ts (options mirror). Excludes the /meta-driven variable
// menus (woa/carbon/co2 variable), which keep their store default.

export interface ViewField {
  key: string;
  label: string;
  kind: "enum" | "number";
  options?: { value: string; label: string }[];
  setter: string;               // store setter name
  def: string | number;
}

const dh = [{ value: "dots", label: "Dots" }, { value: "hexes", label: "Hexagons" }];
const fh = [{ value: "field", label: "Field" }, { value: "hexes", label: "Hexagons" }];

export const LAYER_VIEWS: Record<string, ViewField[]> = {
  "geotraces": [
    { key: "element", label: "Element", kind: "enum", setter: "setGeotracesElement", def: "fe",
      options: [{value:"mn",label:"Mn"},{value:"fe",label:"Fe"},{value:"co",label:"Co"},{value:"ni",label:"Ni"},{value:"cu",label:"Cu"}] },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setGeotracesDisplayMode", def: "dots", options: dh },
  ],
  "memento": [
    { key: "gas", label: "Gas", kind: "enum", setter: "setMementoGas", def: "n2o",
      options: [{value:"ch4",label:"CH₄"},{value:"n2o",label:"N₂O"}] },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setMementoDisplayMode", def: "dots", options: dh },
  ],
  "mosaic-sediment": [
    { key: "variable", label: "Variable", kind: "enum", setter: "setMosaicVariable", def: "toc",
      options: [{value:"toc",label:"TOC"},{value:"tn",label:"TN"},{value:"d13c",label:"δ¹³C"},{value:"d14c",label:"δ¹⁴C"}] },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setMosaicDisplayMode", def: "dots", options: dh },
  ],
  "arctic-catchments": [
    { key: "variable", label: "Variable", kind: "enum", setter: "setArcticCatchmentsVariable", def: "ocs_mean",
      options: [{value:"ocs_mean",label:"Soil OC stock"},{value:"oc_tot",label:"Total OC"},{value:"runoff_mean",label:"Runoff"},{value:"pf_frac",label:"Permafrost frac"},{value:"t_2m_mean",label:"Air temp"}] },
  ],
  "woa-climatology": [
    { key: "depth", label: "Depth (m)", kind: "number", setter: "setWoaDepth", def: 500 },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setWoaDisplayMode", def: "field", options: fh },
  ],
  "ocean-carbon": [
    { key: "depth", label: "Depth (m)", kind: "number", setter: "setCarbonDepth", def: 0 },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setCarbonDisplayMode", def: "field", options: fh },
  ],
  "ocean-acidification": [
    { key: "variable", label: "Variable", kind: "enum", setter: "setAcidificationVariable", def: "aragonite",
      options: [{value:"aragonite",label:"Aragonite Ω"},{value:"calcite",label:"Calcite Ω"},{value:"horizon",label:"Saturation horizon"},{value:"horizon-shift",label:"Horizon shift"}] },
    { key: "depth", label: "Depth (m)", kind: "number", setter: "setAcidificationDepth", def: 0 },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setAcidificationDisplayMode", def: "field", options: fh },
  ],
  "marine-carbon": [
    { key: "variable", label: "Variable", kind: "enum", setter: "setMarineCarbonVariable", def: "co2_fco2",
      options: [{value:"co2_fco2",label:"Surface fCO₂"},{value:"dic",label:"DIC"},{value:"o2_recent",label:"Oxygen"},{value:"woa_temp",label:"Temperature"}] },
    { key: "depth", label: "Depth (m)", kind: "number", setter: "setMarineCarbonDepth", def: 0 },
  ],
  "vme-suitability": [
    { key: "view", label: "View", kind: "enum", setter: "setVmeView", def: "suitability",
      options: [{value:"suitability",label:"Suitability"},{value:"uncertainty",label:"Uncertainty"}] },
  ],
  "ocean-co2-surface": [
    { key: "decade", label: "Decade idx", kind: "number", setter: "setCo2Decade", def: 5 },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setCo2DisplayMode", def: "field", options: fh },
  ],
  "oxygen-deox": [
    { key: "view", label: "View", kind: "enum", setter: "setOxygenView", def: "change",
      options: [{value:"recent",label:"Recent O₂"},{value:"change",label:"Deoxygenation Δ"}] },
    { key: "depth", label: "Depth (m)", kind: "number", setter: "setOxygenDepth", def: 500 },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setOxygenDisplayMode", def: "field", options: fh },
  ],
  "seabed-substrate": [
    { key: "displayMode", label: "Display", kind: "enum", setter: "setSeabedDisplayMode", def: "field", options: fh },
  ],
  "arctic-sediment-carbon": [
    { key: "variable", label: "Variable", kind: "enum", setter: "setCascadeVariable", def: "oc",
      options: [{value:"oc",label:"Organic C"},{value:"tn",label:"Total N"},{value:"d13c",label:"δ¹³C"},{value:"d14c",label:"δ¹⁴C"}] },
    { key: "displayMode", label: "Display", kind: "enum", setter: "setCascadeDisplayMode", def: "field",
      options: [{value:"field",label:"Field"},{value:"stations",label:"Stations"}] },
  ],
  "ocean-currents": [
    { key: "depth", label: "Depth", kind: "enum", setter: "setCurrentsDepth", def: "surface",
      options: [{value:"surface",label:"Surface"},{value:"1000m",label:"1000 m"}] },
  ],
};
