# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The layer must not deny a filter its own sync applies.

`obisSpecies` (the legend entry for the `biodiversity-hotspots` layer) said:

    "Every quality-controlled deep-sea species occurrence in the OBIS Open Data
     archive — no curated species shortlist, no taxonomic exclusions"
    "We deliberately do NOT filter by taxon, dataset, country, or year"

The sync says the opposite, in its own words, in four places:

    obis_sync.py:11   "Filter strategy: curated species list derived from
                       existing biodiversity_hotspots rows"
    obis_sync.py:195  species = SELECT DISTINCT scientific_name
                                FROM biodiversity_hotspots
    obis_sync.py:204  "no species in DB — nothing to filter parquet by"
    obis_parquet.py:11 "Curation happens at the SPECIES level (14k deep-sea-
                        relevant taxa from our curated list)"

⚠️ The design is sound and the ingest documents it honestly, including its
sharpest consequence: "the curated list — being derived from this very table —
could never learn a species the floor had already excluded". Corals are the
deliberate exception, matched by taxonomic rank at any depth to break that
closure. Only the user-facing copy was wrong, and it was wrong in the direction
that flatters: claiming an unfiltered mirror of OBIS.

Live on production 2026-09-10: 34,273,149 rows, 77,339 distinct species.

⛔ Derived from the code, not hardcoded. If the sync ever genuinely stops
filtering by species, these tests stop demanding the disclosure instead of
having to be deleted.
"""
import json
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[1]
LOCALES = ROOT.parent / "frontend" / "public" / "locales"
SYNC    = ROOT / "ingestion" / "obis_sync.py"
PARQUET = ROOT / "ingestion" / "obis_parquet.py"

#: Wording, in each locale we ship, that denies the filter the sync applies.
_DENIALS = re.compile(
    r"no curated species shortlist|no taxonomic exclusions"
    r"|deliberately do NOT filter by taxon"
    r"|bez wyselekcjonowanej listy gatunk|NIE filtrujemy według taksonu"
    r"|sans liste d'espèces sélectionnée|ne filtrons délibérément pas par taxon"
    r"|ohne kuratierte Artenliste|filtern bewusst nicht nach Taxon",
    re.IGNORECASE)


def _sync_filters_by_species() -> bool:
    src = SYNC.read_text(encoding="utf-8")
    return bool(re.search(
        r"SELECT DISTINCT scientific_name\s+FROM biodiversity_hotspots", src))


def _locales():
    return sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file())


def _entry(loc):
    d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
    return d["layers"]["obisSpecies"]


def test_the_fixture_reads_the_sync_and_every_locale():
    assert SYNC.is_file() and PARQUET.is_file(), "fixture problem: ingest files missing"
    assert len(_locales()) >= 2, "fixture problem: fewer than two locales"
    for loc in _locales():
        assert _entry(loc), f"fixture problem: {loc.name} has no obisSpecies entry"


def test_the_denial_pattern_would_catch_the_wording_that_shipped():
    # ⛔ Prove the pattern fires. A completeness guard shipped earlier this week
    # with a pattern too narrow to match the very sentence it was written for.
    for was_there in (
        "no curated species shortlist, no taxonomic exclusions",
        "We deliberately do NOT filter by taxon, dataset, country, or year",
        "bez wyselekcjonowanej listy gatunków",
        "ohne kuratierte Artenliste",
    ):
        assert _DENIALS.search(was_there), f"the pattern misses {was_there!r}"


def test_no_locale_denies_a_species_filter_the_sync_applies():
    if not _sync_filters_by_species():
        return                      # the claim would be true; nothing to guard
    offenders = {}
    for loc in _locales():
        blob = "\n".join(str(v) for v in _entry(loc).values())
        hit = _DENIALS.findall(blob)
        if hit:
            offenders[loc.name] = hit[:2]
    assert not offenders, (
        "the sync filters OBIS by a curated species list and these locales deny "
        f"it: {offenders}"
    )


def test_every_locale_discloses_the_species_filter_positively():
    # ⛔ Deleting the denial is not enough. Saying nothing leaves a reader with
    # the same wrong impression the false sentence gave them.
    if not _sync_filters_by_species():
        return
    missing = []
    for loc in _locales():
        blob = "\n".join(str(v) for v in _entry(loc).values())
        if "biodiversity_hotspots" not in blob:
            missing.append(loc.name)
    assert not missing, (
        f"{missing} never tell the reader the species list is derived from the "
        "layer's own contents, which is what bounds its coverage"
    )


def test_the_coral_exception_is_explained_where_it_is_the_reason_for_the_bound():
    # The ingest's own justification: corals are matched by rank precisely
    # because the self-derived list could never learn a species the depth floor
    # excluded. A reader told about the bound deserves the escape hatch too.
    parquet = PARQUET.read_text(encoding="utf-8")
    assert "_CORAL_ORDERS" in parquet, "fixture problem: the coral path is gone"
    missing = [loc.name for loc in _locales()
               if not re.search(r"coral|koralow|corau|korallen",
                                "\n".join(str(v) for v in _entry(loc).values()),
                                re.IGNORECASE)]
    assert not missing, f"{missing} do not mention the coral exception at all"
