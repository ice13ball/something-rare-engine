# WOD23 casts fixture

Real casts cut out of NOAA NCEI World Ocean Database 2023 files (OSD, CTD, PFL), used by the `wod-casts` parser
tests. WOD is public domain (NOAA/NCEI, no redistribution restriction). Source: the NCEI directory
`https://www.ncei.noaa.gov/data/oceans/ncei/wod/<year>/wod_<inst>_<year>.nc`. Phase 0 measurements of the full
source are in `PHASE0.md`.

## Files

| File | Cut from | Why |
|---|---|---|
| `wod_osd_1975_cut.nc` | `wod_osd_1975.nc` | 8044758 (S, 19 levels), 13485047 (O2 with fills between levels), 11115466 (NO3, one level at 5 m), first cast with `z_row_size = 0`, first with `time < 1.0`, first with a zero fraction (day only), first at lon -180.0 or 180.0, first cast with neither time nor date (if any), and 2 casts without oxygen before the first oxygen cast |
| `wod_osd_2015_cut.nc` | `wod_osd_2015.nc` | 17813889 (brackish S / O2 spot), 18954244 (NO3), first cast whose any variable has `WODprofileflag != 0`, 2 casts without oxygen placed before the first oxygen cast |
| `wod_ctd_2015_cut.nc` | `wod_ctd_2015.nc` | 17729190 (O2 spot), 17384990 (S, 899 levels, thinning), first `dataset == "XCTD"`, first with lat >= 89.9, 2 casts without oxygen before the first oxygen cast |
| `wod_pfl_2024_cut.nc` | `wod_pfl_2024.nc` | 22708857 (O2, 1,960 levels, fills on the CTD grid), 22710905 (NO3, 557), 22705470 (S, 58), first `real_time == "real-time adjusted data"`, 2 casts without oxygen before the first oxygen cast |
| `wod_osd_1970_cut.nc` | `wod_osd_1970.nc` | first cast whose `time` decodes to 1970-01-01 (and the no-time-no-date cast if it was not found earlier). Single-purpose time fixture: exempt from the oxygen offset-divergence assertion (the four main cuts are not). Written only if one exists; `expected.json` says `"time_1970_cast": "none found"` otherwise |
| `listing_root.html`, `listing_1800.html` | NCEI `/` and `/1800/` | the `<a href=...>` lines only, unedited, for the listing-parser tests |
| `expected.json` | the ORIGINAL files | the oracle, below |
| `PHASE0.md` | | the Phase 0 report (host names and home paths stripped) |

The cast with neither time nor date (`no_time_no_date_cast` in `expected.json`): if the sources contain none, the
value says so and the test builds one synthetically from a real cast with `time` set to its fill (-1e10) and
`date` to 0.

## How it was cut (`backend/scripts/wod_cut_fixture.py`)

Run on the production VPS, no download of whole files (netCDF byte-range opens, `Dataset(url + "#mode=bytes")`;
the netCDF side uses libcurl, the listings use urllib forced to IPv4 because the VPS has no IPv6 route to NCEI):

    python -I <dir>/wod_cut_fixture.py --out <dir>/fixture      # wod_casts_rules.py copied beside it

Each cut is a netCDF4 (zlib) file with the selected casts in source order. Every ragged array is re-packed by
its OWN row sizes (`z`, `z_WODflag` by `z_row_size`; `<Var>`, `<Var>_WODflag` by `<Var>_row_size`), so the
offset trap survives: in the cut, oxygen's cumulative offsets differ from z's for >= 1 cast (asserted per cut
file, and the count per variable is stored as `trap_divergent_casts`). Variable and dimension names, dtypes and
all attributes (`units`, `_FillValue`, `flag_values`, `flag_meanings`, ...) are copied; variables not listed in
the brief are not copied. Text variables are copied raw (char matrices stay char matrices). Total size of the
cut files is asserted < 1 MB. After writing, the oracle code is run again over the CUT file and must reproduce
the oracle computed from the original, byte for byte, or the script fails.

## `expected.json` (the oracle)

Computed from the original files with plain Python: ragged offsets are `sum()` of the preceding row sizes (no
numpy cumsum), picks come from the script's own loop over the R1 windows, nothing is imported from
`ingestion.wod_casts_*` except constants (`DEPTHS`, `WINDOWS`, `VARS`, `NSTAR_K`). A parser test must compare the
parser's output to this file, never recompute it.

