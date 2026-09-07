# ONC RADCPTS netCDF — real schema notes

`radcpts_rcne5_real.nc` is a **real** ONC data product, truncated for size.

Provenance:
- Location `RCNE5`, deviceCategoryCode `ADCP75KHZ` (Endeavour North, RDI 75 kHz).
- Ordered via `dataProductDelivery` — `dataProductCode=RADCPTS`, `extension=nc`,
  `dpo_ensemblePeriod=900` (ONC-side 15-minute ensemble averaging).
- DOI 10.34943/86149231-aa6e-4960-8b72-e7abaa85ae19, downloaded 2026-07-10.
- Subset to `depth=0:8`, `time=0:6`, `meanBackscatter` only. **One NaN injected at
  `[2,1]`** so the gap path is exercised — the full file happens to contain none.
  Every other value is verbatim.

## Facts the parser depends on (verified against the full 1 MB file)

| Fact | Value |
|---|---|
| Full dims | `depth=80`, `time=96` (96 = 24 h ÷ 900 s) |
| `meanBackscatter` dims | **`(depth, time)`** — the opposite order from our `strip[time][bin]` |
| `meanBackscatter` units | dB, observed range 75.2 – 96.7 |
| `depth` coord | **DESCENDING**: `[1885.56, 1877.56, … 1829.56]` m — index 0 is the *deepest* bin |
| `time` coord | `datetime64[ns]`, bin **centres** (`00:07:30`, `00:22:30`, …) |
| Missing values | absent here, but other locations/beams can carry NaN |

The descending depth axis is the trap: `AdcpHeatmap` draws `binIdx = 0` at the top
under a "surface" label, so the parser must sort bins shallow→deep. An unsorted strip
still renders as a plausible image — it is simply upside down.

Other variables in the full product (not currently ingested): `u`, `v`, `w`,
`velocityError`, `intens_beam1..4`, `corr_beam1..4`, `percentGood_beam1..4`,
`velocity_beam1..4`, `temperature`, `pressure`, `sound_speed`, `compassHeading`,
`pitch`, `roll`.

## The sibling product: `NTS` (Nortek Time Series)

Nortek instruments (`BACAX`, `BACME` @ 2 MHz; `HRBIP` @ 400 kHz) do not offer `RADCPTS`
at all — ordering it returns HTTP 400 errorCode 127. They publish `NTS`, whose netCDF has
the **same** variables this parser reads:

```
dims: depth=102, time=96
meanBackscatter (depth, time)  dB
depth           (depth,)       meters
intens_beam1..3                counts     # 3 beams, not 4
```

So one parser serves both; only the product code differs, and it must be read from
`GET /api/dataProducts`, never inferred from the instrument frequency.
