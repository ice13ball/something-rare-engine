# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Hub pages — the invariants that make them a crawl path rather than decoration.

These tests are all pure: no DB, no app import. Each one guards a way the hubs
could look present while doing nothing, which is the failure mode that produced
29,241 URLs in "Discovered – currently not indexed" in the first place.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from domains import seo  # noqa: E402
from domains.seo_hubs import (  # noqa: E402
    ALL_HUBS,
    HUBS,
    _static_items,
    page_count,
)


class Row(dict):
    """asyncpg rows are mapping-like; the builders only ever subscript them."""


# ── pagination ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "total,per_page,expected",
    [
        (0, 500, 1),        # an empty table still has a page 1 that says "0"
        (1, 500, 1),
        (500, 500, 1),      # exact multiple must not produce an empty trailing page
        (501, 500, 2),
        (37889, 500, 76),
    ],
)
def test_page_count(total, per_page, expected):
    assert page_count(total, per_page) == expected


def test_page_count_never_zero():
    """`/seamount` 404-ing because a table is empty would reinstate the bug."""
    for total in range(0, 5):
        assert page_count(total, 500) >= 1


# ── the layer list must not drift from the sitemap's ─────────────────────────

def test_layer_hub_lists_exactly_the_sitemap_layer_pages():
    urls = [i["url"] for i in _static_items("layer")]
    expected = [f"https://something-rare.com/layer/{lid}" for lid in seo.LAYER_PAGE_IDS]
    assert urls == expected


def test_sitemap_core_still_reads_the_extracted_constants():
    """Guard against someone re-inlining the layer list into the function body.

    Two copies would drift silently: the sitemap would keep advertising a layer
    page the hub no longer links to — asserted but unlinked, which is exactly
    the state this whole change exists to remove. Asserting the NAMES are loaded
    is what catches a re-inline; asserting the values match (test above) would
    still pass against two identical copies.
    """
    src = (BACKEND / "domains" / "seo.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "seo_sitemap_core"
    )
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_LAYER_PAGE_TABLES" in names
    assert "_LAYER_PAGE_TABLELESS" in names


def test_layer_ids_are_unique():
    assert len(seo.LAYER_PAGE_IDS) == len(set(seo.LAYER_PAGE_IDS))


# ── item builders ────────────────────────────────────────────────────────────

def test_seamount_item_carries_a_real_descriptor_not_just_a_number():
    """A page of 500 bare "Seamount #N" links repeats the CTR defect just fixed."""
    item = HUBS["seamount"].row_to_item(
        Row(peak_id=1204898, height_m=2713, latitude=83.92, longitude=-3.0)
    )
    assert item["url"] == "https://something-rare.com/seamount/1204898"
    assert item["label"] == "Seamount #1204898"
    assert "Arctic Ocean" in item["meta"]
    assert "2,713 m" in item["meta"]


def test_seamount_item_abstains_on_an_uncovered_basin():
    """`basin_for` returns None in the Indonesian transition — no guess, no filler."""
    item = HUBS["seamount"].row_to_item(
        Row(peak_id=7, height_m=None, latitude=0.0, longitude=120.0)
    )
    assert item["meta"] == ""
    for placeholder in ("None", "undefined", "null", "—"):
        assert placeholder not in item["meta"]
        assert placeholder not in item["label"]


def test_report_hub_splits_three_kinds_under_one_key():
    """`report_cache` holds claim:, chess: and bare Argo ids. One shape misroutes."""
    claim = HUBS["report"].row_to_item(Row(platform_id="claim:BGR-PMN-1"))
    argo = HUBS["report"].row_to_item(Row(platform_id="4902916"))
    chess = HUBS["report"].row_to_item(Row(platform_id="chess:Snake Pit"))
    assert claim["url"] == "https://something-rare.com/claim-report/BGR-PMN-1"
    assert argo["url"] == "https://something-rare.com/report/4902916"
    # ChESS keeps the /report/ URL — it is the one that works and the one the
    # sitemap already carries. Only the LABEL is corrected: calling a
    # hydrothermal locality "Argo float" is the bug.
    assert chess["url"] == "https://something-rare.com/report/chess:Snake%20Pit"
    assert chess["label"] == "Snake Pit"
    assert "Argo" not in chess["label"] and "Argo" not in chess["meta"]


