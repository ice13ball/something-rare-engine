# Data sources and licences

**Almost no data ships in this repository, and the exception is named here rather than
glossed.** Beyond the source code, `backend/tests/fixtures/` holds ~1.1 MB of **real**
upstream excerpts across 13 sources — among them GEOTRACES seawater rows, ONC ADCP
profiles, and GLODAP and SOCAT NetCDF slices. They exist so parsers are tested against
the shapes they actually meet, and they remain under their upstream terms.

**Four fixture sets were deliberately withheld from this package**, because their upstream
terms do not permit redistribution or do not say: MEMENTO (contributors may include
unpublished data; the terms ask that the contributing scientist be contacted before results
are published), seabed lithology (CC-BY-NC 4.0, non-commercial only), MOSAiC sediment and
Arctic rivers (no licence stated upstream). The parsers for those four are in the source and
their tests skip without the fixtures. Every one of them is listed in the source map below —
withheld from the package is not the same as unused by the platform.

Every map layer is fetched at run time from its upstream provider
and stored in the platform's own PostgreSQL/PostGIS database. Each dataset remains under the
**licence of its upstream provider** — the AGPL-3.0 licence on this code does **not** relicense
any data.

The platform stores upstream provenance verbatim and never alters or derives source values.
Provenance (source, URL, licence, citation, caveats) travels with the data through the panels
and the Area Export tool. **If a value looks wrong, verify it at the upstream `source_url`,
not here.**

This file is the human-readable licence map. It is representative of the licence-notable
sources, not an exhaustive list of all ~110 sync sources; the authoritative per-source
provenance lives in `backend/services/export_registry.py` and the live legend.

---

## ⚠️ Non-commercial / restricted-use sources

These sources are **not** freely reusable for commercial purposes. Anyone deploying a
derivative must re-check these before any monetised use.

| Source | Layer(s) | Licence | Note |
|---|---|---|---|
| **Dutkiewicz et al. 2015** — global seabed lithology (EarthByte) | `seabed-lithology` **and, as a model predictor,** `vme-suitability` → `coral-acid-exposure` | **CC-BY-NC 4.0** | Non-commercial. This lineage runs *through* the VME suitability model into the coral acidification-exposure layer. The platform is publishable today **only because it is non-monetised.** If this platform, or any fork, is ever put behind a paid tier, this CC-BY-NC lineage must be re-assessed first. |
| **MaxMind GeoLite2** — Country / ASN databases | request-log enrichment in the API-key subsystem (`GEOIP_COUNTRY_DB`, `GEOIP_ASN_DB`) | MaxMind GeoLite2 EULA | **Redistribution is prohibited** by the EULA. The `.mmdb` files are therefore **not** in this repository and must be obtained directly from MaxMind under your own account. Without them the enrichment is simply skipped (`country`/`asn` stay NULL) — nothing else breaks. |
| **InterRidge Vents Database v3.4** (via PANGAEA) | `hydrothermal-vents` | **CC-BY-NC-SA 4.0** | Non-commercial **and** share-alike, confirmed at the dataset's own PANGAEA DOI (doi:10.1594/PANGAEA.917894). Not yet resolved organisationally as of the 2026-09-03 licence audit — re-check before any monetised use. |
| **OBIS-SEAMAP** (Duke University Marine Geospatial Ecology Lab) | `noise-risk` (cetacean-sightings component; the layer also blends ICES and EMODnet Physics data) | Redistribution prohibited without permission | OBIS-SEAMAP's terms of use forbid redistributing data obtained from the portal. `noise-risk` computes an index that includes OBIS-SEAMAP sightings, inheriting the restriction for that component. |
| **MBARI MARS** (Monterey Accelerated Research System) | `hydrophone-stations` (one of 22 passive-acoustic networks aggregated into this layer) | "Internal research activities only" | Per MBARI's VARS data-use policy. Restricts only this one sub-source within the aggregate — the other 21 networks are unaffected individually. |

The platform is **non-commercial**; that is what makes the Dutkiewicz source above
compatible. Note that the **code** is AGPL-3.0, which *does* permit commercial use — the
restrictions in this section come from the data providers and are not affected by the code
licence. Anyone monetising a fork must resolve them independently.

