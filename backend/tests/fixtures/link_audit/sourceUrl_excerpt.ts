const OFFSHORE_SOURCE_HOMEPAGES: Record<string, { org: string; url: string }> = {
  emodnet:               { org: "EMODnet Human Activities",   url: "https://emodnet.ec.europa.eu/en/human-activities" },
  boem:                  { org: "BOEM (USA)",                 url: "https://www.boem.gov/oil-gas-energy/leasing/lease-information" },
  crown_estate:          { org: "The Crown Estate (UK)",      url: "https://www.thecrownestate.co.uk/our-business/marine/" },
};

const LAYER_SOURCES: Record<string, SourceEntry> = {
  // ── ISA layers ─────────────────────────────────────────────────────────────
  "isa-contract": {
    org: "International Seabed Authority — DeepData",
    homepage: "https://www.isa.org.jm/exploration-contracts/",
  },
  "interridge-vent": {
    org: "InterRidge Vents Database (Beaulieu & Szafrański 2020 / PANGAEA)",
    // vents-data.interridge.org returns 502/down — point at the persistent
    // PANGAEA DOI for the dataset itself, which is the canonical citation.
    homepage: "https://doi.org/10.1594/PANGAEA.917894",
  },
};

const MORE_SOURCES: Record<string, SourceEntry> = {
  "obis-occurrence": {
    org: "OBIS — Ocean Biodiversity Information System (UNESCO/IOC)",
    homepage: "https://doi.org/10.25607/obis.occurrence.b89117cd",
    perFeature: (p) => {
      const id = p.obis_id ?? p.id;
      return typeof id === "string" && id.length > 0 ? `https://obis.org/occurrence/${id}` : null;
    },
  },
  "argo-float": {
    org: "Argo Programme — float page via Euro-Argo Fleet Monitoring",
    homepage: "https://argo.ucsd.edu/",
    perFeature: (p) => {
      const platform = p.platform_id ?? p.platformId ?? p.wmo;
      return platform != null
        ? `https://fleetmonitoring.euro-argo.eu/float/${encodeURIComponent(String(platform))}`
        : null;
    },
  },
};
