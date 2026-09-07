# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
`_raster_disk_path` (backend/routers/spatial_v2.py) builds a filesystem path
for the offshore-activities on-demand raster cache from a `filter_key` string
that is derived directly from user-supplied `types`/`countries` query params
(only split-and-stripped, no allowlist). Before the fix, `filter_key` was
interpolated straight into the filename, so a value like
"../../../../etc/passwd" (or a leading "/", or a null byte) could make the
resulting path escape `_RASTER_CACHE_DIR` entirely. Since `_raster_put` does
`p.parent.mkdir(parents=True, exist_ok=True)` and then writes bytes, that is
an arbitrary file WRITE, not just a read.

These tests execute the actual path builder (not a grep of the source) and
assert the resulting path can never leave the cache root, while two distinct
filter_keys still get two distinct (and stable) cache files.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from routers.spatial_v2 import _RASTER_CACHE_DIR, _raster_disk_path  # noqa: E402


def _assert_contained(p: pathlib.Path) -> None:
    """The resolved path must sit inside the resolved cache root.

    A plain string check for "../" is not enough — a path can normalise
    to an escape without ever containing that literal substring (e.g. via
    an absolute-path component or unusual separators). `resolve()` performs
    the actual filesystem-level normalisation before we compare.
    """
    root = _RASTER_CACHE_DIR.resolve()
    resolved = p.resolve()
    assert root in resolved.parents or resolved == root, (
        f"{resolved} escaped cache root {root}"
    )


# A shallow "../../../etc/passwd" is not by itself sufficient to prove escape:
# the vulnerable builder still prefixes the malicious value with "{y}__", and
# pathlib only treats an exact ".." *segment* as "go up one level" — enough
# ".." segments have to outnumber the fixed directory depth under
# _RASTER_CACHE_DIR (offshore-activities/_ondemand/{z}/{x}/{y}__...) before a
# resolve() actually lands outside the cache root. 20 repetitions comfortably
# clears that depth (and even the filesystem root) regardless of how deep
# _RASTER_CACHE_DIR itself is configured, so this is what actually goes RED
# against the unpatched builder — see the RED/GREEN proof in the task report.
_DEEP_TRAVERSAL = "../" * 20 + "etc/passwd"

MALICIOUS_KEYS = [
    "t=" + _DEEP_TRAVERSAL + "--c=ALL",
    _DEEP_TRAVERSAL,
    "/etc/passwd",  # leading '/' injection (defence in depth; see note above)
    "t=ALL--c=" + "\x00" + "evil",
    "t=" + "A" * 4000 + "--c=ALL",  # far over the ~255-byte filename limit
]


@pytest.mark.parametrize("filter_key", MALICIOUS_KEYS)
def test_malicious_filter_key_cannot_escape_cache_dir(filter_key: str) -> None:
    p = _raster_disk_path(5, 10, 15, filter_key)
    _assert_contained(p)


def test_malicious_filter_key_produces_short_safe_filename() -> None:
    """A hex-digest filename can never trip the filesystem's ~255-byte
    per-component name limit, regardless of how many types/countries the
    caller stuffs into filter_key."""
    p = _raster_disk_path(5, 10, 15, "t=" + "A" * 4000 + "--c=ALL")
    assert len(p.name.encode()) <= 255


def test_null_byte_filter_key_does_not_raise() -> None:
    # A null byte in a path historically raises ValueError from the OS layer
    # on some platforms; the digest must neutralise it before it ever reaches
    # a path component.
    p = _raster_disk_path(5, 10, 15, "t=ALL--c=\x00evil")
    _assert_contained(p)
    assert "\x00" not in str(p)


def test_different_filter_keys_map_to_different_paths() -> None:
    p1 = _raster_disk_path(5, 10, 15, "t=oil_rig--c=US")
    p2 = _raster_disk_path(5, 10, 15, "t=wind_farm--c=US")
    assert p1 != p2


def test_same_filter_key_maps_to_same_path_twice() -> None:
    # The cache must still work: identical inputs => identical output path,
    # deterministically, across separate calls.
    p1 = _raster_disk_path(5, 10, 15, "t=oil_rig--c=US")
    p2 = _raster_disk_path(5, 10, 15, "t=oil_rig--c=US")
    assert p1 == p2


def test_benign_filter_key_still_lands_under_cache_dir() -> None:
    p = _raster_disk_path(5, 10, 15, "t=ALL--c=ALL")
    _assert_contained(p)
    assert p.parent.parent.parent == _RASTER_CACHE_DIR / "offshore-activities" / "_ondemand"
