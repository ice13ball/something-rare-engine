# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The area export must never carry pi_email — as GeoJSON or as CSV."""
from domains import pangaea_water as pw
from ingestion import coastdom, greenland_pp
from pangaea_water_helpers import (  # noqa: F401  (conn is a fixture)
    PP_TSV, coastdom_jsonld, coastdom_tsv, conn, fake_fetch, needs_db, pp_jsonld,
)

pytestmark = needs_db


async def test_area_export_never_carries_pi_email(conn, monkeypatch):
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch({
        coastdom.TEXTFILE_URL: coastdom_tsv(), coastdom.JSONLD_URL: coastdom_jsonld(),
        greenland_pp.TEXTFILE_URL: PP_TSV, greenland_pp.JSONLD_URL: pp_jsonld()}))
    await pw.sync_coastdom()
    from routers.export import export_data
    bbox = "119,26,119.3,26.2"                      # the two Minjiang estuary positions
    geo = await export_data("coastdom", bbox=bbox, poly=None, cells=None, format="geojson")
    csv = await export_data("coastdom", bbox=bbox, poly=None, cells=None, format="csv")
    for body in (geo.body.decode(), csv.body.decode()):
        assert "pi1@example.org" not in body
        assert "pi_email" not in body
    assert '"doc_umol_l": 118.0' in geo.body.decode()
