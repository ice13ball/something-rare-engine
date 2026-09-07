# SOCATv2026 decadal gridded — confirmed schema (verified 2026-06-25 on VPS)

Source (single NetCDF, NOT a tarball):
https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/SOCATv2026_Gridded_Data/SOCATv2026_tracks_gridded_decadal.nc
(25,057,882 bytes; NCEI Accession 0315110; DOI 10.25921/8dba-fr90; CC-BY 4.0)

## Variables used (dims (tdecade, ylat, xlon))
| key       | nc var                          | unit  |
|-----------|---------------------------------|-------|
| fco2      | `fco2_ave_weighted_decade`      | µatm  |
| density   | `fco2_count_nobs_decade`        | count |
| sst       | `sst_ave_weighted_decade`       | °C    |
| salinity  | `salinity_ave_weighted_decade`  | PSU   |

(product also has *_ave_unwtd, *_min, *_max, *_count_nobs, count_ncruise — unused)

## Grid
- dims: `tdecade=6, ylat=180, xlon=360`
- **tdecade** (datetime64, decade centres): 1975-01-01, 1984-12-31, 1995-01-01, 2004-12-31,
  2015-01-01, 2024-12-31 → labels **1970s, 1980s, 1990s, 2000s, 2010s, 2020s** (index 0..5).
- **xlon:** -179.5 … 179.5 ascending, 1° cell-centred → **already -180..180, NO normalization**
  (just argsort defensively).
- **ylat:** -89.5 … 89.5 ascending.
- **missing/land:** NaN (no _FillValue). fCO₂ ~21% finite (sparse, non-gap-filled), min 106.7
  max 4059 (coastal/upwelling outliers — clip domain ~280–450 for the bulk).

Fixture `SOCATv2026_decadal.slice.nc`: real 20×20-cell window × all 6 decades
(fco2_ave_weighted_decade + fco2_count_nobs_decade + tdecade), ~52 KB.
