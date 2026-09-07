# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
from backend.services import bathymetry_stats as bs

def test_tid_groups_disjoint_and_correct():
    assert 11 in bs.TID_MEASURED and 10 in bs.TID_MEASURED and 17 in bs.TID_MEASURED
    assert 40 in bs.TID_INDIRECT and 44 in bs.TID_INDIRECT and 46 in bs.TID_INDIRECT
    assert 70 in bs.TID_UNKNOWN
    assert bs.TID_MEASURED.isdisjoint(bs.TID_INDIRECT)

def test_classify_confidence_thresholds():
    assert bs.classify_confidence(85) == "high"
    assert bs.classify_confidence(80) == "high"
    assert bs.classify_confidence(50) == "medium"
    assert bs.classify_confidence(19) == "low"

def test_summarize_counts_and_depth():
    # 2x2 window: codes [[11,40],[11,0]], elev metres [[-1000,-2000],[-1500,500]]
    tid = np.array([[11, 40], [11, 0]], dtype=np.int16)
    elev = np.array([[-1000, -2000], [-1500, 500]], dtype=np.float64)
    mask = np.array([[True, True], [True, False]])  # exclude the land cell (500)
    out = bs.summarize(tid, elev, mask)
    assert out["n_cells"] == 3
    assert round(out["pct_measured"], 1) == round(200/3, 1)   # two of three are code 11
    assert round(out["pct_multibeam"], 1) == round(200/3, 1)
    assert round(out["pct_indirect"], 1) == round(100/3, 1)
    assert out["depth_min_m"] == 1000.0 and out["depth_max_m"] == 2000.0  # positive-down

def test_tri_zero_on_flat():
    assert bs.tri(np.full((3, 3), -2000.0)) == 0.0


# ---------------------------------------------------------------------------
# Task 2: grid tests — skipped when GEBCO clip fixtures or xarray/shapely absent
# ---------------------------------------------------------------------------
import pathlib, pytest

FIXD = pathlib.Path(__file__).parent / "fixtures" / "bathymetry"


def _deps():
    try:
        import xarray, netCDF4, shapely  # noqa
        return True
    except Exception:
        return False


gridmark = pytest.mark.skipif(
    not (FIXD.exists() and (FIXD / "tid_clip.nc").exists() and _deps()),
    reason="GEBCO clip fixtures or deps absent — grid test deferred to VPS (Task 9)",
)


def _write_tiny_nc(tmp_path, lat_asc: bool) -> tuple:
    """Build a 4×4 lat/lon grid with tid/elevation and write to two .nc files."""
    import xarray as xr
    import numpy as np

    lats = np.array([-1.5, -0.5, 0.5, 1.5], dtype=float)
    lons = np.array([-1.5, -0.5, 0.5, 1.5], dtype=float)
    if not lat_asc:
        lats = lats[::-1]

    tid_data  = np.full((4, 4), 11, dtype=np.int16)   # all multibeam
    elev_data = np.full((4, 4), -3000.0, dtype=float)  # 3 km ocean

    ds_tid = xr.Dataset({"tid":       (["lat", "lon"], tid_data)},
                        coords={"lat": lats, "lon": lons})
    ds_elev = xr.Dataset({"elevation": (["lat", "lon"], elev_data)},
                         coords={"lat": lats, "lon": lons})

    tid_nc  = tmp_path / f"tid_{'asc' if lat_asc else 'desc'}.nc"
    elev_nc = tmp_path / f"elev_{'asc' if lat_asc else 'desc'}.nc"
    ds_tid.to_netcdf(tid_nc)
    ds_elev.to_netcdf(elev_nc)
    return tid_nc, elev_nc


@pytest.mark.skipif(not _deps(), reason="xarray/netCDF4/shapely absent")
@pytest.mark.parametrize("lat_asc", [True, False], ids=["ascending", "descending"])
def test_sample_polygon_lat_order(tmp_path, monkeypatch, lat_asc):
    """_window must return non-empty arrays for both ascending and descending lat grids."""
    tid_nc, elev_nc = _write_tiny_nc(tmp_path, lat_asc)
    monkeypatch.setattr(bs, "_tid_path",  lambda: tid_nc)
    monkeypatch.setattr(bs, "_elev_path", lambda: elev_nc)
    geom = {"type": "Polygon", "coordinates": [[
        [-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0]
    ]]}
    out = bs.sample_polygon(geom, (-1.0, -1.0, 1.0, 1.0))
    assert out is not None, f"sample_polygon returned None for lat_asc={lat_asc}"
    assert out["n_cells"] > 0, f"n_cells=0 for lat_asc={lat_asc}"


