// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { LAYER_CONFIGS, type LayerId } from "../../types/layers";
import { LAND_LAYER_CONFIGS } from "../../types/landLayers";
import type { AssertComplete } from "../../types/layerRegistry";

/* ── Layer tooltip data ──────────────────────────────────────────────────── */

/** Non-translatable metadata only — descriptions are in panels.json under tooltip.descriptions.<id> */
export interface LayerTooltipMeta {
  source: string;
  /** Authoritative URL for the source — DOI when one exists, otherwise the publishing
   * organisation's canonical portal. Rendered as a clickable "↗" link on the source line.
   * Omit only for derived/composite layers with no single canonical citation. */
  sourceUrl?: string;
  /** When set, the tooltip's source line opens OUR in-app LegendPanel "Layers" tab
   * (scrolled to this layer id) instead of an external sourceUrl link. Use for layers
   * whose methodology deserves an in-app write-up rather than pointing offsite.
   * Mutually exclusive with sourceUrl — set at most one. */
  legendRef?: LayerId;
  pairsWith: LayerId[];
}

/** Stable id→label lookup built from the existing config arrays. */
export const LAYER_LABEL_MAP: Record<string, string> = Object.fromEntries(
  [...LAYER_CONFIGS, ...LAND_LAYER_CONFIGS].map(l => [l.id, l.label]),
);

/** Convert dash-separated layer id to camelCase for panels.json key lookup. */
export function dashToCamel(s: string): string {
  return s.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
}