```
{
 "schema_version": 1,
 "constants": {"depths": [0, 50, ...], "windows": [[lo, hi], ...], "nstar_k": 16.0, "fill_limit": -1e9},
 "no_time_no_date_cast": {"file": "wod_osd_1975.nc", "wod_unique_cast": int} | "none found ..." (string),
 "time_1970_cast": "found" | "none found",
 "notes": {<cut name not written>: [str, ...]},
 "cut_bytes_total": int,
 "files": {
  "<cut file name, e.g. wod_osd_1975_cut.nc>": {
    "source_file": "wod_osd_1975.nc",
    "counts": {"source", "no_depth_levels", "no_values", "stored", "no_good", "no_date", "drawn"},
    "trap_divergent_casts": {"<NetCDF var, e.g. Oxygen>": int},      # casts whose own offset != z's offset
    "notes": [str],                                                    # rules that matched nothing
    "casts": {
      "<wod_unique_cast as a decimal string>": {
        "wod_unique_cast": int, "file": "wod_osd_1975.nc",             # file = the ORIGINAL file name
        "lat": float, "lon": float,                                    # float32 values as doubles
        "raw_time": float | null,                                      # `time` as stored; < 1.0 = fill
        "raw_date": int | null,                                        # `date` as stored (YYYYMMDD, parts may be 0)
        "dataset": str | null,                                         # e.g. "bottle/rosette/net", "XCTD"
        "z_row_size": int,
        "time": {"date": "YYYY-MM-DD" | null, "precision": "second"|"day"|"month"|"year"|null,
                 "second_of_day": int | null},                         # decode: time first, then date; a zero
                                                                       # fraction = "day", never a midnight
        "reasons": [str],                                              # why this cast is in the fixture
        "vars": {                                                      # only NetCDF variables PRESENT in the file
          "<Temperature|Salinity|Oxygen|Phosphate|Silicate|Nitrate>": {
            "row_size": int,                                           # <Var>_row_size of this cast
            "profile_flag": int,                                       # <Var>_WODprofileflag, raw
            "row_size_mismatch": bool,                                 # row_size > 0 and != z_row_size (levels then [])
            "n_valid": int,                                            # non-fill values (len(levels))
            "n_good": int,                                             # valid AND flag 0 AND z_flag 0 AND profile_flag 0
            "levels": [[j, z, value, flag, z_flag], ...]               # ONLY non-fill values, j = index within
          }                                                            # the cast's slice, ascending; z/value/flag
        },                                                             # read at the VARIABLE'S OWN offset
        "picks": {                                                     # per display depth, DEPTHS order (8 entries)
          "<temperature|salinity|oxygen|phosphate|silicate|nitrate>": [[j, z, value] | null, ...],
          "nstar": [[j, z, nstar, no3, po4] | null, ...]               # always present, 8 entries
        },
        "status": "no_depth_levels"|"no_values"|"no_good"|"no_date"|"drawn"
      }
    }
  }
 }
}
```

Definitions:

* **good level** (for picks and `n_good`): value is not a fill (`value > -1e9`), `<Var>_WODflag == 0`,
  `z_WODflag == 0`, the cast's `<Var>_WODprofileflag == 0`, and `z` is not a fill.
* **pick**: among good levels with `lo <= z <= hi` of the depth's R1 window (inclusive), the one nearest the
  target depth; ties go to the shallower `z`, then the lower `j`. `picks` keys are the WOA variable keys
  (`temperature`, `salinity`, `oxygen`, `phosphate`, `silicate`, `nitrate`), `vars` keys are NetCDF names. A
  variable absent from the file is absent from both. `z` is the double value of the float32 depth, so a parser
  that compares in float32 can see rounding differences at the 1e-7 level; compare with tolerance.
* **N\***: `nitrate - 16 * phosphate` at the SAME index `j` (all variables sit on z's grid), both levels good,
  then picked exactly like any other variable. `[j, z, nstar, no3, po4]`; `nstar` is a double computed from the
  float32 inputs. For files without a Phosphate variable (CTD, PFL) all 8 entries are null.
* **status** (first match): `no_depth_levels` = `z_row_size == 0`; `no_values` = no variable has a non-fill
  value (or the only ones have a size mismatch); `no_good` = has values but no good level in any variable;
  `no_date` = has a good level but `time.date` is null; `drawn` = the rest.
* **counts** (over the casts of that cut file): `source` = number of casts in the cut file; `stored` = casts with
  at least one non-fill value = `no_good + no_date + drawn` (P5: `no_date` is counted only for casts that have a
  good value); `drawn = stored - no_good - no_date` exactly; `source = no_depth_levels + no_values + stored`.
* Phase 0 measured `row_size == z_row_size` for every cast that has the variable, so `levels[*][1]` (z) is read
  from z's own slice at the same `j`.

## Census (`backend/scripts/wod_casts_measure.py`)

Remote header census of all 225 files (see the script docstring); its JSON result is pasted into the ops doc.
