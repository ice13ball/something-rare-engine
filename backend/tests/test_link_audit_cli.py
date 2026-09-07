# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio

import httpx

from backend.scripts.link_audit import cli
from backend.scripts.link_audit.cli import collect_sampled_rows, dedupe_for_fetch
from backend.scripts.link_audit.models import LinkRow
from backend.scripts.link_audit.sample import fetch_layer_features


def _row(url, surface="tooltip", layer="x"):
    return LinkRow(layer, surface, url, url, "homepage", "f.ts", 1)


def test_dedupes_by_normalized_url_so_each_url_is_fetched_once():
    """glodap.info appears in tooltips, provenance and the inventory. Fetch it
    once; report it three times."""
    rows = [
        _row("https://www.glodap.info/", "tooltip"),
        _row("https://www.glodap.info/", "provenance"),
        _row("https://www.socat.info/", "tooltip"),
    ]
    assert dedupe_for_fetch(rows) == [
        "https://www.glodap.info/",
        "https://www.socat.info/",
    ]  # insertion-ordered, one entry per unique URL


def test_dedupe_preserves_every_occurrence_row_for_reporting():
    rows = [_row("https://a.org/", "tooltip"), _row("https://a.org/", "inventory")]
    assert len(dedupe_for_fetch(rows)) == 1
    assert len(rows) == 2


def _mock_fetch(routes: dict):
    """Route each URL through its own httpx.MockTransport handler while still
    exercising the real fetch_layer_features (no real network, real parsing/
    error handling)."""
    async def _fetch(url, api_key, limit=5, params=None):
        handler = routes.get(url)
        if handler is None:
            return []
        return await fetch_layer_features(
            url, api_key=api_key, limit=limit, params=params,
            transport=httpx.MockTransport(handler))
    return _fetch


def test_collect_sampled_rows_visits_stored_url_layers_and_produces_stored_rows(monkeypatch):
    """A STORED_URL_LAYERS entry with no deep-link template of its own must
    still surface as surface='stored' rows with correct host grouping and the
    TRUE group size (not just the capped sample count)."""
    url = "https://apiv2.example/v1/map/methane-seeps"

    def handler(request: httpx.Request) -> httpx.Response:
        feats = [{"properties": {"source_url": f"https://nature.com/{i}"}} for i in range(7)]
        return httpx.Response(200, json={"features": feats})

    monkeypatch.setattr(cli, "LAYER_ENDPOINTS", {})
    monkeypatch.setattr(cli, "STORED_URL_LAYERS", {"methane-seeps": (url, None)})
    monkeypatch.setattr(cli, "fetch_layer_features", _mock_fetch({url: handler}))

    rows, group_sizes, not_checked = asyncio.run(collect_sampled_rows([], api_key="K"))

    stored_rows = [r for r in rows if r.surface == "stored"]
    assert len(stored_rows) == 3                       # capped sample, not exhaustive
    assert all(r.layer_id == "methane-seeps" for r in stored_rows)
    # fetch_layer_features truncates to its `limit=5` before grouping — the
    # backend returned 7, but only the first 5 ever reach group_stored_urls.
    assert group_sizes == {"methane-seeps": {"nature.com": 5}}
    assert not any("methane-seeps" in reason for reason in not_checked)


def test_collect_sampled_rows_reports_not_checked_when_stored_layer_endpoint_is_empty(monkeypatch):
    """An endpoint that returns no features must be STATED in not_checked, not
    silently dropped from the report."""
    url = "https://apiv2.example/v1/map/dead-layer"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": []})

    monkeypatch.setattr(cli, "LAYER_ENDPOINTS", {})
    monkeypatch.setattr(cli, "STORED_URL_LAYERS", {"dead-layer": (url, None)})
    monkeypatch.setattr(cli, "fetch_layer_features", _mock_fetch({url: handler}))

    rows, group_sizes, not_checked = asyncio.run(collect_sampled_rows([], api_key="K"))

    assert rows == []
    assert group_sizes == {}
    assert any("dead-layer" in r and "no features" in r for r in not_checked)


def test_collect_sampled_rows_reports_not_checked_when_features_have_no_stored_urls(monkeypatch):
    """Features fetched successfully but carrying none of STORED_URL_PROPS
    must also be disclosed, not treated as a silent no-op."""
    url = "https://apiv2.example/v1/map/no-urls-layer"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [{"properties": {"id": 1}}]})

    monkeypatch.setattr(cli, "LAYER_ENDPOINTS", {})
    monkeypatch.setattr(cli, "STORED_URL_LAYERS", {"no-urls-layer": (url, None)})
    monkeypatch.setattr(cli, "fetch_layer_features", _mock_fetch({url: handler}))

    rows, group_sizes, not_checked = asyncio.run(collect_sampled_rows([], api_key="K"))

    assert rows == []
    assert group_sizes == {}
    assert any("no-urls-layer" in r and "no stored URL props" in r for r in not_checked)
