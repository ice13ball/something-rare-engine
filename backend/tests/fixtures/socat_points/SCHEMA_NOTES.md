# SOCATv2026 point observations — confirmed schema (verified 2026-10-09 on the VPS, from the real files)

Companion of `../socat_co2/SCHEMA_NOTES.md` (the 1-degree gridded decadal product). Everything below was measured on
the downloaded files, not taken from SOCAT documentation. Counts exclude the 8,453 metadata lines and the header line.

## 1. Files (NCEI Accession 0315110, all `curl -4` 200 OK)

Base: `https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/`

| File | Bytes | Last-Modified | Note |
|---|---|---|---|
| `SOCATv2026_synthesis_file.zip` | 1,470,284,018 | Fri 12 Jun 2026 14:46:31 GMT | ONE member, `SOCATv2026.tsv` = 8,949,823,070 B (zip passes `unzip -t`); sha256 `010941e968652b459ff86c32c368ae0b150cadc3b5c3858668c103a86f9d9341` |
| `SOCATv2026_FlagE.tsv` | 1,614,187,580 | Fri 12 Jun 2026 15:02:30 GMT | flag-E datasets only, same columns |
| regional `SOCATv2026_{Arctic,Coastal,Indian,NorthAtlantic,NorthPacific,SouthernOceans,TropicalAtlantic,TropicalPacific}.tsv` | 534M, 3.8G, 74M, 567M, 313M, 1.9G, 318M, 870M (listing) | 12 Jun 2026 | overlapping subsets of the global file (not downloaded; the global zip is the whole set) |
| `SOCATv2026_DataUseStatement.pdf` 258,649 B · `SOCATv2026_Summary_for_NCEI.pdf` 184,100 B · `Read_SOCATv2019_v2026.m` 27,886 B | | | |

The v2026 release exists (socat.info: released 2026-06-16, data submitted up to 2026-01-16). Report line 1 of the files
says "created: 2026-06-02 13:48 +0000" (main) / "13:45" (FlagE). Gridded products live in `SOCATv2026_Gridded_Data/`
(not used here). VPS copies: `/var/tmp/socat-phase0/` (zip, FlagE tsv, PDFs, .m).

## 2. Structure and columns

Plain TSV (tab, UTF-8, `\n`), no quoting. Lines 1-4 report banner, line 5 = dataset-table column line
(`Expocode version Dataset Name Platform Name PI(s) Data Source DOI Data Source Reference Westmost Longitude Eastmost Longitude
Southmost Latitude Northmost Latitude Start Time End Time QC Flag Additional Metadata Document(s)`), lines 6-8396 = one line per
dataset (15 fields; 8,391 datasets; bbox as `4.85W`/`47.74N` text, dates `YYYY-MM-DD`), then the "Note for data set(s)"
and "Explanation of data columns" text (lines 8397-8453), then the data header at **line 8454** (main) / **line 357** (FlagE),
data from the next line. Locate the header by `Expocode\t` + `\tyr\t`, not by line number. Every one of the 44,018,204 data
lines has exactly 32 fields (0 ragged).

