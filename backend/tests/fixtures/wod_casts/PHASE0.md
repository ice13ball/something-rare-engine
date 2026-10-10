# WOD23 stage 4 — Phase 0 source measurement (2026-10-09)

Scope: brief `docs/specs/2026-10-06-real-observation-points-brief.md`, stage 4 (WOD OSD + CTD + PFL casts,
T/S/O2/PO4/SiO4/NO3, thinned to ≤100 levels). No code changes, no commits. Everything ran on
the production VPS in `/var/tmp/wod-phase0/` with the backend venv python
(the backend venv python, netCDF4 1.7.4, numpy 2.4.4), `nice -n 19 ionice -c3`,
heavy runs inside `systemd-run --user --scope -p MemoryMax=1500M`. Downloads with `/usr/bin/curl -4`.

Raw companions (same directory):
- `wod-phase0-perfile.txt` — one line per file (225): inst, year, MB, casts, z-levels [p50,p90,p99,max], casts with O2, casts with NO3
- `wod-phase0-samples.txt` — full per-variable output for the 7 downloaded files (flags, fills, units, string fill rates, spot checks)
- On the VPS: `listing.tsv` (HEAD Content-Length for every file), `census.jsonl`/`census_v2b.jsonl` (header census of all 225 files), `analysis.jsonl` (7 sampled files), scripts `inv.sh census.py analyze.py drive.sh agg.py layout.py`.

## 0. Method — exact counts, not only extrapolation

netCDF4 on the VPS can open NCEI files **remotely by HTTP byte range** (`Dataset(url + "#mode=bytes")`) and read
only the header plus the `casts`-sized `<Var>_row_size` arrays (~50 s per file, a few MB of traffic). So the
cast counts below are **exact for all 225 files**, not extrapolated. I still did the requested
casts-per-byte extrapolation from the 7 downloaded files and compare it to the exact numbers (§3).

## 1. Inventory (no download) — `listing.tsv`

Source: `https://www.ncei.noaa.gov/data/oceans/ncei/wod/{year}/wod_{inst}_{year}.nc`, HEAD `Content-Length` per file.

| Instrument | Files | Years | Total bytes | Largest file |
|---|---|---|---|---|
| OSD | 127 | 1800 (=all pre-1900), 1900–2025 | 27,326,682,716 (27.3 GB) | `wod_osd_1989.nc` 806 MB |
| CTD | 64 | 1961–2025 (no 1965) | 18,859,575,373 (18.9 GB) | `wod_ctd_1995.nc` 682 MB |
| PFL | 34 | 1956, 1994–2026 (2026 partial, 65 MB) | 49,472,900,877 (49.5 GB) | **`wod_pfl_2025.nc` 4,518,462,675 B (4.52 GB)** |
| **Total** | **225** | | **95,659,158,966 (95.7 GB)** | |

- ⚠️ `wod/wod_osd_pre1900.nc` and `wod/1800/wod_osd_1800.nc` are the **same file** (identical MD5 `36e5f1ed…` in `wod/MD5SUMS`, 299,843,671 B). Counted once. A naive "all .nc under wod/" sum double-counts it.
- PFL dominates: 52% of bytes; 2013–2025 each 1.8–4.5 GB. CTD peaks 1991–2010 (~0.5–0.7 GB/yr). OSD peaks 1963–1990 (0.4–0.8 GB/yr), and is ~1–7 MB/yr after 2018.
- Files are re-published: PFL/CTD 2015 and 2025 carry 2026-05-13 timestamps (listing), PFL 2026 exists as a partial year.

**Throughput (measured, 7 real downloads, `curl -w`):**

| File | Bytes | Seconds | MB/s |
|---|---|---|---|
| osd_2015 | 67,643,755 | 4.2 | 16.0 |
| osd_1955 | 172,120,067 | 12.1 | 14.2 |
| osd_1975 | 495,730,815 | 24.2 | 20.5 |
| ctd_1995 | 681,800,178 | 61.3 | 11.1 |
| ctd_2015 | 309,483,780 | 14.9 | 20.8 |
| pfl_2008 | 714,337,082 | 57.8 | 12.3 |
| pfl_2024 | 4,186,683,754 | 501.8 | 8.3 |
| **sum** | 6.63 GB | 676 s | **9.8 MB/s average** |

