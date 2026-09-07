# GLODAP v2.2016b Mapped Climatology — confirmed schema (verified 2026-06-25 on VPS)

Source tarball (GEOMAR mirror): https://glodap.info/glodap_files/v2.2023/GLODAPv2.2016b.MappedProduct.tar.gz
(211,523,164 bytes; NOAA origin fallback under nodc.noaa.gov/archive/arc0107/0162565/).

Per-variable NetCDF files used (data var name == file stem after "GLODAPv2.2016b."):

| file                              | data var       | unit    |
|-----------------------------------|----------------|---------|
| GLODAPv2.2016b.TCO2.nc            | `TCO2`         | µmol/kg |
| GLODAPv2.2016b.TAlk.nc            | `TAlk`         | µmol/kg |
| GLODAPv2.2016b.pHtsinsitutp.nc    | `pHtsinsitutp` | (pH)    |
| GLODAPv2.2016b.Cant.nc            | `Cant`         | µmol/kg |

Each file also carries `<var>_error`, `<var>_relerr`, `Input_mean/std/N`, `SnR`, `CL`, `Depth`.

- **dims:** `depth_surface=33, lat=180, lon=360` (main var shape `(depth_surface, lat, lon)`; squeeze any size-1 `snr`).
- **depth values** (read from the `Depth` DATA VAR, not the bare `depth_surface` dim), metres:
  `[0,10,20,30,50,75,100,125,150,200,250,300,400,500,600,700,800,900,1000,1100,1200,1300,1400,1500,1750,2000,2500,3000,3500,4000,4500,5000,5500]`
- **lat:** -89.5 … 89.5 (ascending, 1° cell-centred).
- **lon:** **20.5 … 379.5** (1° cell-centred, 20°E origin, wraps past 360) → normalize: values >180 minus 360, then sort ascending → -159.5 … 179.5.
- **missing/land:** `_FillValue` absent; missing cells are **NaN** (use `np.isnan`). ~52% finite.
- **observed ranges:** TCO2 1019–2402; TAlk 1069–2660; pHtsinsitutp 7.43–8.52; Cant -0.49–72.86 µmol/kg.

Fixture `GLODAPv2.2016b.TCO2.slice.nc`: real 20×20-cell Pacific window × all 33 depths (TCO2 + Depth + lat/lon), 118 KB.
