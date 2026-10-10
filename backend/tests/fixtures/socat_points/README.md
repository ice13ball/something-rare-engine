# socat_points — real SOCATv2026 point-observation excerpt

Rows are copied verbatim (byte for byte, original header and text blocks) from the official SOCATv2026
synthesis file, nothing edited or generated. Findings about the whole file: `SCHEMA_NOTES.md`.

- Source: NCEI Accession 0315110, https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/
  - `SOCATv2026_synthesis_file.zip` (1,470,284,018 B) -> `SOCATv2026.tsv` (8,949,823,070 B), report created 2026-06-02
  - `SOCATv2026_FlagE.tsv` (1,614,187,580 B), report created 2026-06-02 13:45
- Version: SOCAT v2026 (released 2026-06-16), DOI 10.25921/8dba-fr90. Licence CC BY 4.0 + acknowledgement
  sentence (see SCHEMA_NOTES section 8).
- Cut on the VPS (`/var/tmp/socat-phase0/`), 2026-10-09: per cruise a contiguous run of data lines
  (`sed -n A,Bp`), then concatenated; windows are 100 rows unless the cruise is shorter. Layout of the
  excerpt file = layout of the original: 4 report lines, the dataset-table column line, the dataset-table
  lines of the cut cruises (+ one dataset with no rows), the "Note for data set(s)" + "Explanation of data
  columns" text block, the data header line, the data rows. Cruises are in file (alphabetical) order.
  Windows are not whole cruises (except 64SA20060719 and 74P220080731), so per-cruise counts are those of the window.

## Files

| File | Rows | Contents |
|---|---|---|
| `SOCATv2026_excerpt.tsv` (246,433 B) | 1,195 data rows, 12 cruises | main synthesis file excerpt (QC flags A-D only, WOCE 2 only) |
| `SOCATv2026_FlagE_excerpt.tsv` (20,986 B) | 96 data rows, 1 cruise | same layout from the separate flag-E file |

## What each cruise demonstrates

| Expocode | Rows | Trap |
|---|---|---|
| `64SA20060719` | 185 (whole) | track crosses the 0/360 meridian: lon 0.062 ... 359.678 in one cruise (naive min/max of lon spans the globe); also `sample_depth` filled, flag D |
| `06AQ20241224` | 100 | lon is exactly `360.00000` on 2 rows, next row `0.00008`: 360 must fold to 0, `lon >= 360` bug; lat -59.5, year 2025 |
| `320620060130` | 100 | crosses the antimeridian (lon 178.46 ... 180.014, so the file value goes past 180 and must become -179.99 in -180..180); Ross Sea, lat -77.6; flag B |
| `06AQ20200801` | 100 | North Pole: lat 89.98 ... 90.00 (10 rows in the whole file at exactly 90.0), lon 7 ... 340 within the window; flag B |
| `11BE20021104` | 100 | extreme coastal fCO2rec: 7093 ... 7748.566 uatm (file maximum), Belgian coast, flag D, version 1.3N |
| `33GC20040908` | 100 | extreme low fCO2rec: 7.2 ... 18.5 uatm (file minimum 7.199), flag C; still WOCE 2 |
| `31HO19571021` | 100 | oldest year (1957); `sal` is `NaN` on every row; flag D |
| `34FM20251127` | 100 | calendar year 2026 appears (50 rows 2025, 50 rows 2026) although SOCAT states "1957 to 2025"; Baltic, flag B |
| `34FP20031001` | 100 | negative salinity (8 rows, e.g. -0.030); Baltic Sea Lines, flag D, version 1.3N |
| `06AQ19911114` | 100 | `ss` = `60.` (second 60) and artificial hh:mm:ss; the file's "Note for data set(s)" names this cruise: times not provided to hour resolution; sample_depth filled |
| `74P220080731` | 10 (whole) | smallest cruise, flag D, lon 355.96 ... 356.09 (near the meridian), sample_depth filled (`5.`) |
| `76XL20160724` | 100 | `SST` and `sal` `NaN` on 2 rows (missing is the literal `NaN`) |
| `09SS20080228` | 0 rows | dataset listed in the dataset table (QC B) but with no data rows in the file: 81 such datasets |
| `35DR19990124` (FlagE file) | 96 (whole) | flag-E dataset: QC_Flag `E`, WOCE 2, Antares drifting buoy 1999; absent from the main file |

Not present in the real file, so no fixture exists: `fCO2rec` = `NaN` (0 of 44,018,204 rows), a WOCE flag other
than 2 (all rows are 2), dataset flag E in the main file.

## Licence and acknowledgement

SOCAT v2026 is licensed CC BY 4.0 (NCEI metadata page for Accession 0315110). The data providers ask that users
include: "The Surface Ocean CO2 Atlas (SOCAT) is an international effort, endorsed by the SCOR Infrastructural Project
International Ocean Carbon Coordination Project (IOCCP) and the Surface Ocean Lower-Atmosphere Study (SOLAS), to deliver
a uniform, quality-controlled surface ocean CO2 database. The many researchers and funding agencies responsible for the
collection of data and quality control are thanked for their contributions to SOCAT." Reference: Bakker et al. (2016) ESSD 8,
383-413, doi:10.5194/essd-8-383-2016, and SOCATv2026 doi:10.25921/8dba-fr90.