Full mirror of 95.7 GB: **~2.7 h at the measured 9.8 MB/s** (range 1.3 h at 20 MB/s – 3.2 h at 8.3 MB/s), serial.
Streaming one year at a time (download → parse → delete, as `wod_oxygen_ingest.py` does) keeps peak disk at the
largest file, 4.5 GB.

## 2. Real files — what is inside

Downloaded and fully parsed: OSD 1955 (pre-1960), OSD 1975 (busy), OSD 2015, CTD 1995 (largest CTD), CTD 2015,
PFL 2008, PFL 2024 (4.19 GB, a busy recent full year). Each deleted right after parsing.

### 2a. Casts and variables (casts with `<Var>_row_size > 0`; in all 7 files every such cast also had ≥1 non-fill value)

| File | casts | z_rs=0 | T | S | O2 | PO4 | SiO4 | NO3 | any of 6 |
|---|---|---|---|---|---|---|---|---|---|
| osd_1955 | 23,402 | 1,779 | 21,450 | 18,683 | 6,792 | 4,463 | 1,237 | 478 | 21,534 |
| osd_1975 | 56,848 | 1,738 | 53,489 | 48,606 | 20,186 | 11,746 | 10,133 | 5,666 | 54,656 |
| osd_2015 | 8,987 | 423 | 8,381 | 7,916 | 7,769 | 6,084 | 5,666 | 4,630 | 8,545 |
| ctd_1995 | 34,810 | 0 | 34,805 | 34,594 | 7,666 | absent | absent | absent | 34,810 |
| ctd_2015 | 26,010 | 0 | 26,010 | 25,477 | 5,803 | absent | absent | absent | 26,010 |
| pfl_2008 | 113,660 | 0 | 113,639 | 109,691 | 8,232 | absent | absent | 162 | 113,660 |
| pfl_2024 | 170,030 | 0 | 170,013 | 157,381 | 28,857 | absent | absent | 13,907 | 170,029 |

Counting rule: per variable by its own `_row_size`, never by `z` (z exists for casts that have no O2 etc.).
OSD has casts with `z_row_size == 0` (no depth levels at all) — excluded from "any of 6".

### 2b. Levels per cast (per variable `_row_size`, casts with >0) — p50 / p90 / p99 / max

| File | z | T | S | O2 | NO3 |
|---|---|---|---|---|---|
| osd_1955 | 6/15/22/35 | 6/15/22/35 | 7/16/22/35 | 10/17/26/35 | 6/9/20/24 |
| osd_1975 | 9/19/40/123 | 9/19/40/123 | 9/19/41/123 | 12/20/35/78 | 6/19/37/78 |
| osd_2015 | 5/22/37/37 | 5/22/37/37 | 5/22/37/37 | 5/23/37/37 | 5/24/37/37 |
| **ctd_1995** | **128/1529/4191/14,425** | same | 127/1533/4203/14,425 | 418/2572/5511/6507 | — |
| **ctd_2015** | **27/372/4704/7,688** | same | 28/384/4734/7,688 | 134/2416/5464/6123 | — |
| pfl_2008 | 70/115/967/1047 | same | 70/115/967/1047 | 71/967/1034/1037 | 547/547/548/548 |
| **pfl_2024** | **694/1019/1930/3127** | same | 681/1020/1935/3127 | 556/1496/2145/3127 | 554/1470/2195/3127 |

CTD from the census (all files, z levels p50/p90/p99/max): 2005 132/2022/5391/12,958 · 2010 75/1484/4417/10,942 ·
2020 16/88/3135/6080 · 2024 16/120/1878/5814. Max over all CTD files 14,425; over all PFL 11,360 (2025); over all OSD 3,663.
Casts with >100 z-levels: CTD 1995 19,401 of 34,810; PFL 2024 156,478 of 170,030; OSD 1975 21 of 56,848.

### 2c. QC, fills, units

Per variable, all 7 files have `<Var>_WODflag` (int8, per obs, 0 = accepted; meanings `accepted range_out inversion
gradient anomaly …`), `<Var>_WODprofileflag` (int8, per cast, 0 = accepted), `<Var>_sigfigs`, `<Var>_origflag`.
`z` has `z_WODflag` (0 accepted, 1 duplicate_or_inversion, 2 density_inversion) and `z_sigfigs`.
Fill `_FillValue = -1e10` on all value variables.