def test_urls_are_encoded_but_keep_the_colon():
    """Two live ids break naive URL building in opposite directions.

    `chess:10°N - EPR` needs encoding or the href carries a raw space and a
    degree sign. `arcticgro:kolyma` must NOT have its colon encoded: the sitemap
    emits it literally, and two spellings of one URL is the duplicate problem
    this whole change exists to remove.
    """
    degrees = HUBS["report"].row_to_item(Row(platform_id="chess:10°N - EPR"))
    assert degrees["url"] == "https://something-rare.com/report/chess:10%C2%B0N%20-%20EPR"
    assert " " not in degrees["url"]

    river = HUBS["river"].row_to_item(
        Row(station_id="arcticgro:kolyma", river_name="Kolyma", site_label=None)
    )
    assert river["url"] == "https://something-rare.com/river/arcticgro:kolyma"


@pytest.mark.parametrize(
    "kind,row",
    [
        ("concession", Row(isa_id="X", contractor_name=None, resource_type=None, area_km2=None)),
        ("vent", Row(id=1, name=None, region=None, ocean=None, depth_m=None)),
        ("onc", Row(location_code="X", name=None, depth_m=None)),
        ("oceansites", Row(ref="X", name=None, network=None, status=None)),
        ("river", Row(station_id="X", river_name=None, site_label=None)),
    ],
)
def test_all_null_row_still_renders_a_usable_link(kind, row):
    item = HUBS[kind].row_to_item(row)
    assert item["url"].startswith("https://something-rare.com/")
    assert item["label"] and "None" not in item["label"]
    assert "None" not in item["meta"]
    assert not item["meta"].startswith(" · ") and not item["meta"].endswith(" · ")


# ── registry shape ───────────────────────────────────────────────────────────

def test_every_hub_url_matches_its_children():
    """The hub must live at the parent path Google actually probes.

    Google requests /seamount when it sees /seamount/12345. A hub at /seamounts
    would be a new orphan page rather than an answer to that request.
    """
    for kind, hub in ALL_HUBS.items():
        assert hub.kind == kind
        sample = _static_items(kind)[0] if not hub.count_sql else None
        if sample:
            assert sample["url"].startswith(f"https://something-rare.com/{kind}/")


def test_hub_intros_are_not_placeholders():
    for hub in ALL_HUBS.values():
        assert len(hub.intro) > 40
        assert hub.title.endswith("| Abyssal Claims")


# ── the sitemap must not submit a URL the server withdraws ───────────────────
#
# `test_layer_hub_lists_exactly_the_sitemap_layer_pages` above compares two
# backend lists to each other. Both can agree perfectly and both be wrong: on
# 2026-09-03 the sitemap and the hub both carried `/layer/wdpa` while
# `frontend/server.js` answered it 410 Gone. Two backend lists cannot see the
# Express server, so nothing failed.
#
# Submitting a 410 in a sitemap is not cosmetic. Search Console reports it as a
# crawl error against the whole sitemap, and the hub page links to it from a
# page Google does index — an internal link to a withdrawn URL on every crawl.

FRONTEND = BACKEND.parent / "frontend"


def _withdrawn_paths_from_server_js() -> set[str]:
    """Read the Express server's own withdrawal lists — no second copy here.

    A hand-kept mirror of these sets in the test would drift the same way the
    two backend lists did, which is the failure this test exists to catch.
    """
    src = (FRONTEND / "server.js").read_text()
    paths: set[str] = set()
    for const in ("GONE_EXACT", "WITHDRAWN_LAYER_PATHS"):
        i = src.index(f"const {const} = new Set([")
        j = src.index("]);", i)
        paths |= set(re.findall(r"'([^']+)'", src[i:j]))
    return paths


def _gone_prefixes_from_server_js() -> list[str]:
    src = (FRONTEND / "server.js").read_text()
    i = src.index("const GONE_PREFIXES = [")
    j = src.index("];", i)
    return re.findall(r"'([^']+)'", src[i:j])


def test_no_sitemap_layer_page_is_a_url_the_server_withdraws():
    withdrawn = _withdrawn_paths_from_server_js()
    prefixes = _gone_prefixes_from_server_js()
    offenders = []
    for lid in seo.LAYER_PAGE_IDS:
        path = f"/layer/{lid}"
        if path in withdrawn or any(
            path == p or path.startswith(p + "/") for p in prefixes
        ):
            offenders.append(path)
    assert offenders == [], (
        f"the sitemap submits URLs the frontend answers 410: {offenders}"
    )


def test_the_withdrawal_lists_are_actually_readable_from_here():
    """Guard the guard: if server.js renames these consts, the parse must fail
    loudly rather than return an empty set and pass the test above vacuously."""
    assert _withdrawn_paths_from_server_js(), "parsed no withdrawn paths at all"
