# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every program the NOAA archive publishes is either walked or refused on
purpose — and a prefix that disappears must not look like one we skipped.

Counted 2026-09-15: the bucket `noaa-passive-bioacoustic` exposes 29 top-level
prefixes and `PROGRAMS` walked 12 of them. Nothing recorded which 17 were left
out, or why, so "we decided against this one" and "nobody ever looked" occupied
the same empty space. Our own walker found 173 deployment metadata files in
eight of the unlisted prefixes.

The same space hid a worse failure. `ioos/` was emptied by the publisher and
the data moved to `esons/`; our prefix kept pointing at the empty one. The sync
returned success for three and a half months while serving positions fetched on
2026-05-30 — twelve programs share one row count, and a zero hides in a sum.

So two rules, and the pair is what matters:

* every prefix the bucket has is CLASSIFIED — walked, or refused with a reason
  somebody checked;
* every prefix we walk still EXISTS in the bucket.

Neither alone would have caught the `ioos` move.
"""
import httpx
import pytest

from ingestion.acoustic_noaa_archive_ingest import (
    BUCKET_PREFIXES_SEEN,
    NOT_INGESTED,
    PROGRAMS,
    _BUCKET,
    _GCS_LIST,
)


def _walked_roots() -> set[str]:
    """The bucket top-level prefixes our programs actually walk.

    ⛔ Derived from `prefix`, never from the dict key. The `ioos` program walks
    `esons/`; keying off the name would call esons unclassified and ioos alive,
    which is exactly backwards.
    """
    return {cfg["prefix"].split("/", 1)[0] for cfg in PROGRAMS.values()}


def test_every_prefix_in_the_bucket_is_classified():
    walked = _walked_roots()
    unclassified = [p for p in BUCKET_PREFIXES_SEEN
                    if p not in walked and p not in NOT_INGESTED]
    assert unclassified == [], (
        f"{len(unclassified)} bucket prefix(es) are neither walked nor refused: "
        f"{unclassified}. An unlisted prefix is indistinguishable from one we "
        "decided against — which is how seventeen programs went unnoticed. "
        "Add it to PROGRAMS, or to NOT_INGESTED with a reason you checked.")


def test_a_walked_prefix_is_never_also_refused():
    walked = _walked_roots()
    both = sorted(walked & set(NOT_INGESTED))
    assert both == [], (
        f"{both} appear both in PROGRAMS and in NOT_INGESTED. One of the two "
        "is a lie, and the reason text is the half a reader would believe.")


def test_every_refusal_carries_a_reason_somebody_could_check():
    """⛔ A false reason is worse than no reason.

    The point of NOT_INGESTED is that the next reader can disagree with it.
    A placeholder gives them nothing to disagree with while looking settled.
    """
    thin = {}
    for prefix, reason in NOT_INGESTED.items():
        text = (reason or "").strip()
        if len(text) < 30 or text.lower().rstrip(".") in {"todo", "tbd", "n/a", "skip", "not needed"}:
            thin[prefix] = reason
    assert thin == {}, (
        f"these refusals say nothing checkable: {thin}. Write what you "
        "verified — and where you did not verify, the word is 'nieustalone'.")


def test_every_program_we_walk_still_exists_in_the_bucket():
    """⭐ The one that would have caught the `ioos` move on the day it happened.

    A prefix whose publisher removed it does not raise — GCS answers an empty
    list, cheerfully, forever.
    """
    walked = _walked_roots()
    gone = sorted(walked - set(BUCKET_PREFIXES_SEEN))
    assert gone == [], (
        f"we walk {gone}, which the bucket does not list. Either the publisher "
        "moved the data — as it did with ioos/ → esons/ — or the prefix has a "
        "typo. Both produce zero rows and no error.")


def test_the_new_programs_did_not_lose_their_prefixes():
    """The eight added on 2026-09-15, named so a silent deletion is loud."""
    added = {
        "afsc": "afsc/audio/",
        "cornell": "cornell/audio/",
        "mbarc_socal": "mbarc_socal/audio/",
        "mbarc_arctic": "mbarc_arctic/audio/",
        "mbarc_flip": "mbarc_flip/audio/",
        "swfsc": "swfsc/audio/",
        "rutgers_njrmi": "rutgers_njrmi/audio/",
        # ⚠️ No audio tree — a C-POD publishes click detections, and its one
        # metadata file sits at the prefix root.
        "md_wea_cpod": "MD_WEA_CPOD/",
    }
    missing = {k: v for k, v in added.items()
               if PROGRAMS.get(k, {}).get("prefix") != v}
    assert missing == {}, (
        f"these programs are gone or re-pointed: {missing}. Together they were "
        "173 deployment metadata files the ingest had never asked for.")


def test_a_source_key_matches_what_the_database_and_frontend_expect():
    """`source` is a join key, not a display string.

    The program key lands in `acoustic_stations.source` and in the
    `station_id` prefix, and the frontend switches on those strings exactly.
    One uppercase key would render as an unlabelled, unfilterable dot.
    """
    odd = sorted(k for k in PROGRAMS if k != k.lower())
    assert odd == [], (
        f"{odd} are not lowercase. Every other source in acoustic_stations is, "
        "and the frontend's colour switch and filter chips match on the raw "
        "string — a case mismatch fails silently, showing a default-coloured "
        "dot with no chip to turn it off.")


@pytest.mark.asyncio
async def test_the_recorded_prefix_list_still_matches_the_live_bucket():
    """The snapshot above is data, and data goes stale.

    ⛔ Skips only when the bucket cannot be reached. A reachable bucket that
    disagrees is a failure, not a skip: a program the archive ADDS is exactly
    the event this whole file exists to make visible.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.get(
                _GCS_LIST,
                params={"delimiter": "/", "maxResults": 1000, "fields": "prefixes"},
            )
            resp.raise_for_status()
            live = {p.rstrip("/") for p in resp.json().get("prefixes", [])}
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"bucket {_BUCKET} unreachable ({type(exc).__name__}) — not checked")

    assert live, f"bucket {_BUCKET} listed zero prefixes — that is not a healthy answer"

    recorded = set(BUCKET_PREFIXES_SEEN)
    added = sorted(live - recorded)
    removed = sorted(recorded - live)
    assert not added, (
        f"the archive published {len(added)} new prefix(es): {added}. Decide "
        "each one — walk it, or refuse it with a reason — then add it to "
        "BUCKET_PREFIXES_SEEN. Leaving it out is how the last seventeen hid.")
    assert not removed, (
        f"{removed} no longer exist in the bucket. If we walk any of them, the "
        "sync is quietly returning zero rows and keeping the stale ones.")


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ The registry must BE the wiring. Guard the call site, not only the helper.
# ─────────────────────────────────────────────────────────────────────────────