Header, exactly as written (32 columns; the unit is in the name, and the file's own explanation block agrees):

`Expocode` · `version` · `Source_DOI` · `QC_Flag` · `yr` · `mon` · `day` · `hh` · `mm` · `ss` · `longitude [dec.deg.E]` ·
`latitude [dec.deg.N]` · `sample_depth [m]` · `sal` · `SST [deg.C]` · `Tequ [deg.C]` · `PPPP [hPa]` · `Pequ [hPa]` · `WOA_SSS` ·
`NCEP_SLP [hPa]` · `ETOPO2_depth [m]` · `dist_to_land [km]` · `GVCO2 [umol/mol]` · `xCO2water_equ_dry [umol/mol]` ·
`xCO2water_SST_dry [umol/mol]` · `pCO2water_equ_wet [uatm]` · `pCO2water_SST_wet [uatm]` · `fCO2water_equ_wet [uatm]` ·
`fCO2water_SST_wet [uatm]` · `fCO2rec [uatm]` · `fCO2rec_src` · `fCO2rec_flag`

`sal` and `WOA_SSS` are PSS-78 (no unit in the name). `version` is text like `2026.0N` / `1.3N` / `3.0U`
(6,607 N-datasets, 1,784 U-datasets; the N/U suffix is not defined in the file). `Source_DOI` is a DOI or `N/A`.

## 3. Longitude, time, missing values

- **Longitude is 0..360 (east-positive)**: measured min 0.0, max **360.0** (the value 360.00000 occurs, 24 rows in 5 cruises, e.g.
  `06AQ20241224`), so normalise with `((lon + 180) % 360) - 180` and fold 360 -> 0 (and 180.0 -> -180 or 180 deliberately).
  The gridded file is -180..180; this one is not. Latitude -78.7371 .. **90.0** (exactly 90.0 on 10 rows, `06AQ20200801`).
- Time: separate UTC columns `yr` (4 digits) `mon` `day` `hh` `mm` (zero-padded 2 digits) and `ss` as **float text with a trailing
  dot** (`03.`; the explanation says "may include decimal places"). `ss` reaches **60.** (18,098 rows start with `60`) and 7
  datasets (`06AQ19911114, 06AQ19911210, 06MT19920510, 06MT19970106, 06P119910616, 06P119950901, 316N19971005`) have
  artificial hh:mm:ss ("times not provided to a resolution of hours"). Value ranges: yr 1957-**2026**, mon 1-12, day 1-31, hh 0-23, mm 0-59.
- Missing = the literal `NaN` in any numeric column (stated in the file). 0 empty fields, 0 unparseable tokens in the 26 numeric columns.
  Some values keep a trailing dot (`73.`, `5.`).

## 4. QC (main file)

- **Dataset flag** `QC_Flag` is carried on EVERY row and also in the dataset table; all 8,310 cruises with rows agree with their table line (0 mismatches).
  Per-row counts: **A 5,847,993 · B 22,280,448 · C 9,336,714 · D 6,553,049 · E 0** (sum 44,018,204). Dataset table (8,391 datasets): A 1,330, B 3,794, C 1,918, D 1,349.
- **`fCO2rec_flag` = 2 on all 44,018,204 rows** (no 3, 4 or 9); the file banner says it holds "only data points with recomputed fCO2 values
  which were deemed acceptable (WOCE flag 2)". So the main file already contains only good rows; there is no rejection to implement,
  only a guard that asserts `fCO2rec_flag == 2`. `fCO2rec` is NaN on 0 rows.
- `fCO2rec_src` (algorithm 0-14): 1 32,819,858 · 2 2,877,727 · 3 1,654,504 · 4 2,167,905 · 5 258,715 · 6 1,703,762 · 7 21,638 ·
  8 2,185,673 · 9 39,645 · 10 112,298 · 11 26,071 · 12 139,296 · 13 797 · 14 10,315 (0 never occurs).
- **Flag E is a separate file**: `SOCATv2026_FlagE.tsv`, 8,421,630 rows, 290 cruises, QC_Flag E on all, `fCO2rec_flag` 2 on all, fCO2rec 6.577-2321.399,
  years 1994-2025, lon 0-359.99998. Not part of the 44 M. Decide separately whether to import it.
- 81 datasets are listed in the table but have no data rows (QC C 72, B 5, D 2, A 2; e.g. `09SS20080228`); 0 cruises with rows are missing from the table. Cruises are contiguous blocks (no interleaving) and the file is ordered by expocode.

## 5. Size

Data lines **44,018,204**; `wc -l` of the main tsv = 44,026,658 = 44,018,204 + 8,453 metadata lines + 1 header line.
Distinct expocodes with rows: **8,310**. Years 1957 (578 rows) ... 2025 (2,157,741) ... **2026 (2,268 rows, two cruises that straddle the new year)**.
FlagE: 8,421,630 data lines + 356 + 1 = 8,421,987 lines expected.

Published count: socat.info home page (fetched 2026-10-09): "The latest SOCAT version (version 2026) has 44 million observations from
1957 to 2025 with an estimated accuracy of <±5 µatm ... 8.4 million calibrated sensor observations (with estimated accuracy of ±5-10 µatm)
are also available." Arithmetic: 44,018,204 -> 44.0 M (matches "44 million"; the brief's "44 M" is exact to 2 digits);
8,421,630 -> 8.4 M (matches "8.4 million"). No more precise official figure exists on the NCEI page or in the Summary PDF. Imported count should equal
44,018,204 minus nothing (no QC rejections), and "from 1957 to 2025" is the cruise start year range, the file has 2026-dated rows.

## 6. Value distributions (main file; percentiles to 0.1 resolution)

| Column | min | p1 | median | p99 | max | NaN rows |
|---|---|---|---|---|---|---|
| fCO2rec [uatm] | 7.199 | 151.8 | 368.9 | 656.9 | 7748.566 | 0 |
| SST [deg.C] | -2.48 | -1.8 | 14.3 | 30.4 | 34.969 | 5,224 |
| sal | -0.17 | 6.0 | 34.2 | 37.2 | 42.263 | 2,287,508 |

No numeric sentinels (no -999/-9999/9999 anywhere: every column's min/max is physical). Oddities, all real data: fCO2rec 7.2 (`33GC20040908`) and
7748.6 (`11BE20021104`, Belgian coast); negative salinity on 31 rows of `34FP20031001`; `ETOPO2_depth [m]` is negative on 2,263,538 rows
(sign is depth-positive, so negative = above the ETOPO2 land line; range -944 .. 10724) — do not use it as a bathymetry filter;
`dist_to_land` is capped at 1000; `sample_depth [m]` is NaN on 34,774,173 rows (79%), otherwise 0-11 m; `Tequ` NaN 5.1 M, `PPPP` NaN 11.5 M.
Other NaN counts: Pequ 7,086,975 · WOA_SSS 15,425 · NCEP_SLP 3,895 · ETOPO2 10 · dist_to_land 10 · GVCO2 2,156,110 · xCO2_equ_dry 9,162,134 ·
xCO2_SST_dry 34,370,794 · pCO2_equ_wet 35,699,064 · pCO2_SST_wet 19,746,597 · fCO2_equ_wet 34,444,088 · fCO2_SST_wet 10,694,525.

## 7. "What changed" probe

HEAD on the zip: `Content-Length: 1470284018`, `Last-Modified: Fri, 12 Jun 2026 14:46:31 GMT`, `ETag: "57a2c0f2-6540f8ae1d2d2"`, `Accept-Ranges: bytes`.
FlagE: `Content-Length: 1614187580`, `ETag: "60368c3c-6540fc40e7046"`. A new SOCAT version arrives as a new accession/filename (`SOCATv2027_...`,
submission deadline for v2027 is 15 January 2027 per socat.info), so the cheap probe is HEAD of the zip (ETag + Content-Length), plus a directory
listing of `.../ocads/data/0315110/` (it is an Apache index with timestamps) and a check whether `.../ocads/data/` has a newer accession. There is no version file.

## 8. Licence and data-use statement

NCEI metadata page (https://www.ncei.noaa.gov/data/oceans/ncei/ocads/metadata/0315110.html), "DATA LICENSE":
"This dataset is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) License. https://creativecommons.org/licenses/by/4.0/"

Data Use Statement for SOCAT v2026 (https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315110/SOCATv2026_DataUseStatement.pdf), verbatim:
"We expect that users of SOCAT v2026: 1) Generously acknowledge the contribution of SOCAT data providers and investigators in the form of invitation to
co-authorship, reference to relevant scientific articles by data providers or by naming data providers in the acknowledgements. [...] 2) Reference SOCAT and
its data products as: For SOCAT versions 3 to 2026 reference Bakker et al. (2016) (Table 1), as well as the relevant SOCAT data product with its doi-number.
For gridded products reference Sabine et al. (2013) in addition to the above. [...] 3) Include in the acknowledgements: ‘The Surface Ocean CO2 Atlas (SOCAT) is
an international effort, endorsed by the SCOR Infrastructural Project International Ocean Carbon Coordination Project (IOCCP) and the Surface Ocean
Lower-Atmosphere Study (SOLAS), to deliver a uniform, quality-controlled surface ocean CO2 database. The many researchers and funding agencies responsible
for the collection of data and quality control are thanked for their contributions to SOCAT.’ 4) Report problems to SOCAT. 5) Inform SOCAT of publications in which SOCAT is used."
(The PDF writes CO2 with a subscript 2.) Wording is "We expect", not a licence condition: the legal licence is CC BY 4.0; the acknowledgement sentence is
the data providers' request, which the project treats as mandatory. The data files themselves point to http://www.socat.info/SOCAT_fair_data_use_statement.htm (old URL).
Citation (NCEI page / Summary PDF): Bakker, D. C. E., Alin, S. R., Bates, N., ... Xu, Y. (2026). Surface Ocean CO2 Atlas Database Version 2026 (SOCATv2026)
(NCEI Accession 0315110). NOAA NCEI. Dataset. doi:10.25921/8dba-fr90. Also Bakker et al. (2016) ESSD 8, 383-413, doi:10.5194/essd-8-383-2016.
Per-cruise providers: the PI(s) and `Source_DOI` are in the dataset table (per cruise, 15-field line), so a cruise panel can name its PI.
