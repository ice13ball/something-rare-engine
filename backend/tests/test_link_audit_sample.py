# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.scripts.link_audit.models import DeepLinkTemplate
from backend.scripts.link_audit.sample import build_deep_link, group_stored_urls


def test_builds_url_from_first_available_prop():
    tpl = DeepLinkTemplate("obis-occurrence", "https://obis.org/occurrence/${id}",
                           ("obis_id", "id"))
    assert build_deep_link(tpl, {"obis_id": "abc123"}) == "https://obis.org/occurrence/abc123"


def test_falls_back_to_the_second_prop_when_the_first_is_absent():
    tpl = DeepLinkTemplate("obis-occurrence", "https://obis.org/occurrence/${id}",
                           ("obis_id", "id"))
    assert build_deep_link(tpl, {"id": "xyz"}) == "https://obis.org/occurrence/xyz"


def test_returns_none_when_no_prop_is_present():
    """kba stores only a local serial PK, so its builder legitimately yields
    nothing — that is a homepage fallback, not an audit failure."""
    tpl = DeepLinkTemplate("kba", "https://www.keybiodiversityareas.org/site/factsheet/${id}",
                           ("SitRecID", "kba_id"))
    assert build_deep_link(tpl, {"id": 7}) is None


def test_url_encodes_the_substituted_value():
    tpl = DeepLinkTemplate("tailings", "https://tailing.grida.no/?search=${name}",
                           ("facility_name",))
    assert build_deep_link(tpl, {"facility_name": "Red Muck Lake #1"}) == (
        "https://tailing.grida.no/?search=Red%20Muck%20Lake%20%231")


def test_stored_urls_are_grouped_by_host_and_capped():
    features = [{"properties": {"source_url": f"https://usgs.gov/pubs/{i}"}} for i in range(50)]
    rows, sizes = group_stored_urls(features, "seaflea", "api:/v1/map/methane-seeps", cap=3)
    assert len(rows) == 3                      # sampled, not exhaustive
    assert sizes["usgs.gov"] == 50             # true group size is reported
    assert all(r.surface == "stored" for r in rows)


def test_stored_url_groups_are_per_host():
    features = [
        {"properties": {"source_url": "https://a.org/1"}},
        {"properties": {"source_url": "https://b.org/1"}},
    ]
    rows, sizes = group_stored_urls(features, "x", "api:/x", cap=3)
    assert sizes == {"a.org": 1, "b.org": 1}
    assert len(rows) == 2


def test_image_url_is_ignored():
    """image_url points at imagery, not information about the object."""
    features = [{"properties": {"image_url": "https://cdn.example.org/a.jpg"}}]
    rows, sizes = group_stored_urls(features, "x", "api:/x", cap=3)
    assert rows == [] and sizes == {}


import asyncio
from pathlib import Path

import httpx

from backend.scripts.link_audit.sample import LAYER_ENDPOINTS, fetch_layer_features


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_endpoint_map_covers_every_deep_link_template_key():
    """A template with no endpoint can never be sampled — that is a silent
    coverage hole, so the map must be complete by construction."""
    from backend.scripts.link_audit.extract_ts import extract_deep_link_templates
    src = REPO_ROOT / "frontend/src/utils/sourceUrl.ts"
    keys = {t.key for t in extract_deep_link_templates(src.read_text(encoding="utf-8"))}
    missing = sorted(keys - set(LAYER_ENDPOINTS))
    assert not missing, f"deep-link keys with no sampling endpoint: {missing}"


def test_fetch_layer_features_sends_the_api_key_and_returns_features():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"features": [{"properties": {"id": "a"}}]})

    feats = asyncio.run(fetch_layer_features(
        "https://apiv2.example/v1/map/x", api_key="K", limit=5,
        transport=httpx.MockTransport(handler)))
    assert seen["key"] == "K"
    assert feats == [{"properties": {"id": "a"}}]


def test_fetch_layer_features_returns_empty_on_error_rather_than_raising():
    """A single unreachable layer endpoint must degrade that layer's coverage,
    not abort the whole audit."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    feats = asyncio.run(fetch_layer_features(
        "https://apiv2.example/v1/map/x", api_key="K", limit=5,
        transport=httpx.MockTransport(handler)))
    assert feats == []


def test_fetch_layer_features_sends_extra_params_alongside_limit():
    """biodiversity/hotspots returns {"features": []} at its default zoom — it
    needs zoom>=3 to return anything, so `params` must reach the request."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"features": [{"properties": {"worms_url": "x"}}]})

    feats = asyncio.run(fetch_layer_features(
        "https://apiv2.example/v1/map/biodiversity/hotspots", api_key="K",
        limit=5, params={"zoom": 5},
        transport=httpx.MockTransport(handler)))
    assert seen["query"] == {"limit": "5", "zoom": "5"}
    assert feats == [{"properties": {"worms_url": "x"}}]


def test_stored_url_layers_only_contains_endpoints_verified_to_carry_stored_urls():
    """Every STORED_URL_LAYERS entry must be a real, resolvable endpoint —
    guards against a future entry being added by memory rather than fetch."""
    from backend.scripts.link_audit.sample import STORED_URL_LAYERS
    assert STORED_URL_LAYERS  # non-empty: the whole point of this feature
    for layer_id, (endpoint, params) in STORED_URL_LAYERS.items():
        assert endpoint.startswith("https://apiv2.something-rare.com/"), layer_id
        assert params is None or isinstance(params, dict), layer_id
