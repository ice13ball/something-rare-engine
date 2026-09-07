# CHI (Cumulative Human Impact) — verified source schema

**Verified against the REAL source on 2026-07-29** (downloaded + inspected on the VPS
with GDAL 3.10.3 / osgeo + numpy). Do NOT write parsers/ramps from memory or from the
research summary — two of its assumptions were wrong (see ⚠️ below).

## Source

- **Dataset:** Halpern et al. 2025, *Science*, "Cumulative impacts to global marine
  ecosystems projected to more than double by midcentury" (doi:10.1126/science.adv2906).
- **Data package:** KNB `doi:10.5063/F18K77KZ` (DataONE resourceMap
  `urn:uuid:6dc82300-01bf-4a7c-ad3a-fdec662f6aea`).
- **License:** **CC0 1.0 Public Domain Dedication** — verbatim from the EML
  `intellectualRights`. No attribution required (we cite anyway); no non-commercial
  clause. This is the cleanest-licensed source on the platform (contrast: VME's
  Dutkiewicz CC-BY-NC).
- Content: **ten** anthropogenic pressures across **six** categories. The cumulative
  index is **dimensionless** (no unit in the EML — "see Supplementary Methods").

## The file we ingest

`cumulative_impact.zip` — DataONE object
`urn:uuid:15a99425-c3cc-46a5-a3b4-3b26f4df29aa`, **62,962,811 bytes** (~60 MB).
Download URL:
`https://knb.ecoinformatics.org/knb/d1/mn/v2/object/urn:uuid:15a99425-c3cc-46a5-a3b4-3b26f4df29aa`

Zip contains **4 GeoTIFFs** (+ a `__MACOSX/` junk dir to skip):

| File | Meaning | valid min / median / p99 / max |
|------|---------|--------------------------------|
| `ssp245_current.tif`     | **present state** (SSP2-4.5 baseline) | 0.006 / 0.204 / 0.78 / **1.82** |
| `ssp585_current.tif`     | present state (SSP5-8.5 baseline)     | 0.007 / 0.206 / 0.74 / 1.85 |
| `ssp245_medium-term.tif` | projection 2041–2060, SSP2-4.5        | 0.022 / 0.500 / 1.13 / 2.86 |
| `ssp585_medium-term.tif` | projection 2041–2060, SSP5-8.5        | 0.025 / — / — / 3.01 |

## Raster schema (identical for all 4)

- **CRS:** World Mollweide on WGS84 —
  `+proj=moll +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs`.
  GDAL reports the CRS name as `"unknown"` with `METHOD["Mollweide"]`; use the PROJ4
  string above, do NOT assume an EPSG code.
- **Grid:** 3617 × 1814 px, pixel size 10 000 m, origin (−18086282.108, 9070047.848).
- **dtype:** Float32.
- **NODATA:** `nan` (declared). **There is NO −9999 sentinel** — verified `== -9999`
  count is **0** in every band. `gdalinfo -stats` misreports `STATISTICS_MEAN=-9999`;
  that is a GDAL approximate-stats artifact, not data. Compute stats over
  `np.isfinite(a)` only.
- No negative values. ~3.68 M valid ocean cells, ~2.88 M nan (land), ≈56% ocean.

## ⚠️ Corrections to the research summary (both would have shipped bugs)

1. **Values are NOT 0–1.** The research said "wartości przeskalowane 0–1, enkoder ramp
   przyjmie bez zmian." False. Individual *pressures* are rescaled 0–1, but the
   **cumulative** index sums them: present-state max **1.82**, projections to **3.01**.
   The ramp domain must be data-driven (v1 present: ~0 → 1.0 saturating, anchored on
   the real distribution — median 0.20, p95 0.53, p99 0.78), NOT hard-clamped 0–1.
2. **"current" is not a single file.** Two scenario-conditioned present-state rasters
   exist (`ssp245_current`, `ssp585_current`). They differ only ~1% (median 0.204 vs
   0.206). **v1 canonical present = `ssp245_current.tif`** (moderate scenario is the
   conventional reference); the <1% scenario dependence is documented in the panel.

## v1 scope decisions (locked 2026-07-29)

- v1 ingests **`ssp245_current.tif` only** (present state). Projections
  (`*_medium-term.tif`) are **excluded from v1** — a later step with an explicit
  scenario selector (like `coral-acid-exposure` epochs), never mixed with "current".
- Editorial framing (binding): CHI = total human pressure, sum of ~10 stressors,
  seabed mining barely represented; ISA claims sit in LOW-CHI abyssal zones. Context,
  not accusation. MEMENTO causality warning ("a concession polygon is not a causal
  source") carried in-layer: panel `WarningBanner` + legend limitations + export
  provenance note.

## Fixture

`chi_ssp245_current_crop.tif` — a real 64×64 `-srcwin` crop of `ssp245_current.tif`
(srcwin x=1248 y=0), 17,289 bytes. Preserves the real Mollweide CRS + nan NODATA;
values 0.667–0.953 (a valid ocean window with a land/nan edge). Use for parser/reproject
unit tests. Never replace with a synthetic array.
