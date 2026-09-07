# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Task 3 + 4 verification: seabed meta payload shape + point sample."""
import pathlib
import pytest
from backend.services import seabed_lithology as sl

FIX = pathlib.Path(__file__).parent / "fixtures" / "seabed" / "seabed_clip.nc"


def test_meta_payload_has_13_classes_and_license():
    meta = sl.build_meta()
    assert len(meta["classes"]) == 13
    assert meta["license"] == "CC-BY-NC"


try:
    import xarray  # noqa: F401
    _XARRAY_AVAILABLE = True
except ImportError:
    _XARRAY_AVAILABLE = False


@pytest.mark.skipif(
    not FIX.exists() or not _XARRAY_AVAILABLE,
    reason="fixture is licence-restricted (CC-BY-NC, Dutkiewicz et al. 2015) and excluded from "
           "the public repository, or xarray is not installed — see DATA-LICENCES.md",
)
def test_point_sample_via_service(monkeypatch):
    sl._GRID = None
    monkeypatch.setattr(sl, "_grid_path", lambda: FIX)
    g = sl.load_grid()
    code = sl.sample(float(g.lats[1]), float(g.lons[1]))
    assert code is None or 1 <= code <= 13