@gridmark
def test_sample_polygon_ccz(monkeypatch):
    monkeypatch.setattr(bs, "_tid_path", lambda: FIXD / "tid_clip.nc")
    monkeypatch.setattr(bs, "_elev_path", lambda: FIXD / "elev_clip.nc")
    geom = {"type": "Polygon", "coordinates": [[
        [-129.5, 11.5], [-128.5, 11.5], [-128.5, 12.5], [-129.5, 12.5], [-129.5, 11.5]
    ]]}
    out = bs.sample_polygon(geom, (-129.5, 11.5, -128.5, 12.5))
    assert out is not None and out["n_cells"] > 0
    assert 0 <= out["pct_measured"] <= 100
    assert out["depth_median_m"] > 0    # CCZ abyssal → kilometres deep


# --- _download format dispatch -------------------------------------------------
# BODC moved GEBCO 2024 to CEDA: TID still serves a ZIP, but the elevation URL now
# redirects to a bare GEBCO_2024_CF.nc. _download assumed ZIP unconditionally, so the
# elevation grid raised BadZipFile -> warning -> ensure_holdings() False -> bake silently
# skipped. Only reachable via force-sync or a fresh-DB boot, so it had no symptoms.
# First 8 bytes below are the real ones off the live CF file (ranged GET, 2026-07-16).
_HDF5_HEAD = b"\x89HDF\r\n\x1a\n" + b"\x00" * 64


def _fake_curl(monkeypatch, write_payload):
    """Stub the curl subprocess so no test ever reaches for 7.5 GB over the wire."""
    import types

    def _run(cmd, **kwargs):
        write_payload(__import__("pathlib").Path(cmd[cmd.index("-o") + 1]))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(bs.subprocess, "run", _run)


def test_download_accepts_bare_netcdf(tmp_path, monkeypatch):
    # The regression: elevation now arrives as a bare netCDF4/HDF5, not a ZIP.
    monkeypatch.setattr(bs, "RAW_DIR", tmp_path)
    _fake_curl(monkeypatch, lambda p: p.write_bytes(_HDF5_HEAD))
    dst = tmp_path / "GEBCO_2024.nc"
    assert bs._download("http://example/elev", dst) is True
    assert dst.read_bytes()[:4] == b"\x89HDF"


def test_download_extracts_zip(tmp_path, monkeypatch):
    # TID is still a ZIP upstream — the sniff must not regress it.
    import zipfile

    monkeypatch.setattr(bs, "RAW_DIR", tmp_path)

    def _zip(p):
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("GEBCO_2024_TID.nc", _HDF5_HEAD)

    _fake_curl(monkeypatch, _zip)
    dst = tmp_path / "GEBCO_2024_TID.nc"
    assert bs._download("http://example/tid", dst) is True
    assert dst.read_bytes()[:4] == b"\x89HDF"


def test_download_rejects_unrecognised_payload(tmp_path, monkeypatch):
    # An HTML error page must fail loudly rather than land as a corrupt .nc.
    monkeypatch.setattr(bs, "RAW_DIR", tmp_path)
    _fake_curl(monkeypatch, lambda p: p.write_bytes(b"<html>404</html>"))
    dst = tmp_path / "GEBCO_2024.nc"
    assert bs._download("http://example/oops", dst) is False
    assert not dst.exists()


def test_download_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "RAW_DIR", tmp_path)
    _fake_curl(monkeypatch, lambda p: p.write_bytes(_HDF5_HEAD))
    dst = tmp_path / "GEBCO_2024.nc"
    bs._download("http://example/elev", dst)
    assert [p.name for p in tmp_path.iterdir()] == ["GEBCO_2024.nc"]
