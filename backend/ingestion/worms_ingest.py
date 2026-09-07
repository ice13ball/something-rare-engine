# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WoRMS (Aphia) taxonomic resolver — pure logic + thin REST fetchers.

Pure functions carry the test weight; the httpx fetchers are thin and
network-gated.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("abyssal.worms")

REST_BASE = "https://www.marinespecies.org/rest"
MAX_BATCH = 50
# match_type preference, best first
_MATCH_RANK = {"exact": 0, "like": 1, "phonetic": 2, "near_1": 3, "near_2": 4, "near_3": 5}


def normalize_name(name: str) -> str:
    """Trim and collapse internal whitespace. Used as the crosswalk key."""
    return " ".join((name or "").split())


def pick_best_candidate(candidates: list[dict] | None) -> dict | None:
    """Return the highest-confidence candidate by match_type, or None."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: _MATCH_RANK.get(c.get("match_type", ""), 99))


def resolution_from_candidate(name: str, candidate: dict | None) -> dict:
    """Build a taxon_name_map row from a chosen candidate (or None)."""
    raw = normalize_name(name)
    if candidate is None:
        return {"raw_name": raw, "matched_aphia_id": None, "match_type": "none", "verified": False}
    match_type = candidate.get("match_type") or "none"
    valid_id = candidate.get("valid_AphiaID") or candidate.get("AphiaID")
    return {
        "raw_name": raw,
        "matched_aphia_id": int(valid_id) if valid_id is not None else None,
        "match_type": match_type,
        "verified": match_type == "exact",
    }


def worms_row_from_record(record: dict) -> dict:
    """Map an authoritative AphiaRecord to a worms_taxa upsert row."""
    return {
        "aphia_id": int(record["AphiaID"]),
        "scientificname": record.get("scientificname"),
        "authority": record.get("authority"),
        "rank": record.get("rank"),
        "status": record.get("status"),
        "kingdom": record.get("kingdom"),
        "phylum": record.get("phylum"),
        "class_name": record.get("class"),
        "order_name": record.get("order"),
        "family": record.get("family"),
        "genus": record.get("genus"),
        "is_marine": record.get("isMarine"),
        "is_brackish": record.get("isBrackish"),
        "is_freshwater": record.get("isFreshwater"),
        "is_terrestrial": record.get("isTerrestrial"),
        "citation": record.get("citation"),
        "url": record.get("url") or record.get("lsid"),
        "worms_modified": record.get("modified"),
    }


async def match_names(names: list[str]) -> list[list[dict]]:
    """Fuzzy+batch match (<=50 names). Returns one candidate-list per input name.
    Normalizes WoRMS' null slots to empty lists so callers see a stable shape."""
    if not names:
        return []
    params = [("scientificnames[]", n) for n in names[:MAX_BATCH]]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{REST_BASE}/AphiaRecordsByMatchNames", params=params)
        if r.status_code == 204:
            return [[] for _ in names[:MAX_BATCH]]
        r.raise_for_status()
        data = r.json()
    return [(group or []) for group in data]


async def records_by_ids(ids: list[int]) -> list[dict]:
    """Fetch authoritative AphiaRecords for valid AphiaIDs (<=50)."""
    if not ids:
        return []
    params = [("aphiaids[]", str(i)) for i in ids[:MAX_BATCH]]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{REST_BASE}/AphiaRecordsByAphiaIDs", params=params)
        if r.status_code == 204:
            return []
        r.raise_for_status()
        return [rec for rec in r.json() if rec]
