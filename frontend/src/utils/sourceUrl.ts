// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Per-feature source attribution registry.
 *
 * Goal: every object on the map links somewhere — directly to its record at the
 * source when the source has a stable per-feature URL, otherwise to the
 * publishing organisation's homepage. The decision is centralised here so:
 *   1. URL changes happen in one place
 *   2. all panels render attribution consistently
 *   3. it is auditable that no layer is "orphaned" without source info
 *
 * Add a new layer: drop a SourceEntry into LAYER_SOURCES keyed by a stable
 * logical name, then call sourceLinkFor("<name>", properties) from the panel.
 * The logical key is intentionally NOT the deck.gl layer id — it groups
 * variants (e.g. mining-footprints + mining-footprints-mvt → "mining-footprint").
 */
export interface SourceLink {
  /** Display name of the publisher / organisation. */
  org: string;
  /** Authoritative URL — per-feature deep link when available, otherwise org homepage. */
  url: string;
  /** Whether the URL is a per-feature page (true) or just the homepage (false). */
  isDeepLink: boolean;
}

type Properties = Record<string, unknown>;

interface SourceEntry {
  org: string;
  /** Always-on homepage / portal URL. */
  homepage: string;
  /** Optional builder — return null to fall back to homepage. */
  perFeature?: (p: Properties) => string | null;
}