| File | T flag0 / pf0 | S flag0 / pf0 | O2 flag0 / pf0 / fill% | NO3 flag0 / pf0 / fill% |
|---|---|---|---|---|
| osd_1955 | 0.971 / 0.955 | 0.968 / 0.909 | 0.905 / 0.861 / 9.2% | 0.805 / 0.877 / 18.5% |
| osd_1975 | 0.983 / 0.949 | 0.972 / 0.895 | 0.858 / 0.885 / 14.0% | 0.818 / 0.845 / 16.4% |
| osd_2015 | 0.960 / 0.978 | 0.900 / 0.916 | 0.892 / 0.967 / 10.7% | 0.908 / 0.936 / 8.4% |
| ctd_1995 | 0.999 / 0.966 | 0.992 / 0.943 | 0.961 / 0.796 / 1.3% | — |
| ctd_2015 | 0.999 / 0.966 | 0.999 / 0.952 | 0.995 / 0.961 / 0.6% | — |
| pfl_2008 | 0.990 / 0.949 | 0.990 / 0.939 | 0.677 / 0.853 / **31%** | 0.097 / 0.568 / **89%** |
| pfl_2024 | 0.999 / 0.876 | 0.970 / 0.809 | 0.439 / 0.618 / **56%** | 0.094 / 0.558 / **90%** |

flag0 = share of all obs slots (fills included) with `WODflag == 0`; pf0 = share of casts having the variable with
`WODprofileflag == 0`. Among non-fill obs, flag0 is ~95–99% everywhere (e.g. PFL 2024 NO3: 0.99 M valid, 0.94 M flag0).
Casts with ≥1 flag-0 value AND profile flag 0, e.g. pfl_2024: T 148,984 · S 127,084 · O2 17,824 · NO3 7,535;
osd_1975: T 50,706 · O2 17,831 · PO4 9,164 · SiO4 7,152 · NO3 4,769.

Units: `Temperature` degree_C · `Oxygen`, `Phosphate`, `Silicate`, `Nitrate` umol/kg · **`Salinity` has no `units`
attribute** (practical salinity, dimensionless) · `z` m, `positive: down`, long_name `depth_below_sea_surface`.
PFL additionally has `Pressure` (dbar) on its own `Pressure_obs`; `z` is already depth in m.

### 2d. Coordinates and time

- `lat`/`lon` float32, **±180** in every file (`lon > 180` count = 0; min −180.0, max 180.0), none masked.
  Lat spans −80.0 … 89.99.
- `time` float64, `units = days since 1770-01-01 00:00:00 UTC`, `_FillValue = -1e10`.
  Fill / `< 1.0`: osd_1955 1,305 (5.6%) · osd_1975 1,354 (2.4%) · osd_2015 0 · ctd_1995 59 (0.17%) · ctd_2015 0 · pfl 0.
  Casts with no time of day (whole-day value): osd_1955 33.9% · osd_1975 11.2% · osd_2015 6.0% · ctd_1995 2.3% · ctd_2015 0.07% · pfl ~0.2%.
  Also present: `date` int32 YYYYMMDD, `GMT_time` float32 hours.

### 2e. Identity / platform fields (fill rate)

| Field | osd_1955 | osd_1975 | osd_2015 | ctd_1995 | ctd_2015 | pfl_2008 | pfl_2024 |
|---|---|---|---|---|---|---|---|
| `wod_unique_cast` (int32) | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| `WOD_cruise_identifier` | 96.7% | 98.0% | 82.1% | 93.6% | 99.4% | 100% | 100% |
| `originators_cruise_identifier` | 25.8% | 65.7% | 33.9% | 33.1% | 72.1% | 100% (= float WMO) | 100% |
| `Platform` (ship) | 81.2% | 86.1% | 73.9% | 85.0% | 96.9% | absent | absent |
| `Ocean_Vehicle` | — | — | — | — | — | 100% (APEX…) | 100% (PROVOR-III, SOLO-II…) |
| `WMO_ID` | — | — | — | — | — | 100% | 100% |
| `Institute` | 42.6% | 74.5% | 19.5% | 56.3% | 13.5% | 21.6% | 57.0% |
| `Project` | 9.8% | 25.7% | 8.3% | 23.5% | 0.6% | 88.0% | 77.4% |
| `country` | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| `dataset` | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| `Temperature_Instrument` | — | 9.9% | 17.7% | 79.0% | 61.5% | 99.98% | 99.99% |
| `Oxygen_Instrument` | — | — | 3.3% | 14.5% | — | — | — |
| `real_time` | — | — | — | — | — | 92.3% | 82.3% (`delayed_mode quality controlled data` / `real-time adjusted data`) |
| `Access_no` | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

