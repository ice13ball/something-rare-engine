# Data sources and licences

**Almost no data ships in this repository, and the exception is named here rather than
glossed.** Beyond the source code, `backend/tests/fixtures/` holds ~1.1 MB of **real**
upstream excerpts across 14 sources — among them GEOTRACES seawater rows, ONC ADCP
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
| **Dutkiewicz et al. 2015** — global seabed lithology (EarthByte) | `seabed-substrate` (the served layer id; `seabed_lithology.py` is the module, and the row said only `seabed-lithology` for months — a reader looking the layer up by id found nothing) **and, as a model predictor,** `vme-suitability` → `coral-acid-exposure` | **CC-BY-NC 4.0** | Non-commercial. This lineage runs *through* the VME suitability model into the coral acidification-exposure layer. The platform is publishable today **only because it is non-monetised.** If this platform, or any fork, is ever put behind a paid tier, this CC-BY-NC lineage must be re-assessed first. |
| **MaxMind GeoLite2** — Country / ASN databases | request-log enrichment in the API-key subsystem (`GEOIP_COUNTRY_DB`, `GEOIP_ASN_DB`) | MaxMind GeoLite2 EULA | **Redistribution is prohibited** by the EULA. The `.mmdb` files are therefore **not** in this repository and must be obtained directly from MaxMind under your own account. Without them the enrichment is simply skipped (`country`/`asn` stay NULL) — nothing else breaks. |
| **InterRidge Vents Database v3.4** (via PANGAEA) | `hydrothermal-vents` | **CC-BY-NC-SA 4.0** | Non-commercial **and** share-alike, confirmed at the dataset's own PANGAEA DOI (doi:10.1594/PANGAEA.917894). Not yet resolved organisationally as of the 2026-09-03 licence audit — re-check before any monetised use. |
| **OBIS-SEAMAP** (Duke University Marine Geospatial Ecology Lab) | `noise-risk` (cetacean-sightings component; the layer also blends ICES and EMODnet Physics data) | Redistribution prohibited without permission | OBIS-SEAMAP's terms of use forbid redistributing data obtained from the portal. `noise-risk` computes an index that includes OBIS-SEAMAP sightings, inheriting the restriction for that component. |
| **MBARI MARS** (Monterey Accelerated Research System) | ⛔ `hydrophone-stations` **left `LAYER_DEFAULTS` / `LAYER_DEFAULTS_PY` and the export registry on 2026-09-04** (`services/export_registry.py`). The weekly `sync_acoustic_stations` still runs and the rows are still in the database, so this clause still binds them — it is the toggle and the bulk export that went away, not the data. Was: one of 22 passive-acoustic networks aggregated into the layer. | "Internal research activities only" | Per MBARI's VARS data-use policy. Restricts only this one sub-source within the aggregate — the other 21 networks are unaffected individually. |

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
| **MARHYS Database 4.0** (vent fluid chemistry) | `marhys` | CC-BY 4.0 | Diehl & Bach (2024), PANGAEA doi:10.1594/PANGAEA.972999. ⭐ **The dataset's own header requires the base publication to be cited ALONGSIDE it**: Diehl & Bach (2020), *Geochemistry, Geophysics, Geosystems*, doi:10.1029/2020GC009385 — citing only the PANGAEA DOI does not satisfy the terms. Compiled at MARUM, University of Bremen; funded by DFG EXC 2077. Frozen at v4.0; versions 1.0-3.0 carry their own DOIs. |
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
| ISA DeepData (`services5.arcgis.com/VcAAb5oBhdAAnFj2`) | `contracts`, `reserved-areas`, `relinquished-areas`, `apeis` — four layers off ONE FeatureServer | Open (isa.org.jm/deepdata) |
| **ISA DeepData (OBIS-hosted Darwin Core datasets)** — Environmental and biological sampling archives from ISA contractor surveys (`datasets.obis.org/hosted/isa/`) | `deepdata-stations` | **CC-BY 4.0**, per `<intellectualRights>` in each dataset's `eml.xml` metadata. Attribution is mandatory. Verified in 8 of ~140 archival datasets. |
| OBIS Open Data (AWS parquet mirror, `s3://obis-open-data/occurrence/*.parquet`) | `obisSpecies`; also aggregated into `biodiversity-hotspots` | Open (obis.org) |
| GBIF (`api.gbif.org/v1/occurrence/search`) | `chess` — the ChEssBase chemosynthetic dataset. ⭐ Pure pass-through since 2026-09-21: the one field that was ours, `chess.habitat_type`, was **removed** rather than improved, because the source publishes no habitat field to pass through. → `docs/methods/data-passthrough.md` | Open, CC-BY / CC0 per dataset (gbif.org) |
| NOAA DSCRTP, MBARI VARS | deep-sea coral/sponge density | Open (NOAA / MBARI) |
| IUCN Red List | biodiversity status | Terms of use (non-redistribution of bulk) |
| WoRMS | taxonomic backbone | Open (marinespecies.org) |
| UNEP-WCMC & IUCN — Protected Planet (WDPA) | ⛔ **withdrawn 2026-09-03** (was: protected areas) | WDPA terms forbid redistribution "through interactive web maps ... that grant users download access" without prior written permission from UNEP-WCMC. Rows remain in the database; the layer is no longer served. |
| BirdLife International / KBA Partnership — Key Biodiversity Areas | ⛔ **withdrawn 2026-09-03** (was: KBAs) | Same redistribution clause as WDPA, plus a separate no-commercial-use clause (verified at keybiodiversityareas.org/termsofservice). Rows remain in the database; the layer is no longer served. |
| MarineRegions.org (VLIZ) — EEZ v12 | `eez`; geometry also underlies `protected-marine-sites` | CC-BY 4.0. VLIZ additionally, non-bindingly, requests that users not host bulk downloads elsewhere and always link back to marineregions.org — noted, not a licence restriction. |
| UNESCO World Heritage Marine Programme + Protected Planet, compiled by MarineRegions.org (VLIZ) | `protected-marine-sites` (50 World Heritage marine sites — **not** WDPA, see `rules/subsystems/tables-that-lie.md`) | CC-BY 4.0, via the MarineRegions WFS layer `MarineRegions:worldheritagemarineprogramme` (DOI 10.14284/592, cited as "UNESCO (2023)"). ⛔ We do **not** fetch from whc.unesco.org — the "UNESCO syndication terms" cited here until 2026-09-11 named a page we have never used. Two questions remain open (2026-09-11): (a) VLIZ's site-wide CC-BY covers "Marine Regions' products", but this product's own citation names **UNESCO** as author, and UNESCO's site terms licence their content CC BY-SA 3.0 IGO — a **ShareAlike**, which CC-BY is not, and VLIZ cannot relicense a third party's content; (b) the compilation draws on **Protected Planet**, the same UNEP-WCMC source that forced the `wdpa` withdrawal on 2026-09-03. Mitigating facts: we store only `name` and `country` as text (facts, not expression), discard every UNESCO-authored description and criterion at ingest, and removed the layer from Area Export on 2026-09-11. Ask VLIZ (info@marineregions.org) which licence governs this product; fold the Protected Planet question into the open UNEP-WCMC thread. |
| National offshore-energy regulators (BOEM, Crown Estate, Crown Estate Scotland, NOPTA, NZP&M, ANP, Sodir, NSTA, CNH, ESDM, PASA, ANH, MRA Papua New Guinea, MME Namibia, SBMA Cook Islands) + EMODnet Human Activities | `offshore-activities` | Mixed: EMODnet portion is CC-BY 4.0 (confirmed). The 16 national-regulator feeds are government registries whose individual reuse terms have **not** been verified per-registry — check each before redistribution. |
| `tayljordan/ports` (GitHub, `raw.githubusercontent.com/tayljordan/ports/main/ports.json`) | `ports` | **MIT**, read from the GitHub API 2026-09-11 (`"spdx_id": "MIT"`). ⚠️ A community compilation of 5,410 ports, not an official hydrographic register — the MIT grant covers the compilation, and says nothing about the national sources behind it. |
| **GDW — Global Dam Watch database v1.0** (figshare doi:10.6084/m9.figshare.25988293.v1) | `dams` | **CC BY 4.0** — read from Figshare's own item metadata 2026-09-11: `"license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}`. ⚠️ **This is an ATTRIBUTION licence, unlike the CC0 it replaced** — GDW must be credited wherever the layer is shown or exported, and the credit is in the legend and the panel. Loaded 2026-09-11: 41,145 barrier points from `GDW_barriers_v1_0.shp`; the reservoir polygons in the same archive are not served. GDW absorbs GOODD and GRanD, which globaldamwatch.org states "will be discontinued". ⛔ Its no-data code is **-99** and it is stored as SQL NULL, never as a measurement. |
| **GOODD** — Mulligan, van Soesbergen & Sáenz 2020, *Scientific Data* 7:31 (figshare doi:10.6084/m9.figshare.9747686.v1) | ⛔ **retired 2026-09-11** (was: `dams`) | **CC0**, verified in Figshare's item metadata. Served here until GDW v1.0 replaced it. GOODD publishes four fields — DAM_ID, Count_ID, Latitud, Longitud — so the layer carried no names or attributes at all; its rows are kept in `dams_goodd_backup_20260911`. |
| **OceanOPS** (`ocean-ops.org/api/data/oceanjson/platforms`) | `oceansites` | ⚠️ **Non-commercial, and stricter than our own code comment claims.** Verbatim from ocean-ops.org/api/help, read 2026-09-11: *"All rights reserved. The information provided through this API may be freely used and copied for educational and other non-commercial purposes, provided that any reproduction of data ... be accompanied by an acknowledgement (credit, link) of OceanOPS as the source. Any other use of the information requires permission from OceanOPS."* The ingest comment calls this "the WMO data policy" — it is not; WMO Resolution 40 governs the separate DBCP/GTS route. ⛔ **This is a SECOND non-commercial dependency** beside the Dutkiewicz lineage above, and it must be counted in any future decision to monetise. |
| **Yesson et al. 2020** — *List of seamounts in the world oceans, an update* (doi:10.1594/PANGAEA.921688) | `seamounts` | **CC-BY-4.0**, stated on the PANGAEA record, read 2026-09-11. |
| **WRI Aqueduct 4.0** | `water-risk` | **CC BY 4.0** — wri.org/aqueduct, read 2026-09-11: *"All the products, methodologies, and datasets that make up Aqueduct are available for use under the Creative Commons Attribution International 4.0 License."* |
| JRC Global Surface Water (Pekel et al. 2016) | `surface-water` | CC-BY, conditional: attribution must name both **JRC and Google**, plus cite Pekel et al. 2016 — see global-surface-water.appspot.com/faq |
| _(no upstream — this platform's own derivation)_ | `monitoring-density` | Not a dataset. `domains/land/density.py` builds a materialised view that `UNION ALL`s tables already licensed above (`chess_occurrences`, `argo_profiles`, `oceansites_stations`, `onc_instruments`, `hotspot_grid`, `wod_profiles`, `pangaea_records`, `bco_dmo_datasets`, `noaa_datasets`, `obis_seamap_records`, `sio_bic_records`). It fetches nothing, so it adds no new grant — but it INHERITS the strictest term among its inputs, and `oceansites_stations` is the non-commercial OceanOPS feed. |
| _(under review)_ | `forest-loss`, `carbon-flux`, `soil-carbon`, `tectonic-plates`, `mosaic-sediment`, `arctic-rivers`, `ais-live`, `air-quality`, `landslides` | **Not stated here yet.** Each of these upstreams either publishes no licence, or publishes terms that do not resolve into one. Rather than print a guess, this file says nothing about them until the maintainer has checked each. Treat these nine layers as unlicensed for reuse until this row is replaced. Two were added 2026-09-11 after checking the upstreams directly: **OpenAQ** (`air-quality`) publishes no blanket grant — docs.openaq.org/about/terms says only *"We only aggregate data that, to the best of our knowledge, has been made available for redistribution"* and *"we provide no assurance that the data provided may be used free of any third-party claims"*; real terms are per-source. **NASA COOLR** (`landslides`) states no licence on gpm.nasa.gov/landslides — and the exact page our code cites, `/landslides/data.html`, now returns **404**. |
| GEBCO — **three products are served deliberately, and they are different vintages** | `bathymetry` shaded relief = `GEBCO_LATEST` WMS, which auto-tracks the newest grid (GEBCO_2026 as of 2026-09-08, verified against the live GetCapabilities); bathymetry **confidence / TID** stats = `GEBCO_2024` (`sync_bathymetry_stats`); per-point depth lookup = `GEBCO_2020` via Open-Topo-Data | Open, "not for navigation" — the terms are identical across all three vintages, but the **attribution year is not**: `GEBCO_LATEST` moved to the 2026 grid while the hand-written credit string still said 2025, so re-read the live WMS before citing a year. |
| Copernicus Marine (CMEMS) | `ocean-currents`, plume tracing | Copernicus licence (account required) |
| ESA Copernicus Sentinel-1 (CDSE) | SAR / dark vessels; the SAR×AIS correlator also produces `vessel-events` ⚠️ whose OTHER input is AIS, still under review below | Copernicus licence (account required) |
| NASA FIRMS | `fires` active fires | Open (NASA LANCE) |
| NOAA WOA23 (`ncei.noaa.gov/data/oceans/woa/WOA23/DATA`) | `woa-climatology` | Public domain (US Gov) |
| ISAS20 (BGC-Argo), SEANOE doi:10.17882/52367 | `oxygen-deox` | Open |
| Argo, via Argovis (`argovis-api.colorado.edu/argo`) | `argo` float profiles | Open (Argo programme) |
| EMODnet / NOAA Marine Cadastre / NZ LINZ / AU ACMA / ONC / OOI | `submarine-cables` (six feeds, one layer) | Mixed: EMODnet open; NOAA public domain; **NZ LINZ Crown copyright (API key required)**; AU ACMA open; ONC/OOI open |
| ONC (Ocean Networks Canada) | `onc` (observatory locations) and `onc-instruments` — ADCP, CTD, sparklines. Each CTD deployment also carries ONC's own DOI and citation string, stored verbatim in `onc_deployment_citations` | ONC terms (token required) |
| SEAFLEA (`services2.arcgis.com/C8EMgrsFcRFL6LrL`) | `methane-seeps` | Open (NRL/NOAA NCEI compilation) |
| World Ocean Database 2023 (`ncei.noaa.gov/data/oceans/ncei/wod`) | `wod-oxygen` historical O₂ profiles | Open (NOAA) |
| ARCADE v1 | `arctic-catchments` | DataVerse doi:10.34894/U9HSPV |
| Permafrost thaw — Alaska (Webb et al. 2026) | `permafrost-thaw` | **CC-BY 4.0** (Zenodo) |
| Permafrost thaw — ARTS v6 (WHRC) | `permafrost-thaw` | **CC0** (Zenodo) |
| SIOS Svalbard (`sios-svalbard.org/rest/stations/data.json`) | `sios-svalbard` observing datasets | SIOS catalogue terms |

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