/** Build a search-friendly slug from a free-text name (lowercase, dashes). */
function slugify(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Per-source homepage table for the offshore-activities layer (16 regulators). */
const OFFSHORE_SOURCE_HOMEPAGES: Record<string, { org: string; url: string }> = {
  emodnet:               { org: "EMODnet Human Activities",   url: "https://emodnet.ec.europa.eu/en/human-activities" },
  boem:                  { org: "BOEM (USA)",                 url: "https://www.boem.gov/oil-gas-energy/leasing" },
  crown_estate:          { org: "The Crown Estate (UK)",      url: "https://www.thecrownestate.co.uk/our-business/marine/" },
  crown_estate_scotland: { org: "Crown Estate Scotland",      url: "https://www.crownestatescotland.com/scotlands-property/offshore-wind" },
  nopta:                 { org: "NOPTA (Australia)",          url: "https://www.nopta.gov.au/" },
  nzpam:                 { org: "NZP&M (New Zealand)",        url: "https://www.nzpam.govt.nz/" },
  anp:                   { org: "ANP (Brazil)",               url: "https://www.gov.br/anp/pt-br" },
  sodir:                 { org: "Sodir (Norway)",             url: "https://www.sodir.no/en/" },
  nsta:                  { org: "NSTA (UK North Sea)",        url: "https://www.nstauthority.co.uk/" },
  cnh:                   { org: "CNH (Mexico)",               url: "https://www.gob.mx/cnh" },
  esdm:                  { org: "ESDM (Indonesia)",           url: "https://migas.esdm.go.id/" },
  pasa:                  { org: "PASA (South Africa)",        url: "https://www.pasa.org.za/" },
  anh_co:                { org: "ANH (Colombia)",             url: "https://www.anh.gov.co/" },
  mra_png:               { org: "MRA Papua New Guinea",       url: "https://www.mra.gov.pg/" },
  mme_nam:               { org: "MME Namibia",                url: "https://www.mme.gov.na/" },
  sbma_ck:               { org: "SBMA Cook Islands",          url: "https://www.sbma.gov.ck/" },
};

const LAYER_SOURCES: Record<string, SourceEntry> = {
  // ── ISA layers ─────────────────────────────────────────────────────────────
  "isa-contract": {
    org: "International Seabed Authority — DeepData",
    homepage: "https://www.isa.org.jm/exploration-contracts/",
  },
  "isa-apei": {
    org: "International Seabed Authority",
    homepage: "https://www.isa.org.jm/protection-of-the-marine-environment/",
  },
  "isa-relinquished": {
    org: "International Seabed Authority",
    homepage: "https://isa.org.jm/exploration-contracts/exploration-areas/",
  },
  "isa-reserved": {
    org: "International Seabed Authority",
    homepage: "https://www.isa.org.jm/exploration-contracts/reserved-areas/",
  },

  // ── Biology / biodiversity ─────────────────────────────────────────────────
  "obis-occurrence": {
    // Canonical OBIS Occurrence Data citation:
    // OBIS (25 March 2025). Intergovernmental Oceanographic Commission of UNESCO.
    // https://doi.org/10.25607/obis.occurrence.b89117cd
    org: "OBIS — Ocean Biodiversity Information System (UNESCO/IOC) — DOI: 10.25607/obis.occurrence.b89117cd",
    homepage: "https://doi.org/10.25607/obis.occurrence.b89117cd",
    perFeature: (p) => {
      const id = p.obis_id ?? p.id;
      return typeof id === "string" && id.length > 0 ? `https://obis.org/occurrence/${id}` : null;
    },
  },
  "interridge-vent": {
    org: "InterRidge Vents Database (Beaulieu & Szafrański 2020 / PANGAEA)",
    // vents-data.interridge.org returns 502/down — point at the persistent
    // PANGAEA DOI for the dataset itself, which is the canonical citation.
    homepage: "https://doi.org/10.1594/PANGAEA.917894",
  },
  "chess-species": {
    org: "ChEssBase (Ramirez-Llodra 2025 / VLIZ via GBIF)",
    homepage: "https://www.gbif.org/dataset/dc5abc9f-84d5-4046-a3ef-9ab24ae53756",
  },
  "sio-bic": {
    org: "SIO Benthic Invertebrate Collection (UC San Diego)",
    homepage: "https://scripps.ucsd.edu/benthic-invertebrate-collection",
    // Deep-link pattern: Django-style /catalog/{HigherTaxaCode}{Catalog#}/
    // Confirmed live 2026-05-04 against sioapps.ucsd.edu/collections/bi/catalog/A1092/
    perFeature: (p) => {
      const tax = p.higher_taxa_code ?? p.higherTaxaCode;
      const cat = p.catalog_no ?? p.catalogNo;
      if (typeof tax !== "string" || typeof cat !== "string") return null;
      if (tax.length === 0 || cat.length === 0) return null;
      return `https://sioapps.ucsd.edu/collections/bi/catalog/${encodeURIComponent(tax + cat)}/`;
    },
  },
  "yesson-seamounts": {
    org: "Yesson et al. 2020 — PANGAEA",
    homepage: "https://doi.org/10.1594/PANGAEA.921688",
  },

  // ── Geographic / regulatory ────────────────────────────────────────────────
  "marineregions-eez": {
    org: "MarineRegions.org — World EEZ v12 (VLIZ)",
    homepage: "https://www.marineregions.org/eez.php",
    perFeature: (p) => {
      const mrgid = p.mrgid ?? p.MRGID;
      return typeof mrgid === "number" || typeof mrgid === "string"
        ? `https://www.marineregions.org/eezdetails.php?mrgid=${mrgid}`
        : null;
    },
  },
  "unesco-mab": {
    org: "UNESCO World Heritage Marine Programme via MarineRegions.org",
    homepage: "https://whc.unesco.org/en/marine-programme/",
    // protected_marine_sites.site_id is the MarineRegions MRGID (the WFS we
    // sync from is hosted by MarineRegions/VLIZ), NOT the UNESCO inscription
    // number — Great Barrier Reef has site_id=26847 here but inscription 154
    // on whc.unesco.org. Link to the MarineRegions gazetteer where the same
    // ID resolves cleanly to a per-site page.
    perFeature: (p) => {
      const id = p.site_id ?? p.mrgid ?? p.MRGID;
      return id != null
        ? `https://www.marineregions.org/gazetteer.php?p=details&id=${encodeURIComponent(String(id))}`
        : null;
    },
  },

  // ── Observatories / sensors ────────────────────────────────────────────────
  "argo-float": {
    // Data reaches us via the Argovis pipeline, but the authoritative per-float
    // page is Euro-Argo Fleet Monitoring, keyed by WMO number (= our platform_id).
    // The old Argovis /plots/argo?platform= route no longer resolves to a float.
    org: "Argo Programme — float page via Euro-Argo Fleet Monitoring",
    homepage: "https://argo.ucsd.edu/",
    perFeature: (p) => {
      const platform = p.platform_id ?? p.platformId ?? p.wmo;
      return platform != null
        ? `https://fleetmonitoring.euro-argo.eu/float/${encodeURIComponent(String(platform))}`
        : null;
    },
  },
  "oceansites-platform": {
    org: "OceanSITES via OceanOPS",
    // www.oceansites.org has ongoing TLS/DNS issues — link to the OceanOPS
    // OceanSITES landing page instead, which mirrors the network info.
    homepage: "https://www.ocean-ops.org/oceansites/",
    // No working per-platform URL: OceanOPS `?ref=` is silently ignored
    // (the dashboard always loads the global view), and OceanSITES doesn't
    // expose per-mooring HTML pages — only NetCDF data files at the GDAC.
  },
  "onc-location": {
    org: "Ocean Networks Canada — Oceans 3.0",
    homepage: "https://www.oceannetworks.ca/",
    perFeature: (p) => {
      const code = p.location_code ?? p.locationCode;
      return typeof code === "string" && code.length > 0
        ? `https://data.oceannetworks.ca/DataSearch?location=${encodeURIComponent(code)}`
        : null;
    },
  },
  "onc-instrument": {
    org: "Ocean Networks Canada — Oceans 3.0",
    homepage: "https://www.oceannetworks.ca/",
    perFeature: (p) => {
      const device = p.device_code ?? p.deviceCode;
      return typeof device === "string" && device.length > 0
        ? `https://data.oceannetworks.ca/DeviceListing?DeviceCode=${encodeURIComponent(device)}`
        : null;
    },
  },

  // ── Cables ─────────────────────────────────────────────────────────────────
  "emodnet-cables": {
    org: "EMODnet Human Activities",
    homepage: "https://emodnet.ec.europa.eu/en/human-activities",
  },
  "onc-cables": {
    org: "Ocean Networks Canada — observatory cable network",
    homepage: "https://www.oceannetworks.ca/observatories/",
  },
  "ooi-cables": {
    org: "OOI Regional Cabled Array",
    homepage: "https://github.com/oceanobservatories/asset-management",
  },
  "noaa-cables": {
    org: "NOAA Marine Cadastre (NOAA / BOEM)",
    homepage: "https://marinecadastre.gov/",
  },
  "nz-cables": {
    org: "LINZ NZ Hydrographic",
    homepage: "https://data.linz.govt.nz/layer/51643",
  },
  "au-cables": {
    org: "ACMA / Geoscience Australia (AODN)",
    homepage: "https://www.cmar.csiro.au/geoserver/web/",
  },

  // ── Misc geophysical ───────────────────────────────────────────────────────
  "tayljordan-ports": {
    org: "tayljordan/ports (3,898 global ports)",
    homepage: "https://github.com/tayljordan/ports",
  },
  "bird-tectonic": {
    org: "Bird (2003) — AGU, Geochem. Geophys. Geosyst.",
    homepage: "https://doi.org/10.1029/2001GC000252",
  },
  "cmems-plume": {
    org: "Copernicus Marine Service (CMEMS)",
    homepage: "https://marine.copernicus.eu/",
  },

  // ── Land ───────────────────────────────────────────────────────────────────
  "maus-mining-footprint": {
    // Per PANGAEA citation compliance request (Lars Möller, 2026-05-04), point at
    // the persistent PANGAEA DOI rather than the Zenodo mirror. Full citation:
    // Maus, V. et al. (2022): Global-scale mining polygons (Version 2) [dataset].
    // PANGAEA, https://doi.org/10.1594/PANGAEA.942325
    org: "Maus, V. et al. (2022) Global-scale mining polygons (Version 2) — PANGAEA",
    homepage: "https://doi.org/10.1594/PANGAEA.942325",
  },
  "wapha-tsf": {
    // The tailings-dam base layer is WAPHA, NOT Maus et al. Distinct authors,
    // distinct dataset, distinct DOI. Until 2026-07 every non-GRID dam was
    // attributed to the Maus mining-polygon DOI.
    // Macklin, M.G., Thomas, C.J., Mudbhatkal, A. et al. (2023), Science 381:1345.
    org: "Hudson-Edwards, K. et al. (2023) WAPHA global metal mines database — Dryad",
    homepage: "https://doi.org/10.5061/dryad.j3tx95xmg",
  },
  // "kba" removed 2026-09-03 alongside the layer withdrawal (KbaPanel.tsx,
  // its only caller, is gone too).
  // Two sources in one layer, and they are not interchangeable. The base
  // compilation is WAPHA (Hudson-Edwards et al. 2023, CC0 via Dryad); the
  // Global Tailings Portal rows are company disclosures under GRID-Arendal's
  // own terms. Rows carry `data_source` — 'wapha', 'grid' or 'grid-enriched' —
  // so send each row to the source that actually holds it. A WAPHA row searched
  // on the portal finds nothing: WAPHA publishes one attribute, and it is not
  // the portal's facility_name.
  "tailings": {
    org: "Hudson-Edwards, K. et al. (2023) WAPHA — Dryad, with Global Tailings Portal (GRID-Arendal) disclosures",
    homepage: "https://doi.org/10.5061/dryad.j3tx95xmg",
    perFeature: (p) => {
      const src = typeof p.data_source === "string" ? p.data_source : "";
      if (src === "wapha") return "https://doi.org/10.5061/dryad.j3tx95xmg";
      // `dam_name` is what the endpoint actually returns. It asked for
      // `facility_name ?? name` before, and the tailings properties carry
      // neither — so every row fell through to null and the layer had no
      // per-feature link at all, silently.
      const name = p.dam_name ?? p.mine_name;
      return typeof name === "string" && name.length > 0
        ? `https://tailing.grida.no/?search=${encodeURIComponent(name)}`
        : "https://tailing.grida.no/";
    },
  },
  "firms": {
    org: "NASA FIRMS (VIIRS: Suomi-NPP, NOAA-20, NOAA-21)",
    homepage: "https://firms.modaps.eosdis.nasa.gov/",
  },
  "openaq": {
    org: "OpenAQ v3",
    homepage: "https://openaq.org/",
    // Backend property is `location_id` (the OpenAQ location ID, not our
    // local serial PK). Don't fall back to `p.id` — that would link to a
    // random unrelated OpenAQ station.
    perFeature: (p) => {
      const id = p.location_id ?? p.locationId;
      return id != null
        ? `https://explore.openaq.org/locations/${encodeURIComponent(String(id))}`
        : null;
    },
  },
  "coolr-landslides": {
    org: "NASA COOLR / Goddard Space Flight Center",
    homepage: "https://gpm.nasa.gov/landslides/",
  },
  "global-dam-watch": {
    org: "Global Dam Watch",
    homepage: "https://www.globaldamwatch.org/",
  },
  "jrc-surface-water": {
    org: "JRC / European Commission — Pekel et al. 2016",
    homepage: "https://global-surface-water.appspot.com/",
  },
  "wri-aqueduct": {
    org: "WRI Aqueduct 4.0",
    homepage: "https://www.wri.org/aqueduct",
  },
  "usgs-earthquake": {
    org: "USGS Earthquake Hazards Program",
    homepage: "https://earthquake.usgs.gov/",
    perFeature: (p) => {
      const id = p.usgs_id ?? p.id ?? p.eventId;
      return typeof id === "string" && id.length > 0
        ? `https://earthquake.usgs.gov/earthquakes/eventpage/${id}`
        : null;
    },
  },
};

/**
 * Look up the best source link for a feature.
 *
 * @param key  Logical source key (e.g. "tailings", "obis-occurrence"), NOT the
 *             deck.gl layer id — see LAYER_SOURCES for the full registry.
 * @param p    Feature properties (used to build per-feature deep links).
 * @returns    SourceLink, or null if the key is unknown.
 */
export function sourceLinkFor(key: string, p: Properties = {}): SourceLink | null {
  const entry = LAYER_SOURCES[key];
  if (!entry) return null;
  const deep = entry.perFeature?.(p) ?? null;
  return {
    org: entry.org,
    url: deep ?? entry.homepage,
    isDeepLink: deep != null,
  };
}

/**
 * Resolve the source link for an offshore-activities feature based on its
 * `source` property + optional per-feature `portal_url` (already returned by
 * the by-id endpoint for many sources). Falls back to org homepage when no
 * per-feature URL exists.
 */
export function offshoreSourceLink(p: Properties): SourceLink | null {
  const source = typeof p.source === "string" ? p.source : "";
  const meta = OFFSHORE_SOURCE_HOMEPAGES[source];
  if (!meta) return null;
  const portal = typeof p.portal_url === "string" && p.portal_url.length > 0 ? p.portal_url : null;
  return {
    org: meta.org,
    url: portal ?? meta.url,
    isDeepLink: portal != null,
  };
}

/** Used in tests / as documentation that all keys are typed correctly. */
export type SourceKey = keyof typeof LAYER_SOURCES;

// Suppress unused-import warning when slugify isn't referenced by perFeature
// builders in a given build — kept exported via this no-op so future builders
// can use it for slug-style lookups.
export const _slugify = slugify;