`dataset` values seen: `bottle/rossette/net` (old OSD spelling), `bottle/rosette/net` (2015), `CTD` **and `XCTD`** inside
the CTD files, `profiling float`.

### 2f. Ragged arrays — offsets vs z (the trap from the rule file)

In all 7 files: `<Var>_row_size == z_row_size` for **every** cast that has the variable (mismatches: 0, all variables).
The **cumulative offsets diverge from z's for almost every cast**: e.g. pfl_2024 Temperature 144,516 of 170,013 casts,
Salinity 157,376 of 157,381, Oxygen 28,856 of 28,857; ctd_2015 Salinity 25,477 of 25,477; osd_1975 Oxygen 20,186 of 20,186.
Exception: ctd_2015 Temperature diverges for 0 casts (every cast has T, so offsets coincide) — the one case where slicing by z would accidentally work.

Spot checks (offsets computed with a plain Python `sum()` over the preceding row sizes, independent of `np.cumsum`):

| File / var | wod_unique_cast | rs | var offset | z offset | depths (first) | correct values | values if sliced at z's offset |
|---|---|---|---|---|---|---|---|
| osd_2015 Oxygen | 17813889 | 2 | 36,066 | 38,693 | 0.4, 2.4 m | 314.14, 314.14 µmol/kg | 119.9, 119.2 (another cast) |
| osd_2015 Salinity | 17813889 | 2 | 35,175 | 38,693 | 0.4, 2.4 m | 11.765, 11.748 (brackish) | 33.38, 33.67 |
| osd_1975 Salinity | 8044758 | 19 | 265,047 | 283,802 | 0,10,20,30,50 … 1972 m | 34.37, 34.33, 34.43, 34.40, 36.02 … 34.95 | 27.24, 27.58, 27.97 … |
| ctd_2015 Oxygen | 17729190 | 6 | 2,523,997 | 3,588,849 | 1.9 … 24.4 m | 287.1, 283.6, 287.6, 262.7, 227.4 … 71.0 | 267.4, 267.3, 267.2 … (flat, wrong cast) |
| ctd_1995 Salinity | 10169209 | 64 | 9,518,995 | 9,553,054 | 2 … 123.8 m | 29.04, 29.47, 29.77 … 35.37 | 33.92, 33.92, 33.92 … |
| pfl_2008 Salinity | 11489988 | 80 | 5,815,565 | 5,901,807 | 5 … 1876 m | 34.89 … 34.62 | 34.37, 34.39 … |
| pfl_2024 Oxygen | 22708857 | 1960 | 10,342,728 | 64,203,096 | 0, 0.3, 0.6, 1.3 m | **fill, 209.4, fill, 209.2, fill** … deepest fill | (z offset beyond the O2 array — would raise / read past end) |

The correct slices give physically coherent profiles (O2 dropping with depth, a brackish surface over salty deep
water); the z-offset slices give another cast's values. Note the PFL row: BGC oxygen is stored **on the CTD z grid
with fills in between** — see surprises.

## 3. Totals — exact (header census) vs extrapolated from samples

Exact (all 225 files, `dims["casts"]` and `_row_size` arrays read remotely):

| | OSD | CTD | PFL | **Total** |
|---|---|---|---|---|
| casts (file `casts` dim) | 3,261,155 | 1,164,910 | 3,227,923 | **7,653,988** |
| casts with any of the 6 vars | 3,042,617 | 1,164,723 | 3,227,506 | **7,434,846** |
| … Temperature | 2,975,645 | 1,163,973 | 3,227,057 | 7,366,675 |
| … Salinity | 2,493,548 | 1,132,102 | 3,014,449 | 6,640,099 |
| … Oxygen | 978,883 | 220,988 | 327,746 | **1,527,617** |
| … Phosphate | 642,239 | 0 | 0 | 642,239 |
| … Silicate | 502,013 | 0 | 0 | 502,013 |
| … Nitrate | 434,560 | 468 | 97,676 | 532,704 |
| raw obs, 6 vars (incl. fill slots) | 83.8 M | 1,085.5 M | 2,869.0 M | **4.04 billion** |
| max z-levels in one cast | 3,663 | 14,425 | 11,360 | |