---

## Mandatory-citation sources

Compatible for reuse, but the provider requires a specific citation and/or acknowledgement.
These are carried verbatim in the platform and must be preserved in any derivative.

| Source | Layer(s) | Licence | Required citation / note |
|---|---|---|---|
| **MEMENTO** (GEOMAR marine CH₄/N₂O) | `memento` | Terms of use | Cite **Kock & Bange (2015), *Eos* 96(3), doi:10.1029/2015EO023665** + the verbatim GEOMAR/SOPRAN acknowledgement. **Contributors may include unpublished data — contact the contributing scientist before publishing results.** GEOMAR states data are "freely usable" but does not name a specific open licence — treat "Terms of use" literally, not as a stand-in for e.g. CC-BY. |
| **GLODAP v2.2016b** (interior-ocean carbon) | `ocean-carbon`, `marine-carbon`, `ocean-acidification`, `coral-acid-exposure` | Open, cite | Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093). |
| **SOCAT v2026** (surface CO₂) | `ocean-co2-surface`, `marine-carbon` | CC-BY 4.0 | Bakker et al. 2026 (NCEI Accession 0315110, doi:10.25921/8dba-fr90) + Sabine et al. 2013. |
| **GEOTRACES IDP2025** (trace metals) | `geotraces` | CC-BY 4.0 | BODC-hosted; research-grade. |
| **CASCADE v2** (Arctic sediment carbon) | `arctic-sediment-carbon` | CC-BY 4.0 | doi:10.17043/cascade-2 (Bolin Centre). |
| **WAPHA** (tailings dams base) | `tailings` | Dryad, cite | Hudson-Edwards et al. 2023, doi:10.5061/dryad.j3tx95xmg; companion Macklin et al. 2023 (*Science* 381:1345). **Not Maus et al.** The `tailings` layer also carries GRID-Arendal-sourced enrichment rows (company-disclosed facility data, tailing.grida.no) alongside the WAPHA base; those rows are not covered by the WAPHA/Dryad grant. Several UI-facing labels still attribute the whole layer to "GRID-Arendal / UNEP" — that attribution is wrong for the base data and needs fixing in code, not just here. |
| **Maus et al. 2022** (mining footprints) | `mining-footprints` | CC-BY 4.0 | PANGAEA doi:10.1594/PANGAEA.942325. |
| **NCEAS / Halpern et al. 2025** (cumulative human impact) | `cumulative-human-impact` | **CC0 1.0** | KNB doi:10.5063/F18K77KZ. Public domain — cited voluntarily. |

---

## General source map

