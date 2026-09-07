# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Build backend/tests/fixtures/wod_oxygen_meta_slice.npz from a REAL WOD file.

Run against a locally downloaded wod_osd_2005.nc:

    python3 backend/scripts/make_wod_meta_fixture.py /path/to/wod_osd_2005.nc

2005 is chosen deliberately: it is the only sampled year that carries BOTH
`CTD` and `bottle/rosette/net` casts and a partially-filled
`Temperature_Instrument` — the 1935 file has no such variable at all, which is
the absent-variable case the parser must survive.
"""
import sys, pathlib, numpy as np
from netCDF4 import Dataset

WANT = 24
src, out = sys.argv[1], pathlib.Path(__file__).resolve().parents[1] / "tests/fixtures/wod_oxygen_meta_slice.npz"
ds = Dataset(src)

def chars(name, idx):
    if name not in ds.variables:
        return None
    v = ds.variables[name][idx]
    return np.array([b"".join(list(np.ma.filled(r, b" "))).decode("utf-8", "replace").strip()
                     for r in v], dtype=object)

ors_all = np.ma.filled(ds.variables["Oxygen_row_size"][:], 0).astype("int64")
zrs_all = np.ma.filled(ds.variables["z_row_size"][:], 0).astype("int64")
gmt_all = np.ma.filled(ds.variables["GMT_time"][:].astype("float64"), np.nan)
dset_all = chars("dataset", slice(None))
instr_all = chars("Temperature_Instrument", slice(None))

# Pick a varied set: CTD + bottle, GMT present + absent, instrument present + absent.
def bucket(i):
    return (dset_all[i] == "CTD", np.isfinite(gmt_all[i]),
            bool(instr_all is not None and instr_all[i]))
seen, idx = {}, []
for i in np.where((ors_all > 0) & (ors_all == zrs_all))[0]:
    b = bucket(i)
    if seen.get(b, 0) >= 3:
        continue
    seen[b] = seen.get(b, 0) + 1
    idx.append(int(i))
    if len(idx) >= WANT:
        break
idx = np.array(sorted(idx))

zcum = np.concatenate([[0], np.cumsum(zrs_all)])
ocum = np.concatenate([[0], np.cumsum(ors_all)])
z, oxy, oflag = [], [], []
for i in idx:
    z.append(np.ma.filled(ds.variables["z"][zcum[i]:zcum[i+1]].astype("float64"), np.nan))
    oxy.append(np.ma.filled(ds.variables["Oxygen"][ocum[i]:ocum[i+1]].astype("float64"), np.nan))
    oflag.append(np.ma.filled(ds.variables["Oxygen_WODflag"][ocum[i]:ocum[i+1]].astype("float64"), np.nan))

def num(name):
    return np.ma.filled(ds.variables[name][idx].astype("float64"), np.nan)

np.savez(
    out,
    wod_cast_id=np.ma.filled(ds.variables["wod_unique_cast"][idx].astype("float64"), np.nan),
    lat=num("lat"), lon=num("lon"), time_days=num("time"), gmt_time=num("GMT_time"),
    bottom_depth=num("Bottom_Depth"), access_no=num("Access_no"),
    oxygen_profile_flag=num("Oxygen_WODprofileflag"),
    z=np.concatenate(z), z_row_size=zrs_all[idx],
    oxygen=np.concatenate(oxy), oxygen_flag=np.concatenate(oflag),
    oxygen_row_size=ors_all[idx],
    country=chars("country", idx), cruise_id=chars("WOD_cruise_identifier", idx),
    platform=chars("Platform", idx), cast_dataset=chars("dataset", idx),
    instrument=chars("Temperature_Instrument", idx),
    o2_units_original=chars("Oxygen_Original_units", idx),
    source_file=np.array([pathlib.Path(src).name], dtype=object),
)
print("wrote", out, "casts:", len(idx))
print("buckets (is_ctd, has_gmt, has_instrument) ->", {str(k): v for k, v in seen.items()})
ds.close()
