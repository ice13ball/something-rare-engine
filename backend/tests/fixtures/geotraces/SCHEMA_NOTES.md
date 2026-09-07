# GEOTRACES IDP2025 seawater-discrete — verified schema (2026-06-23)

Source ZIP (anonymous, CC-BY 4.0): https://www.bodc.ac.uk/data/published_data_library/catalogue/10.5285/123/RN-20251119092622_42C921488D038BE6E0637086ABC09F0C.zip
Member: `seawater/ascii/GEOTRACES_IDP2025_Seawater.zip` → `GEOTRACES_IDP2025_Seawater.csv` (268 MB, comma-separated, single header row, 1178 columns).

## Metadata columns (resolve by name, not index)
- `Cruise` (0), `Station:METAVAR:INDEXED_TEXT` (1, value may be text e.g. `(101)`, `001`, `Station 10`), `Type` (2, 'B'=bottle),
  `yyyy-mm-ddThh:mm:ss.sss` (3, ISO datetime), `Longitude [degrees_east]` (4, **0–360 — normalize >180 to -360**),
  `Latitude [degrees_north]` (5), `Bot. Depth [m]` (6), `DEPTH [m]` (20).
- Metadata is REPEATED on every sample row of a station (no forward-fill needed).

## Dissolved metal value columns (v1 targets) — units differ!
- `Co_D_CONC [pmol/kg]`, `Cu_D_CONC [nmol/kg]`, `Fe_D_CONC [nmol/kg]`, `Mn_D_CONC [nmol/kg]`, `Ni_D_CONC [nmol/kg]`
- IDP2025 CSV uses UNIFIED names (NO `_BOTTLE` suffix). Beware lookalikes: `Cu_DL_CONC` (dissolved-labile, NOT our Cu), `Fe_II_D_CONC`, `Fe_S_CONC`. Match the EXACT base name.
- Per value column the next two columns are ALWAYS: `STANDARD_DEV` then `QV:SEADATANET` (the QC flag).
- Capture the unit verbatim from the `[...]` in each header (never hardcode — Co is pmol/kg, others nmol/kg).

## QC flags — SeaDataNet L20
0 no-QC, 1 good, 2 probably-good, 3 probably-bad, 4 bad, 6 below-detection, 8 interpolated, 9 missing.
Policy: keep values with flag NOT IN {4,9}; store raw flag; UI labels quality + below-detection(6). GEOTRACES doc explicitly recommends keeping flagged data and informing users, not dropping it.

## Fixture
`seawater_real_subset.csv` = real header + real rows from cruises GA01/GA02/GA03 covering all 5 dissolved metals, multiple stations (incl. text station names), multi-sample profiles, and flags 1/2/3/6. Use it for parser unit tests.
