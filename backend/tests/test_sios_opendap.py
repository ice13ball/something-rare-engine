# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_sios_opendap.py
import pathlib
from backend.ingestion import sios_opendap as so

FX = pathlib.Path(__file__).parent / "fixtures/sios_opendap"
DDS = (FX / "shortwave_dds.txt").read_text()
ASCII = (FX / "shortwave_ascii.txt").read_text()


def test_parse_data_variable():
    assert so.parse_data_variable(DDS) == "shrtRad"


def test_time_dim_size():
    assert so.time_dim_size(DDS) == 2196990


def test_epoch_ms_1900_decodes_to_2017():
    # shortwave series starts ~2017-07-25 (value ~42939 days since 1900)
    ms = so.epoch_ms_from_days_since_1900(42939.0)
    import datetime as dt
    d = dt.datetime.utcfromtimestamp(ms / 1000)
    assert d.year == 2017 and d.month == 7


def test_parse_ascii_grid_pairs():
    pairs = so.parse_ascii_grid(ASCII, "shrtRad")
    assert len(pairs) >= 10
    assert all(len(p) == 2 for p in pairs)


def test_build_series_shape():
    s = so.build_series(DDS, ASCII)
    assert s and s["var"] == "shrtRad"
    pts = s["points"]
    assert len(pts) >= 10
    assert isinstance(pts[0][0], int) and isinstance(pts[0][1], float)
    assert pts == sorted(pts)  # time-ordered
