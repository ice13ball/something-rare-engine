# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import pytest
from backend.api_docs import curate_schema, build_openapi, PUBLIC_SERVER_URL

BASE = {
    "openapi": "3.1.0",
    "info": {"title": "x", "version": "0"},
    "paths": {
        "/v1/admin/secret": {"get": {"summary": "s", "responses": {}}},
        "/admin/api/login": {"post": {"responses": {}}},
        "/org-admin/api/me": {"get": {"responses": {}}},
        "/v1/feedback": {"post": {"responses": {}}},
        "/v1/blog/articles": {"get": {"responses": {}}},
        "/v1/seo/contractors": {"get": {"responses": {}}},
        "/v1/reports/refresh-species-cache": {"post": {"responses": {}}},
        "/v1/reports/lookup/claims-by-contractor": {"get": {"responses": {}}},
        "/v1/map/claims": {"get": {"responses": {}}},
        "/v2/spatial/tiles/offshore-activities/{z}/{x}/{y}": {"get": {"responses": {}}},
        "/v2/map/water-risk": {"get": {"responses": {}}},
        "/v2/export/{layer}": {"get": {"responses": {}}},
        "/v2/export/{layer}/count": {"get": {"responses": {}}},
    },
}


def test_excludes_internal_paths():
    schema = curate_schema(BASE)
    for p in schema["paths"]:
        assert not p.startswith(("/v1/admin", "/admin", "/org-admin",
                                 "/v1/feedback", "/v1/blog", "/v1/seo"))


def test_keeps_readable_paths_incl_tiles():
    schema = curate_schema(BASE)
    assert "/v1/map/claims" in schema["paths"]
    assert "/v2/map/water-risk" in schema["paths"]
    assert any("/tiles/" in p for p in schema["paths"])


def test_security_scheme_applied():
    schema = curate_schema(BASE)
    sch = schema["components"]["securitySchemes"]["ApiKeyAuth"]
    assert sch == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert schema["security"] == [{"ApiKeyAuth": []}]


def test_servers_and_version():
    schema = curate_schema(BASE)
    assert schema["servers"][0]["url"] == PUBLIC_SERVER_URL
    assert schema["info"]["version"] == "1.0.0"
    assert schema["info"]["title"] == "Abyssal Claims API"


def test_every_op_has_summary_and_tag():
    schema = curate_schema(BASE)
    for p, ops in schema["paths"].items():
        for method, op in ops.items():
            if method in ("get", "post", "put", "delete", "patch"):
                assert op.get("summary"), f"{method} {p} missing summary"
                assert op.get("tags"), f"{method} {p} missing tag"


def test_does_not_mutate_input():
    before = len(BASE["paths"])
    curate_schema(BASE)
    assert len(BASE["paths"]) == before  # deepcopy, input untouched


def test_claims_has_response_example():
    schema = curate_schema(BASE)
    ex = schema["paths"]["/v1/map/claims"]["get"]["responses"]["200"]["content"]["application/json"]["example"]
    assert ex["type"] == "FeatureCollection"
    assert schema["paths"]["/v1/map/claims"]["get"]["responses"]["200"]["description"]


def test_export_has_response_example_and_tag():
    schema = curate_schema(BASE)
    export_op = schema["paths"]["/v2/export/{layer}"]["get"]
    ex = export_op["responses"]["200"]["content"]["application/json"]["example"]
    assert ex["type"] == "FeatureCollection"
    assert ex["metadata"]["layer"] == "geotraces"
    assert export_op["responses"]["200"]["description"]
    assert export_op["tags"] == ["Export"]


def test_hides_reports_refresh_but_keeps_lookup():
    schema = curate_schema(BASE)
    assert "/v1/reports/refresh-species-cache" not in schema["paths"]
    assert "/v1/reports/lookup/claims-by-contractor" in schema["paths"]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="importing backend.main needs env")
def test_real_app_schema():
    from backend.main import app
    app.openapi_schema = None
    schema = build_openapi(app)
    assert "/v1/map/claims" in schema["paths"]
    assert not any(p.startswith("/admin") for p in schema["paths"])
