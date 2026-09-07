# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The Data Inventory tab must not publish a hand-typed count.

`("offshore", …, "16 government registries", …)` shipped in `_INVENTORY` and was
public until 2026-08-27, by which time the ingest fed 26 source tags across 40
sovereigns. Nothing failed: a typed number rots silently, and this one sat on
the layer that is the platform's best evidence of what it does.

These tests guard the shape of the defect, not the number. Re-typing a fresher
count is the same bug with a later expiry date.
"""
from __future__ import annotations

import inspect
import re

import main
from routers import spatial_v2


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def test_no_inventory_label_opens_with_a_bare_count():
    """A digit is fine — a digit that COUNTS OUR OWN HOLDINGS is not.

    Years, versions and citations ("Yesson et al. 2020", "OpenAQ v3",
    "WRI Aqueduct 4.0") are stable facts about the upstream. A leading integer
    is us claiming how much we hold, which only the database knows.
    """
    typed = [
        (row[0], row[5]) for row in main._INVENTORY
        if isinstance(row[5], str) and row[5] is not main._COUNTED
        and re.match(r"^\d+\s", row[5])
    ]
    assert typed == [], f"hand-typed counts in _INVENTORY: {typed}"


def test_the_offshore_label_is_counted_not_typed():
    row = next(r for r in main._INVENTORY if r[0] == "offshore")
    assert row[5] is main._COUNTED
    assert "offshore" in main._COUNTED_ORG


def test_every_counted_key_exists_in_the_inventory():
    keys = {r[0] for r in main._INVENTORY}
    assert set(main._COUNTED_ORG) <= keys


def test_the_fallback_carries_no_number():
    """A failed count must degrade to a vaguer TRUE label, never to a stale one."""
    assert not re.search(r"\d", main._COUNTED_ORG_FALLBACK)


def test_offshore_count_uses_the_same_predicate_as_the_country_filter():
    """⛔ The number on the label and the number in the filter are one claim.

    `offshore_activities_countries` excludes rows with no name AND no operator.
    Counting sovereigns without that clause yields 41 while the filter offers
    40 — two different numbers for the same thing, on the same screen.
    """
    sql, _template = main._COUNTED_ORG["offshore"]
    endpoint_src = _norm(inspect.getsource(spatial_v2.offshore_activities_countries))
    for clause in (
        "where sovereign is not null",
        "and (name is not null or operator is not null)",
    ):
        assert clause in _norm(sql), f"label SQL is missing: {clause}"
        assert clause in endpoint_src, f"endpoint no longer has: {clause} — re-check the label"


def test_the_template_renders_the_count_it_is_given():
    _sql, template = main._COUNTED_ORG["offshore"]
    assert template.format(n=40) == "Government registries — 40 countries"
