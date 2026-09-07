# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pytest
from backend.scripts.link_audit.normalize import normalize_url, classify_kind


@pytest.mark.parametrize("raw,expected", [
    # bare hostname gets a scheme
    ("obis.org", "https://obis.org"),
    ("ncei.noaa.gov/products/world-ocean-database",
     "https://ncei.noaa.gov/products/world-ocean-database"),
    # already-absolute URLs are left alone
    ("https://www.glodap.info/", "https://www.glodap.info/"),
    # http is PRESERVED, never silently upgraded — the upgrade is a proposed fix
    ("http://example.org/x", "http://example.org/x"),
    # protocol-relative
    ("//cdn.example.org/a", "https://cdn.example.org/a"),
    # surrounding whitespace and trailing prose punctuation are stripped
    ("  https://obis.org/  ", "https://obis.org/"),
    ("https://doi.org/10.1594/PANGAEA.917894.", "https://doi.org/10.1594/PANGAEA.917894"),
    # a bare DOI becomes a resolver URL
    ("10.1594/PANGAEA.917894", "https://doi.org/10.1594/PANGAEA.917894"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://doi.org/10.1594/PANGAEA.917894", "doi"),
    ("https://www.glodap.info/", "homepage"),
    ("https://services2.arcgis.com/x/FeatureServer/0/query", "endpoint"),
    ("https://data.linz.govt.nz/services;key=K/wfs", "endpoint"),
    ("https://obis.org/occurrence/${id}", "deep-link"),
])
def test_classify_kind(url, expected):
    assert classify_kind(url) == expected


def test_normalize_does_not_collapse_doubled_slash():
    """A doubled slash is a *fixable defect*, so normalization must preserve it
    for the fixer to find rather than silently repairing it."""
    assert normalize_url("https://x.org//a") == "https://x.org//a"