| Source | Layer family | Licence / access |
|---|---|---|
| ISA DeepData | ISA concessions, contractor reports | Open (isa.org.jm/deepdata) |
| OBIS Open Data (AWS parquet mirror) | biodiversity occurrences | Open (obis.org) |
| GBIF | biodiversity occurrences | Open, CC-BY / CC0 per dataset (gbif.org) |
| NOAA DSCRTP, MBARI VARS | deep-sea coral/sponge density | Open (NOAA / MBARI) |
| IUCN Red List | biodiversity status | Terms of use (non-redistribution of bulk) |
| WoRMS | taxonomic backbone | Open (marinespecies.org) |
| UNEP-WCMC & IUCN — Protected Planet (WDPA) | ⛔ **withdrawn 2026-09-03** (was: protected areas) | WDPA terms forbid redistribution "through interactive web maps ... that grant users download access" without prior written permission from UNEP-WCMC. Rows remain in the database; the layer is no longer served. |
| BirdLife International / KBA Partnership — Key Biodiversity Areas | ⛔ **withdrawn 2026-09-03** (was: KBAs) | Same redistribution clause as WDPA, plus a separate no-commercial-use clause (verified at keybiodiversityareas.org/termsofservice). Rows remain in the database; the layer is no longer served. |
| MarineRegions.org (VLIZ) — EEZ v12 | `eez`; geometry also underlies `protected-marine-sites` | CC-BY 4.0. VLIZ additionally, non-bindingly, requests that users not host bulk downloads elsewhere and always link back to marineregions.org — noted, not a licence restriction. |
| UNESCO World Heritage Marine Programme + MarineRegions.org | `protected-marine-sites` (50 World Heritage marine sites — **not** WDPA, see `rules/subsystems/tables-that-lie.md`) | Open; UNESCO syndication terms (whc.unesco.org/en/syndication) |
| National offshore-energy regulators (BOEM, Crown Estate, Crown Estate Scotland, NOPTA, NZP&M, ANP, Sodir, NSTA, CNH, ESDM, PASA, ANH, MRA Papua New Guinea, MME Namibia, SBMA Cook Islands) + EMODnet Human Activities | `offshore-activities` | Mixed: EMODnet portion is CC-BY 4.0 (confirmed). The 16 national-regulator feeds are government registries whose individual reuse terms have **not** been verified per-registry — check each before redistribution. |
| JRC Global Surface Water (Pekel et al. 2016) | `surface-water` | CC-BY, conditional: attribution must name both **JRC and Google**, plus cite Pekel et al. 2016 — see global-surface-water.appspot.com/faq |
| _(under review)_ | `forest-loss`, `carbon-flux`, `soil-carbon`, `tectonic-plates`, `mosaic-sediment`, `arctic-rivers`, `ais-live` | **Not stated here yet.** Each of these upstreams either publishes no licence, or publishes terms that do not resolve into one. Rather than print a guess, this file says nothing about them until the maintainer has checked each. Treat these seven layers as unlicensed for reuse until this row is replaced. |
| GEBCO 2024 | bathymetry / confidence | Open, "not for navigation" |
| Copernicus Marine (CMEMS) | ocean currents, plume tracing | Copernicus licence (account required) |
| ESA Copernicus Sentinel-1 (CDSE) | SAR / dark vessels | Copernicus licence (account required) |
| NASA FIRMS | active fires | Open (NASA LANCE) |
| NOAA WOA23 | climatology | Public domain (US Gov) |
| ISAS20 (BGC-Argo) | oxygen | Open |
| Argo | float profiles | Open (Argo programme) |
| EMODnet / NOAA Marine Cadastre / NZ LINZ / AU ACMA / ONC / OOI | submarine cables | Mixed: EMODnet open; NOAA public domain; **NZ LINZ Crown copyright (API key required)**; AU ACMA open; ONC/OOI open |
| ONC (Ocean Networks Canada) | observatories, ADCP, CTD, sparklines | ONC terms (token required) |
| SEAFLEA | methane seeps | Open (NRL/NOAA NCEI compilation) |
| World Ocean Database 2023 | historical O₂ profiles | Open (NOAA) |
| ARCADE v1 | Arctic catchments | DataVerse doi:10.34894/U9HSPV |
| Permafrost thaw — Alaska (Webb et al. 2026) | `permafrost-thaw` | **CC-BY 4.0** (Zenodo) |
| Permafrost thaw — ARTS v6 (WHRC) | `permafrost-thaw` | **CC0** (Zenodo) |
| SIOS Svalbard | observing datasets | SIOS catalogue terms |

⚠️ **PANGAEA-hosted sources set licence per deposited dataset, not per portal.** `hydrothermal-vents`,
`mosaic-sediment`, `mining-footprints`, `arctic-sediment-carbon` and `arctic-rivers` all resolve
through PANGAEA or a PANGAEA-adjacent DOI; every licence shown above was read at that dataset's own
DOI page, never assumed from the portal in general.

---

## For anyone forking this code

1. **The data is not yours to relicense.** AGPL-3.0 covers only the code in this repo.
2. **Re-check the non-commercial row above before any paid use** — the CC-BY-NC lineage from
   Dutkiewicz et al. 2015 flows into modelled products.
3. **Preserve mandatory citations and acknowledgements** — they are a condition of use, not a
   courtesy.
4. You must obtain your own upstream accounts/keys (Copernicus, CDSE, ONC, Dryad, MEMENTO,
   LINZ, …) to populate the layers.