def test_every_configured_program_reaches_the_sync():
    """A program in PROGRAMS that nothing calls is config, not ingestion.

    ⛔ Until 2026-09-15 the sync chain in `domains/acoustic.py` carried its own
    hand-written list of twelve `(name, fetcher)` rows. Adding a program to
    PROGRAMS therefore did nothing at all, and there was no error to say so —
    a source missing from a list cannot fail, it simply never runs, and its
    rows age quietly. All eight programs added that day would have landed in
    exactly that hole.
    """
    from domains import acoustic

    wired = {name for name, _ in acoustic.station_sources()}
    missing = sorted(set(PROGRAMS) - wired)
    assert missing == [], (
        f"{missing} are configured in PROGRAMS but never fetched by the "
        "station sync. Nothing anywhere would have reported this.")


def test_the_sync_asks_the_registry_rather_than_a_copy_of_it():
    """⛔ The other half: a list derived from PROGRAMS proves nothing if the
    sync stopped reading it. This replaces the registry with a sentinel and
    checks the sync's own source list changes with it — a re-typed list would
    not move."""
    from unittest.mock import patch

    from domains import acoustic

    sentinel = {"probe_program_xyz": {
        "display": "probe", "operator": "probe", "prefix": "probe/audio/",
        "portal": "https://example.invalid/", "skip_mobile_platforms": True,
    }}
    with patch.dict(PROGRAMS, sentinel, clear=False):
        wired = {name for name, _ in acoustic.station_sources()}

    assert "probe_program_xyz" in wired, (
        "adding a program to the registry did not change what the sync walks — "
        "the chain is reading a copy, so the registry is decoration")


