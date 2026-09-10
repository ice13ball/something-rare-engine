// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Frontend mirror of the backend export layer registry.
// Used by the ExportPanel to list exportable layers + their metadata.

export interface ExportLayerMeta {
  id: string;
  /** Map toggle id — only set when the export id differs from the map LayerId. */
  mapLayerId?: string;
  label: string;
  kind: "vector" | "composite" | "field";
  geomKind?: "point" | "polygon" | "line";
  family: string;
  source: string;
  sourceUrl: string;
  citation?: string;
  composite?: boolean;
  /** Show in the export panel even when no matching map layer is toggled on
   *  (for field exports with no natural per-AOI map toggle, e.g. bathymetry). */
  alwaysAvailable?: boolean;
}

/** Returns the map LayerId that corresponds to this export entry. */
export const mapIdOf = (l: ExportLayerMeta): string => l.mapLayerId ?? l.id;

export const EXPORT_LAYERS_FE: ExportLayerMeta[] = [
  {
    id: "arctic-rivers",
    label: "Arctic River Inputs",
    kind: "vector",
    geomKind: "point",
    family: "Arctic & carbon",
    source: "ArcticGRO + PANGAEA",
    sourceUrl: "https://arcticgreatrivers.org/data/",
  },
  {
    id: "arctic-catchments",
    label: "Arctic Catchments (ARCADE)",
    kind: "vector",
    geomKind: "polygon",
    family: "Arctic & carbon",
    source: "ARCADE v1",
    sourceUrl: "https://doi.org/10.34894/U9HSPV",
  },
  {
    // Active-gated on the real "vme-suitability" map toggle (id matches the LayerId, so
    // mapIdOf falls through to it) — not alwaysAvailable: this is a modeled surface and
    // users should see it on the map before pulling it down.
    id: "vme-suitability",
    label: "VME Coral Suitability (modeled)",
    kind: "vector",
    geomKind: "polygon",
    family: "Life & geology",
    source: "Platform-derived MaxEnt SDM — occurrences NOAA DSCRTP",
    sourceUrl: "https://www.ncei.noaa.gov/products/deep-sea-corals",
  },
  {
    // Active-gated on the real "coral-acid-exposure" map toggle (id matches the LayerId,
    // so mapIdOf falls through to it) — mirrors the vme-suitability entry above; this is
    // the VME model crossed with the aragonite saturation horizons, so it lives in the
    // same "Life & geology" family, not "Ocean fields".
    id: "coral-acid-exposure",
    label: "Coral acidification exposure (modeled)",
    kind: "vector",
    geomKind: "polygon",
    family: "Life & geology",
    source: "Platform-derived: VME MaxEnt suitability x reconstructed aragonite horizons x GEBCO 2024",
    sourceUrl: "https://www.glodap.info/",
    citation: "Occurrences: NOAA DSCRTP. Predictors: GEBCO 2024, Dutkiewicz et al. 2015, WOA23, ISAS20, GLODAPv2 (Lauvset et al. 2016; Key et al. 2015).",
  },
  {
    id: "sios-svalbard",
    label: "SIOS Svalbard Observing",
    kind: "vector",
    geomKind: "point",
    family: "Arctic & carbon",
    source: "SIOS Station REST",
    sourceUrl: "https://sios-svalbard.org/metadata_search",
  },
  {
    id: "marine-carbon",
    label: "Marine Carbon (raw sources → ZIP)",
    kind: "composite",
    composite: true,
    family: "Arctic & carbon",
    source: "SOCAT · GLODAP · ISAS20 · WOA23",
    sourceUrl: "https://www.glodap.info/",
  },
  {
    id: "memento",
    label: "MEMENTO CH₄/N₂O",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "GEOMAR MEMENTO",
    sourceUrl: "https://memento.geomar.de/",
    citation: "Kock & Bange 2015, Eos 96(3), doi:10.1029/2015EO023665",
  },
  {
    id: "methane-seeps",
    label: "Methane Seeps (SEAFLEA)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "SEAFLEA",
    sourceUrl: "https://www.ncei.noaa.gov/",
    citation: "Phrampus et al. 2020",
  },
  {
    id: "geotraces",
    label: "GEOTRACES trace metals",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "GEOTRACES IDP2025 (BODC)",
    sourceUrl: "https://www.bodc.ac.uk/geotraces/",
  },
  {
    id: "geotraces-values",
    label: "GEOTRACES all parameters (per-sample values)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "GEOTRACES IDP2025 (BODC)",
    sourceUrl: "https://www.bodc.ac.uk/geotraces/",
  },
  {
    id: "mosaic",
    mapLayerId: "mosaic-sediment",
    label: "Marine Sediment Carbon (MOSAIC)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "MOSAIC (ETH Zürich)",
    sourceUrl: "https://mosaic.ethz.ch/",
    citation: "Van der Voort et al. 2021 (ESSD 13:2135)",
  },
  // --- ISA & seabed registries ---
  {
    id: "contracts",
    label: "Mining contracts (ISA)",
    kind: "vector",
    geomKind: "polygon",
    family: "ISA & seabed",
    source: "International Seabed Authority (ISA)",
    sourceUrl: "https://www.isa.org.jm/exploration-areas",
  },
  {
    id: "reserved-areas",
    label: "Reserved areas (ISA)",
    kind: "vector",
    geomKind: "polygon",
    family: "ISA & seabed",
    source: "International Seabed Authority (ISA)",
    sourceUrl: "https://www.isa.org.jm/exploration-areas",
  },
  {
    id: "apeis",
    label: "APEIs (ISA)",
    kind: "vector",
    geomKind: "polygon",
    family: "ISA & seabed",
    source: "International Seabed Authority (ISA)",
    sourceUrl: "https://www.isa.org.jm/exploration-areas",
  },
  {
    id: "relinquished-areas",
    label: "Relinquished areas (ISA)",
    kind: "vector",
    geomKind: "polygon",
    family: "ISA & seabed",
    source: "International Seabed Authority (ISA)",
    sourceUrl: "https://www.isa.org.jm/exploration-areas",
  },
  {
    id: "offshore-activities",
    label: "Offshore activities",
    kind: "vector",
    geomKind: "polygon",
    family: "ISA & seabed",
    source: "National government offshore registries",
    sourceUrl: "https://www.boem.gov/",
  },
  // --- Task 5: Life & geology batch ---
  {
    id: "seamounts",
    label: "Seamounts",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "Yesson et al. 2020 (PANGAEA v2)",
    sourceUrl: "https://doi.pangaea.de/10.1594/PANGAEA.921688",
    citation: "Yesson et al. 2020, doi:10.1594/PANGAEA.921688",
  },
  {
    id: "hydrothermal-vents",
    label: "Hydrothermal vents",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "InterRidge Vents Database v3.4",
    sourceUrl: "https://vents-data.interridge.org/",
  },
  {
    id: "biodiversity-hotspots",
    label: "Biodiversity (OBIS)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "OBIS",
    sourceUrl: "https://obis.org/",
  },
  {
    id: "chess",
    label: "Chemosynthetic life (ChEssBase)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "ChEssBase (OBIS)",
    sourceUrl: "https://obis.org/dataset/21d3a7f0-fc5c-4e5e-8781-8cb929ebb47d",
  },
  // "eez" removed 2026-09-04: CC-BY 4.0 allows it, but VLIZ asks that their
  // products not be made available for download elsewhere. A courtesy, not an
  // obligation — reversible without asking anyone. The layer still renders.
  {
    id: "protected-marine-sites",
    label: "Marine protected sites (UNESCO)",
    kind: "vector",
    geomKind: "polygon",
    family: "Life & geology",
    source: "UNESCO World Heritage Marine + MarineRegions.org",
    sourceUrl: "https://whc.unesco.org/en/marine/",
  },
  {
    id: "deepdata-stations",
    label: "DeepData stations (ISA)",
    kind: "vector",
    geomKind: "point",
    family: "Life & geology",
    source: "ISA contractor DwC archives (via OBIS)",
    sourceUrl: "https://www.isa.org.jm/",
  },
  // --- Task 6: Sensors registry batch ---
  {
    id: "argo",
    label: "Argo floats",
    kind: "vector",
    geomKind: "point",
    family: "Sensors",
    source: "Argo (GDAC / Euro-Argo)",
    sourceUrl: "https://argo.ucsd.edu/",
  },
  {
    id: "oceansites",
    label: "OceanSITES moorings",
    kind: "vector",
    geomKind: "point",
    family: "Sensors",
    source: "OceanSITES / OceanOPS",
    sourceUrl: "https://www.oceansites.org/",
  },
  {
    id: "onc",
    label: "ONC observatories",
    kind: "vector",
    geomKind: "point",
    family: "Sensors",
    source: "Ocean Networks Canada (ONC)",
    sourceUrl: "https://data.oceannetworks.ca/",
  },
  {
    id: "onc-instruments",
    label: "ONC instruments",
    kind: "vector",
    geomKind: "point",
    family: "Sensors",
    source: "Ocean Networks Canada (ONC)",
    sourceUrl: "https://data.oceannetworks.ca/",
  },
  // "hydrophone-stations" removed 2026-09-04: one of the 22 aggregated networks
  // (MBARI MARS) is released for "internal research activities only" — a clause
  // on use, not just redistribution, which a bulk download cannot honour.
  {
    id: "wod-oxygen",
    label: "WOD oxygen profiles",
    kind: "vector",
    geomKind: "point",
    family: "Sensors",
    source: "NOAA World Ocean Database 2023 (WOD23)",
    sourceUrl: "https://www.ncei.noaa.gov/products/world-ocean-database",
    citation: "doi:10.7289/V5H70CVX",
  },
  // --- 2026-09-10: three entries the backend registry has always served but
  // the panel never listed. Found by check 20f of abyssal-new-layer-check:
  // the registry does NOT auto-discover, so a backend entry with no row here
  // is reachable by curl and invisible to every user. Counts verified live
  // before adding: permafrost-thaw 539, arctic-sediment-carbon 200,
  // seabed-substrate 441 over a small bbox each.
  {
    id: "permafrost-thaw",
    label: "Permafrost Thaw",
    kind: "vector",
    geomKind: "point",
    family: "Arctic & carbon",
    source: "Alaska Permafrost Thaw DB v2.0.0 (Webb et al. 2026) + ARTS v6.0.0",
    sourceUrl: "https://doi.org/10.5281/zenodo.16996415",
    citation: "alaska_webb: CC-BY 4.0; arts_panarctic: CC0",
  },
  {
    id: "arctic-sediment-carbon",
    label: "Arctic Sediment Carbon (CASCADE stations)",
    kind: "vector",
    geomKind: "point",
    family: "Arctic & carbon",
    source: "CASCADE v2, Bolin Centre for Climate Research",
    sourceUrl: "https://doi.org/10.17043/cascade-2",
    citation: "CC-BY 4.0",
  },
  {
    id: "seabed-substrate",
    label: "Seabed Substrate (Dutkiewicz 2015)",
    kind: "field",
    family: "Ocean fields",
    source: "Dutkiewicz et al. 2015 seafloor lithology (EarthByte)",
    sourceUrl: "https://www.earthbyte.org/seafloor-lithology-of-the-ocean-basins/",
    // ⛔ CC-BY-NC. Publishable only while this platform is not monetised —
    // see rules/layers/nc-licence-lineage.md before any paid tier.
    citation: "Dutkiewicz, A. et al. 2015, Geology, doi:10.1130/G36883.1 — CC-BY-NC 4.0",
  },
  // --- Task 7: Infrastructure — cable composite ---
  {
    id: "submarine-cables",
    label: "Submarine Cables",
    kind: "composite",
    composite: true,
    family: "Infrastructure",
    source: "EMODnet + NOAA Marine Cadastre + LINZ + ACMA + ONC + OOI",
    sourceUrl: "https://emodnet.ec.europa.eu/en/human-activities",
  },
  // --- Task 8: Land registry batch ---
  {
    id: "mining-footprints",
    label: "Mining footprints",
    kind: "vector",
    geomKind: "polygon",
    family: "Land",
    source: "Maus et al. 2022/2023 — PANGAEA",
    sourceUrl: "https://doi.org/10.1594/PANGAEA.942325",
    citation: "Maus et al. 2022/2023, doi:10.1594/PANGAEA.942325",
  },
  // "kbas" removed 2026-09-03: the licence clause names download access
  // explicitly, and this menu is that download access.
  // "wdpa" removed 2026-09-03: same reason.
  {
    id: "tailings",
    label: "Tailings dams",
    kind: "vector",
    geomKind: "point",
    family: "Land",
    source: "Hudson-Edwards et al. 2023 WAPHA (CC0, Dryad) + GRID-Arendal / UNEP Global Tailings Portal",
    sourceUrl: "https://doi.org/10.5061/dryad.j3tx95xmg",
  },
  {
    id: "fires",
    label: "Active fires",
    kind: "vector",
    geomKind: "point",
    family: "Land",
    source: "NASA FIRMS (MODIS / VIIRS)",
    sourceUrl: "https://firms.modaps.eosdis.nasa.gov/",
  },
  {
    id: "air-quality",
    label: "Air quality stations",
    kind: "vector",
    geomKind: "point",
    family: "Land",
    source: "OpenAQ v3",
    sourceUrl: "https://openaq.org/",
  },
  {
    id: "landslides",
    label: "Landslides",
    kind: "vector",
    geomKind: "point",
    family: "Land",
    source: "NASA COOLR / GSFC",
    sourceUrl: "https://gpm.nasa.gov/landslides/",
  },
  {
    id: "dams",
    label: "Dams",
    kind: "vector",
    geomKind: "point",
    family: "Land",
    source: "Global Dam Watch",
    sourceUrl: "https://www.globaldamwatch.org/",
  },
  {
    id: "water-risk",
    label: "Water risk (Aqueduct)",
    kind: "vector",
    geomKind: "polygon",
    family: "Land",
    source: "WRI Aqueduct 4.0",
    sourceUrl: "https://www.wri.org/aqueduct",
    citation: "WRI Aqueduct 4.0 (2023)",
  },
  // --- Task 9: Carbon field layers ---
  {
    id: "socat-co2",
    mapLayerId: "ocean-co2-surface",
    label: "Surface CO₂ (SOCAT)",
    kind: "field",
    family: "Carbon fields",
    source: "SOCAT v2026 (decadal gridded)",
    sourceUrl: "https://www.socat.info/",
    citation: "Bakker et al. 2026 (NCEI Accession 0315110, doi:10.25921/8dba-fr90)",
  },
  {
    id: "glodap-carbon",
    mapLayerId: "ocean-carbon",
    label: "Interior Carbon (GLODAP)",
    kind: "field",
    family: "Carbon fields",
    source: "GLODAP v2.2016b Mapped Climatology",
    sourceUrl: "https://www.glodap.info/",
    citation: "Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
  },
  {
    id: "isas20-oxygen",
    mapLayerId: "oxygen-deox",
    label: "Oxygen (ISAS)",
    kind: "field",
    family: "Carbon fields",
    source: "ISAS20 (BGC-Argo 2014–2018 mean)",
    sourceUrl: "https://www.seanoe.org/data/00412/52367/",
    citation: "ISAS20 release",
  },
  {
    id: "woa23",
    mapLayerId: "woa-climatology",
    label: "WOA Climatology",
    kind: "field",
    family: "Carbon fields",
    source: "NOAA World Ocean Atlas 2023 (WOA23)",
    sourceUrl: "https://www.ncei.noaa.gov/products/world-ocean-atlas",
    citation: "WOA23 release",
  },
  // --- Ocean fields: physical raster grids sampled on export (Phase 1) ---
  {
    id: "ocean-currents",
    label: "Ocean Currents (surface + 1000 m)",
    kind: "field",
    family: "Ocean fields",
    source: "CMEMS Global Ocean Physics (u/v velocity)",
    sourceUrl: "https://data.marine.copernicus.eu/",
    citation: "Copernicus Marine Service",
  },
  {
    // Active-gated on the real "ocean-acidification" map toggle (id matches the LayerId,
    // so mapIdOf falls through to it) — mirrors the ocean-currents entry above.
    id: "ocean-acidification",
    label: "Ocean Acidification (GLODAP ΩA/ΩC)",
    kind: "field",
    family: "Ocean fields",
    source: "GLODAP v2.2016b Mapped Climatology",
    sourceUrl: "https://www.glodap.info/",
    citation: "Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
  },
  {
    // Platform-derived aragonite saturation-horizon depth (2-D, no depth axis) —
    // its own export id, but gated on the same "ocean-acidification" map toggle.
    id: "ocean-acidification-horizon",
    mapLayerId: "ocean-acidification",
    label: "Aragonite saturation-horizon depth (modeled)",
    kind: "field",
    family: "Ocean fields",
    source: "Platform-derived from GLODAP v2.2016b OmegaA",
    sourceUrl: "https://www.glodap.info/",
    citation: "Derived from GLODAP OmegaA — Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
  },
  {
    // Platform-derived aragonite horizon SHIFT (present-day vs preindustrial reconstruction,
    // both via PyCO2SYS) — its own export id, gated on the same "ocean-acidification" map toggle.
    id: "ocean-acidification-horizon-shift",
    mapLayerId: "ocean-acidification",
    label: "Aragonite horizon shift since preindustrial (modeled)",
    kind: "field",
    family: "Ocean fields",
    source: "Platform-derived from GLODAP v2.2016b OmegaA (present-day vs preindustrial reconstruction)",
    sourceUrl: "https://www.glodap.info/",
    citation: "Derived from GLODAP OmegaA — Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
  },
  {
    // Active-gated on the real "cumulative-human-impact" map toggle (id matches the LayerId,
    // so mapIdOf falls through to it) — mirrors the ocean-acidification entry above.
    id: "cumulative-human-impact",
    label: "Cumulative Human Impact (modelled)",
    kind: "field",
    family: "Ocean fields",
    source: "NCEAS / Halpern et al. 2025",
    sourceUrl: "https://doi.org/10.1126/science.adv2906",
    citation: "Halpern et al. 2025 (Science, doi:10.1126/science.adv2906); data archive doi:10.5063/F18K77KZ, CC0 1.0",
  },
  {
    id: "bathymetry",
    alwaysAvailable: true,
    label: "Bathymetry (GEBCO 2024)",
    kind: "field",
    family: "Ocean fields",
    source: "GEBCO 2024 Grid",
    sourceUrl: "https://www.gebco.net/",
    citation: "GEBCO Compilation Group (2024)",
  },
];