Cross-check: OSD casts with oxygen = 978,883 vs 978,785 rows in prod `wod_oxygen_profiles` (Δ 98 = casts the existing
parser skips, e.g. time fill) — the census and the existing ingest agree.

Extrapolation as requested (each file's bytes × casts/byte of the nearest sampled year of the same instrument):
OSD 3.33 M (exact 3.26 M, +2%) · CTD 1.17 M (exact 1.16 M, +1%) · PFL 3.89 M (exact 3.23 M, **+21%** — PFL casts/byte
falls 4× between 2008 (159/MB) and 2024 (41/MB) as levels per profile grew) · total 8.39 M vs exact 7.65 M (+10%).
Casts per MB in samples: osd 136 (1955) / 115 (1975) / 133 (2015); ctd 51 (1995) / 84 (2015); pfl 159 (2008) / 41 (2024).

## 3b. Postgres size estimate (one row per cast, ≤100 levels)

Byte model verified read-only on prod PG 17 (`pg_column_size`): `real[100]` = 424 B (24 B header + 4/value);
with a NULL = 436 B; `"char"[100]` = 124 B; `smallint[100]` = 224 B; point geometry = 32 B.
Existing `wod_oxygen_profiles` indexes cost 156 B/row for 5 indexes (pkey 35, unique cast id 45, GiST 51, date 15, decade 10).

Arrays computed per cast from the real row sizes (`L = min(row_size, 100)`, summed over all casts in all 225 files):

| Layout | OSD | CTD | PFL | Total arrays |
|---|---|---|---|---|
| A: one shared `depth real[]` + per variable `real[]` + `"char"[]` flags (fills → NULL) | 0.99 GB | 1.32 GB | 4.32 GB | **6.62 GB** (≈890 B/row) |
| B: per variable its own depth `real[]` + values + flags (needed if fills are dropped per variable) | 1.33 GB | 1.73 GB | 5.58 GB | **8.63 GB** |

Add per row: tuple header + line pointer 28 B, scalar columns ≈120–200 B (cast id, instrument, date/time, geom 32 B,
cruise id, platform FK, n_levels, max depth, profile flags) → 1.1–1.5 GB; indexes 130–160 B/row → 1.0–1.2 GB;
page/fill slack ~5–10%.

**Estimate: ~9 GB (layout A, all 7.43 M casts) to ~12.5 GB (layout B + slack).** Dropping casts with no flag-0 value
or profile flag ≠ 0 removes ~5–15% (higher for PFL BGC). TOAST compression of float arrays saves little (not measured — no writes allowed).
⚠️ Storing levels as JSONB like the existing table (`o2_profile` averages 369 B for 10.3 [depth, O2] pairs ≈ 18 B per number vs 4 B)
would make the arrays ~4.5× larger: **~30 GB**.
PFL is ~65% of the arrays; without thinning the raw 4.04 billion values would be ~16 GB as float32 for values alone.

## 4. Existing table `wod_oxygen_profiles` (prod, read-only)

- Name: `wod_oxygen_profiles` (the rule file calls it `wod_oxygen` — that relation does not exist). 978,785 rows,
  749 MB total (heap 603 MB, indexes 146 MB, toast 1 MB), avg row 537 B, avg 10.26 levels, max 518. `dataset` = `OSD` for all rows,
  dates 1900-05-26 … 2025-04-23.
- Columns: `id serial`, `wod_cast_id text UNIQUE`, `lat`, `lon` (float8), `geom Point 4326`, `profile_date date`, `decade smallint`,
  `cruise`, `dataset`, `country`, `probe_type` (text), `max_depth_m float8`, `n_levels smallint`, `o2_profile jsonb` ([[depth, O2], …]),
  `o2_units text`, `qc_flag smallint`, `qc_note text`, `profile_time timestamptz`, `time_precision text`.
  Indexes: pkey, unique(wod_cast_id), GiST(geom), btree(profile_date), btree(decade).
- Facts relevant to extend-vs-new:
  - Every column that carries data is O2-specific in meaning: `o2_profile`, `o2_units`, `qc_flag`/`qc_note` (O2 QC),
    `n_levels` and `max_depth_m` (defined as the deepest **O2** level, per the rule). For 5.9 M of the 7.4 M target casts there is no O2.
  - Level storage is JSONB: ~4.5× the float32 array size (see §3b); at 7.4 M casts × up to 7 arrays that is the difference between ~9–12 GB and ~30 GB.
  - The sync rewrites the whole table and clears the `wod-oxygen` tile cache; MVT SQL in `routers/spatial_v2.py` decimates by id modulo for 1 M rows.
    7.4 M rows is 7.6× the current row count for the same tile path.
  - The existing 978,883 O2-bearing OSD casts are a strict subset of the stage-4 OSD casts (same `wod_unique_cast`); a new table would duplicate them unless the old layer is retired or re-pointed.
  - `wod_unique_cast` is documented by NCEI as unique across the whole WOD; not cross-checked across instruments here.
- Separate table `wod_profiles` (124 rows, 104 kB, PANGAEA dataset DOIs with lon/lat/year) is unrelated to WOD23 casts despite its name.

## 5. VPS state (2026-10-09, during/after the run)

- `df -h /`: 150 G size, 96 G used, 49 G available, **67%** (unchanged before/after; peak scratch 4.19 GB for pfl_2024).
- RAM: 15 GiB total, ~5.6–7.2 GiB available, swap 8 GiB with 3.5–4.8 GiB used. 8 CPUs.
- Adding the estimated 9–12.5 GB moves / to ~73–75% (plus transient WAL/index-build space during a bulk load).
- Scratch: all `.nc` deleted (`find /var/tmp/wod-phase0 -name '*.nc*'` → 0); directory holds 460 KB of scripts and results.

## 6. Surprises / traps for the implementation

1. **Nutrients come from OSD only.** CTD and PFL files have no Phosphate or Silicate variable at all; Nitrate exists for 468 CTD casts and 97,676 PFL (BGC-Argo) casts. 
2. **PFL BGC variables sit on the CTD z grid with fills in between** (O2 31% fill slots in 2008, 56% in 2024; NO3 ~90%). Thinning "first/every-Nth of ≤100 of z" would produce mostly-empty O2/NO3 arrays — drop fills per variable first, then thin (→ layout B, or per-variable index arrays).
3. `wod_osd_1800.nc` ≡ `wod_osd_pre1900.nc` (same MD5) — do not ingest twice.
4. OSD has 162 k casts with `z_row_size == 0` (3,261,155 casts vs 3,098,810 with depth levels) — no levels at all.
5. Offsets diverge from z for nearly every cast in all three instruments, while per-cast row sizes always match z's — exactly the silent-zip trap; the one exception (ctd_2015 Temperature, every cast has T) would make a wrong implementation pass a test on that file.
6. Salinity has no `units` attribute; CTD files contain XCTD casts (`dataset = 'XCTD'`); OSD `dataset` spelling changes (`rossette` → `rosette`).
7. PFL has no `Platform`; identity is `WMO_ID` + `Ocean_Vehicle` (100%) and `real_time` (delayed-mode vs real-time adjusted).
8. Files are republished (2026-05-13 timestamps on old years; PFL 2026 is partial) — re-sync must be idempotent on `wod_unique_cast`.
9. Header-only remote census works (`#mode=bytes`, ~50 s/file) — useful for a cheap "did NCEI change anything" check without downloading 96 GB. Transient `NetCDF: HDF error` on 3 of 225 remote opens; succeeded on retry.

## Commands used (abridged)

```
ssh <production VPS> 'df -h /; free -h; systemctl cat abyssal-api'
/usr/bin/curl -4 -sS https://www.ncei.noaa.gov/data/oceans/ncei/wod/            # year dirs
/usr/bin/curl -4 -sS $B/$y/ | grep -oE 'wod_(osd|ctd|pfl)_[0-9a-z]+\.nc'        # per-year files
/usr/bin/curl -4 -sSI $B/$y/$f | awk content-length                               # bytes  -> listing.tsv
xargs -P 6 nice -n 19 ionice -c3 python -I census.py <url>                        # netCDF4.Dataset(url+'#mode=bytes'): dims + <Var>_row_size
curl -4 -fsS -o dl/$f -w '%{size_download} %{time_total} %{speed_download}' $B/$y/$f
systemd-run --user --scope -p MemoryMax=1500M nice -n 19 ionice -c3 python -I analyze.py dl/$f; rm -f dl/$f
sudo -u postgres psql -d abyssal -X -c '\d+ wod_oxygen_profiles' ; SELECT count/pg_total_relation_size/pg_column_size(...)
```
