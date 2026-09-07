const LAYER_TOOLTIPS_META: Record<string, LayerTooltipMeta> = {
  // ── Ocean ──
  "contracts": {
    source: "International Seabed Authority — DeepData",
    sourceUrl: "https://www.isa.org.jm/exploration-contracts/",
    pairsWith: ["hydrothermal-vents", "biodiversity-hotspots", "argo"],
  },
  "ocean-currents": {
    source: "Copernicus Marine Service — GLOBAL_ANALYSISFORECAST_PHY_001_024 (cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m)",
    sourceUrl: "https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/description",
    pairsWith: ["argo", "contracts", "hydrothermal-vents"],
  },
  "woa-climatology": {
    source: "NOAA NCEI — World Ocean Atlas 2023 (Accession 0270533)",
    sourceUrl: "https://www.ncei.noaa.gov/products/world-ocean-atlas",
    pairsWith: ["argo", "ocean-currents", "biodiversity-hotspots"],
  },
};