export const LAYER_TOOLTIPS_META = {
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
  "ocean-carbon": {
    source: "GLODAP v2.2016b Mapped Climatology (GEOMAR / NOAA NCEI)",
    sourceUrl: "https://glodap.info/index.php/mapped-data-product/",
    pairsWith: ["woa-climatology", "oxygen-deox", "argo"],
  },
  "ocean-acidification": {
    source: "GLODAP v2.2016b OmegaA/OmegaC (Lauvset 2016; Key 2015) — horizon depth platform-derived",
    legendRef: "ocean-acidification",
    pairsWith: ["marine-carbon", "vme-suitability", "argo"],
  },
  "ocean-co2-surface": {
    source: "SOCAT v2026 decadal gridded (NCEI 0315110)",
    sourceUrl: "https://socat.info/index.php/version-2026/",
    pairsWith: ["ocean-carbon", "woa-climatology", "argo"],
  },
  "marine-carbon": {
    source: "GLODAP v2.2016b + SOCAT v2026 + ISAS20 + WOA23",
    sourceUrl: "https://www.glodap.info",
    // Companions that EXTEND the carbon picture — NOT ocean-carbon/co2/oxygen,
    // which are already merged into this unified layer.
    pairsWith: ["arctic-rivers", "memento", "methane-seeps"],
  },
  "vme-suitability": {
    source: "Modeled (MaxEnt/elapid): NOAA DSCRTP coral occurrences + GEBCO/WOA23/ISAS/GLODAP/substrate predictors",
    legendRef: "vme-suitability",
    pairsWith: ["marine-carbon", "biodiversity-hotspots", "methane-seeps"],
  },
  "coral-acid-exposure": {
    source: "Platform-derived: VME MaxEnt suitability × reconstructed aragonite saturation horizons (GLODAP v2.2016b, via PyCO2SYS)",
    sourceUrl: "https://www.glodap.info/",
    pairsWith: ["vme-suitability", "ocean-acidification"],
  },
  "cumulative-human-impact": {
    source: "NCEAS / Halpern et al. 2025, Science",
    sourceUrl: "https://doi.org/10.1126/science.adv2906",
    pairsWith: ["vme-suitability", "ocean-acidification", "contracts"],
  },
  "oxygen-deox": {
    source: "Ifremer/LOPS — ISAS20 BGC-Argo dissolved oxygen (SEANOE 10.17882/52367, CC-BY 4.0); baseline NOAA NCEI WOA23",
    sourceUrl: "https://doi.org/10.17882/52367",
    pairsWith: ["woa-climatology", "argo", "ocean-currents"],
  },
  "wod-oxygen": {
    source: "NOAA NCEI — World Ocean Database 2023 (WOD23)",
    sourceUrl: "https://www.ncei.noaa.gov/products/world-ocean-database",
    pairsWith: ["oxygen-deox", "woa-climatology", "argo"],
  },
  "memento": {
    source: "GEOMAR Helmholtz Centre for Ocean Research Kiel — MEMENTO database of marine CH₄ and N₂O",
    sourceUrl: "https://memento.geomar.de",
    pairsWith: ["wod-oxygen", "argo", "woa-climatology"],
  },
  "geotraces": {
    source: "GEOTRACES IDP2025 — NERC EDS BODC (doi:10.5285/42c92148…), CC-BY 4.0",
    sourceUrl: "https://www.bodc.ac.uk/geotraces/data/dp/",
    pairsWith: ["memento", "wod-oxygen", "oxygen-deox"],
  },
  "mosaic-sediment": {
    source: "MOSAIC v.019 — mosaicprd.ethz.ch/api",
    sourceUrl: "https://mosaic.ethz.ch/",
    pairsWith: ["arctic-sediment-carbon", "geotraces"],
  },
  "hydrothermal-vents": {
    source: "Beaulieu, Stace E; Szafrański, Kamil M (2020): InterRidge Global Database of Active Submarine Hydrothermal Vent Fields Version 3.4 [dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.917894",
    sourceUrl: "https://doi.org/10.1594/PANGAEA.917894",
    pairsWith: ["contracts", "biodiversity-hotspots", "chess"],
  },
  "argo": {
    source: "Argo Programme (international) — accessed via Argovis (CU Boulder)",
    sourceUrl: "https://argo.ucsd.edu/",
    pairsWith: ["contracts", "biodiversity-hotspots", "oceansites"],
  },
  "biodiversity-hotspots": {
    source: "Ocean Biodiversity Information System (OBIS) — IOC-UNESCO",
    sourceUrl: "https://obis.org/",
    pairsWith: ["contracts", "hydrothermal-vents", "seamounts"],
  },
  "noise-risk": {
    source: "Derived layer — modelled from contract boundaries (no external citation)",
    pairsWith: ["contracts", "biodiversity-hotspots", "argo"],
  },
  "seamounts": {
    source: "Yesson, Chris; Letessier, Tom B; Nimmo-Smith, Alex; Hosegood, Phil; Brierley, Andrew S; Hardouin, Marie; Proud, Roland (2020): List of seamounts in the world oceans - An update [dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.921688",
    sourceUrl: "https://doi.org/10.1594/PANGAEA.921688",
    pairsWith: ["contracts", "biodiversity-hotspots", "hydrothermal-vents"],
  },
  "reserved-areas": {
    source: "International Seabed Authority — DeepData",
    sourceUrl: "https://www.isa.org.jm/exploration-contracts/",
    pairsWith: ["contracts", "apeis"],
  },
  "relinquished-areas": {
    source: "International Seabed Authority — DeepData",
    sourceUrl: "https://www.isa.org.jm/exploration-contracts/",
    pairsWith: ["contracts", "reserved-areas"],
  },
  "apeis": {
    source: "International Seabed Authority — DeepData",
    sourceUrl: "https://isa.org.jm/environmental-management-plan-for-the-clarion-clipperton-zone/",
    pairsWith: ["contracts", "biodiversity-hotspots", "reserved-areas"],
  },
  "eez": {
    source: "Flanders Marine Institute (VLIZ) — World EEZ v12 via MarineRegions.org",
    sourceUrl: "https://www.marineregions.org/eez.php",
    pairsWith: ["contracts"],
  },
  "protected-marine-sites": {
    source: "UNESCO World Heritage Marine Programme",
    sourceUrl: "https://whc.unesco.org/en/marine-programme/",
    pairsWith: ["contracts", "biodiversity-hotspots", "eez"],
  },
  "oceansites": {
    source: "OceanSITES — Global Network of Open Ocean Time-Series Stations",
    sourceUrl: "https://www.oceansites.org/",
    pairsWith: ["contracts", "argo", "onc"],
  },
  "onc": {
    source: "Ocean Networks Canada — Oceans 3.0",
    sourceUrl: "https://data.oceannetworks.ca/",
    pairsWith: ["oceansites", "hydrothermal-vents", "seamounts"],
  },
  "chess": {
    source: "Ramirez-Llodra E (2025). ChEssBase v1.0. Flanders Marine Institute, accessed via GBIF.org.",
    sourceUrl: "https://doi.org/10.15468/6v6ug8",
    pairsWith: ["hydrothermal-vents", "contracts", "seamounts"],
  },
  "submarine-cables": {
    source: "EMODnet Human Activities (7 layers: NVE, BSH, Rijkswaterstaat, UK, SIG — EC DG MARE, CC BY 4.0) + NOAA Marine Cadastre + NZ LINZ + AU ACMA + ONC + OOI",
    sourceUrl: "https://emodnet.ec.europa.eu/en/human-activities",
    pairsWith: ["contracts", "eez", "onc", "onc-instruments"],
  },
  "onc-instruments": {
    source: "Ocean Networks Canada — Oceans 3.0 instrument registry",
    sourceUrl: "https://data.oceannetworks.ca/DeviceListing",
    pairsWith: ["onc", "submarine-cables", "hydrothermal-vents"],
  },
  "hydrophone-stations": {
    source: "OOI + IMOS + MBARI MARS + AWI PALAOA + OBSEA + KM3NeT + NOAA Passive Acoustic Archive (NRS, SanctSound, NEFSC, PIFSC, SEFSC, ONMS, ADEON, BOEM, AEON, Navy, NPS, JASCO, FRAM, CSI, IOOS) + SAMBAH + CTBTO IMS — 23 networks",
    sourceUrl: "https://oceanobservatories.org/",
    pairsWith: ["onc", "onc-instruments", "noise-risk"],
  },
  "marhys": {
    source: "MARHYS Database 4.0 — Diehl & Bach (2024), PANGAEA (CC-BY-4.0). Cite the base publication alongside it: Diehl & Bach (2020), doi:10.1029/2020GC009385",
    sourceUrl: "https://doi.org/10.1594/PANGAEA.972999",
    pairsWith: ["hydrothermal-vents", "chess", "methane-seeps"],
  },
  "ports": {
    source: "EMODnet Human Activities — Port locations (EC DG MARE, CC BY 4.0)",
    sourceUrl: "https://emodnet.ec.europa.eu/en/human-activities",
    pairsWith: ["contracts", "submarine-cables"],
  },
  "tectonic-plates": {
    source: "Bird (2003) plate model — packaged by Hugo Ahlenius / Nordpil",
    sourceUrl: "https://github.com/fraxen/tectonicplates",
    pairsWith: ["hydrothermal-vents", "seamounts", "contracts"],
  },
  "monitoring-density": {
    source: "Derived from OBIS, ChEssBase, Argo, OceanSITES, ONC, WOD, PANGAEA, BCO-DMO, NOAA, OBIS-SEAMAP, CCHDO, SIO-BIC museum specimens — aggregated internally",
    pairsWith: ["contracts", "reserved-areas", "argo"],
  },
  "deepdata-stations": {
    source: "ISA DeepData (data.isa.org.jm) via OBIS-hosted DwC archives — platform-aggregated analysis, not raw contractor records",
    sourceUrl: "https://datasets.obis.org/hosted/isa/index.html",
    pairsWith: ["contracts", "monitoring-density", "biodiversity-hotspots"],
  },
  // ── Land ──
  "mining-footprints": {
    source: "Maus, Victor; da Silva, Dieison M; Gutschlhofer, Jakob; da Rosa, Robson; Giljum, Stefan; Gass, Sidnei L B; Luckeneder, Sebastian; Lieber, Mirko; McCallum, Ian (2022): Global-scale mining polygons (Version 2) [dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.942325",
    sourceUrl: "https://doi.org/10.1594/PANGAEA.942325",
    pairsWith: ["water-risk", "tailings"],
  },
  "forest-loss": {
    source: "Hansen/UMD/Google/USGS/NASA — distributed via WRI Global Forest Watch",
    sourceUrl: "https://www.globalforestwatch.org/",
    pairsWith: ["mining-footprints", "carbon-flux"],
  },
  "tailings": {
    source: "WAPHA (Hudson-Edwards et al. 2023, Dryad) + Global Tailings Portal — GRID-Arendal / Earthworks / UN Environment",
    sourceUrl: "https://doi.org/10.5061/dryad.j3tx95xmg",
    pairsWith: ["mining-footprints", "landslides"],
  },
  "arctic-rivers": {
    source: "ArcticGRO (Arctic Great Rivers Observatory) + PANGAEA",
    sourceUrl: "https://arcticgreatrivers.org/data/",
    pairsWith: ["surface-water", "mining-footprints", "water-risk"],
  },
  "arctic-catchments": {
    source: "ARCADE v1 — Pan-Arctic catchment database (DataVerse NL)",
    sourceUrl: "https://doi.org/10.34894/U9HSPV",
    pairsWith: ["arctic-rivers", "ocean-carbon", "marine-carbon"],
  },
  "arctic-sediment-carbon": {
    source: "CASCADE v2 — Martens et al. 2021, ESSD 13:2561 (Bolin Centre, CC-BY 4.0)",
    sourceUrl: "https://doi.org/10.17043/cascade-2",
    pairsWith: ["arctic-rivers", "arctic-catchments", "marine-carbon"],
  },
  "sios-svalbard": {
    source: "sios-svalbard.org/rest/stations/data.json",
    sourceUrl: "https://sios-svalbard.org/metsis/search",
    pairsWith: ["arctic-rivers", "argo", "woa-climatology"],
  },
  "methane-seeps": {
    source: "SEAFLEA Observed Database (NRL / NOAA NCEI), Phrampus et al. 2020",
    sourceUrl: "https://doi.org/10.1029/2019GC008747",
    pairsWith: ["memento", "hydrothermal-vents", "chess"],
  },
  "permafrost-thaw": {
    source: "Alaska Permafrost Thaw Database v2.0.0 — Webb et al. 2026 (ESSD 18:3147)",
    sourceUrl: "https://doi.org/10.5194/essd-18-3147-2026",
    pairsWith: ["arctic-rivers", "arctic-catchments", "arctic-sediment-carbon"],
  },
  "fires": {
    source: "NASA LANCE / EOSDIS — Fire Information for Resource Management System (FIRMS)",
    sourceUrl: "https://firms.modaps.eosdis.nasa.gov/",
    pairsWith: ["mining-footprints", "air-quality", "carbon-flux"],
  },
  "air-quality": {
    source: "OpenAQ — global open air-quality data platform",
    sourceUrl: "https://openaq.org/",
    pairsWith: ["mining-footprints", "fires", "tailings"],
  },
  "landslides": {
    source: "NASA Goddard — Cooperative Open Online Landslide Repository (COOLR)",
    sourceUrl: "https://gpm.nasa.gov/landslides/",
    pairsWith: ["tailings", "mining-footprints", "surface-water"],
  },
  "surface-water": {
    source: "Pekel et al. (2016). Joint Research Centre / European Commission — Global Surface Water Explorer",
    sourceUrl: "https://global-surface-water.appspot.com/",
    pairsWith: ["mining-footprints", "dams", "water-risk"],
  },
  "dams": {
    source: "Global Dam Watch — international consortium of dam-research organisations",
    sourceUrl: "https://www.globaldamwatch.org/",
    pairsWith: ["mining-footprints", "surface-water", "tailings"],
  },
  "carbon-flux": {
    source: "Harris et al. (2021), WRI / Global Forest Watch — Forest Greenhouse Gas Emissions",
    sourceUrl: "https://www.globalforestwatch.org/",
    pairsWith: ["forest-loss", "mining-footprints"],
  },
  "soil-carbon": {
    source: "ISRIC — SoilGrids, soc_0-5cm_mean",
    sourceUrl: "https://soilgrids.org/",
    pairsWith: ["mining-footprints", "carbon-flux", "forest-loss"],
  },
  "water-risk": {
    source: "World Resources Institute — Aqueduct 4.0",
    sourceUrl: "https://www.wri.org/aqueduct",
    pairsWith: ["mining-footprints", "tailings", "surface-water"],
  },
  "vessel-events": {
    source: "Sentinel-1 SAR (Copernicus Data Space Ecosystem) × AISStream.io",
    sourceUrl: "https://dataspace.copernicus.eu/",
    pairsWith: ["contracts", "apeis", "protected-marine-sites"],
  },
  "offshore-activities": {
    source: "EMODnet Human Activities (EU EEZ blocks — EC DG MARE, CC BY 4.0) + national petroleum/seabed registries (BOEM, Crown Estate, Sodir, NSTA, ANH, CNH, NOPTA, NZP&M, ANP, ESDM, PASA, CNSOPB/C-NLOPB, GEUS/DEA, MRA PNG, MME, SBMA, MEEI/IMA, Petroleum Commission Ghana, PMP, PAD/GSI, PERUPETRO).",
    sourceUrl: "https://emodnet.ec.europa.eu/en/human-activities",
    pairsWith: ["eez", "contracts", "protected-marine-sites"],
  },
  "seabed-substrate": {
    source: "Dutkiewicz et al. 2015, Geology (doi:10.1130/G36883.1) · EarthByte",
    sourceUrl: "https://www.earthbyte.org/seafloor-lithology-of-the-ocean-basins/",
    pairsWith: ["seamounts", "hydrothermal-vents", "contracts"],
  },
  "ais-live": {
    source: "AISStream.io — live AIS broadcast relay",
    sourceUrl: "https://aisstream.io/",
    pairsWith: ["vessel-events", "contracts", "protected-marine-sites"],
  },
  "bathymetry": {
    source: "GEBCO Compilation Group — wms.gebco.net (GEBCO_LATEST grid)",
    sourceUrl: "https://www.gebco.net/data_and_products/gridded_bathymetry_data/",
    pairsWith: ["seamounts", "hydrothermal-vents", "contracts"],
  },
} as const satisfies Record<LayerId, LayerTooltipMeta>;

// Every layer gets a hover tooltip. There is no defensible reason for a row in
// the left menu to explain nothing, so this registry has no opt-out list.
export const _tooltipsAreComplete: AssertComplete<
  keyof typeof LAYER_TOOLTIPS_META,
  never
> = true;