def test_the_walked_program_count_is_not_silently_shrinking():
    """A floor, not an equality: new programs are welcome, losses are not."""
    from domains import acoustic

    # ⚠️ NOT a uniqueness check on the names. `fram` appears twice on purpose:
    # one NOAA-archive station plus seven HAUSGARTEN moorings, which is why
    # production holds exactly 8 rows under that source. The upsert key is
    # `station_id`, not `source`, so the two fetchers coexist rather than
    # overwrite. An assertion that they must be unique would have been a true
    # test of a false rule.
    assert len(PROGRAMS) >= 20, (
        f"only {len(PROGRAMS)} NOAA-archive programs are configured; there "
        "were 20 after the 2026-09-15 additions. Somebody removed some.")


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ The database's own opinion about which sources exist.
# ─────────────────────────────────────────────────────────────────────────────

def test_every_source_the_sync_can_emit_is_allowed_by_the_check_constraint():
    """A source the ingest produces and the table forbids writes nothing.

    ⛔ `acoustic_stations.source` is CHECK-constrained to a hand-written list.
    The sync inserts row by row inside a try/except, so a CHECK violation
    becomes one warning per row and a run that ends reporting success — the
    table simply never gains the source. All eight programs added on
    2026-09-15 would have landed in that hole: the ingest walks them, the
    mappers build rows, and Postgres rejects every one.

    `schema/` may not import `domains/`, so the two lists cannot be derived
    from each other. This test is the derivation.
    """
    from domains import acoustic
    from schema.acoustic import ACOUSTIC_SOURCES

    emitted = {name for name, _ in acoustic.station_sources()}
    forbidden = sorted(emitted - set(ACOUSTIC_SOURCES))
    assert forbidden == [], (
        f"the sync emits {forbidden}, which the CHECK constraint on "
        "acoustic_stations.source rejects. Every row would be refused by the "
        "database and swallowed by the sync's per-row handler.")


def test_the_constraint_list_does_not_outlive_its_sources():
    """The other direction — a name nothing can produce any more.

    ⚠️ Not a failure on its own (a retired source's rows may still be in the
    table), so this asserts the list stays explainable rather than minimal:
    every allowed value is either emitted by the sync today, or one of the
    two documented aliases.
    """
    from domains import acoustic
    from schema.acoustic import ACOUSTIC_SOURCES

    emitted = {name for name, _ in acoustic.station_sources()}
    # HAUSGARTEN writes under 'fram'; the ISA/IMS ingests write their own.
    orphans = sorted(set(ACOUSTIC_SOURCES) - emitted)
    assert orphans == [], (
        f"{orphans} are allowed by the constraint but no fetcher produces "
        "them. Either a source was removed from the sync without a word, or "
        "the list has grown a name that never meant anything.")


def test_the_constraint_sql_refuses_anything_that_is_not_a_bare_token():
    """⛔ The list is interpolated into DDL. A member with a quote in it would
    be a broken statement at best."""
    import schema.acoustic as sa

    assert "'md_wea_cpod'" in sa._sources_sql()
    original = sa.ACOUSTIC_SOURCES
    try:
        sa.ACOUSTIC_SOURCES = original + ("bad'; DROP TABLE acoustic_stations; --",)
        with pytest.raises(ValueError, match="bare lowercase token"):
            sa._sources_sql()
    finally:
        sa.ACOUSTIC_SOURCES = original
