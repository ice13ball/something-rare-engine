# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""No layer may claim completeness or final authority.

This portal mirrors its sources 1:1 (Michal, 2026-09-10), and that forbids
stating more than the source does as firmly as it forbids stating less. Two
phrasings break the rule on sight, because no Earth-observation dataset can
support either:

  * a completeness claim — "every X on Earth", "all X worldwide"
  * an authority claim   — "the definitive reference", "the authoritative source"

`globalSurfaceWater` carried both: "Every surface water body on Earth ... It is
the definitive reference for understanding water availability". Its OWN
limitations paragraph, three fields later in the same entry, says "30m
resolution means small streams and ponds below ~900m² are invisible" and that
cloud-persistent tropics have lower observation counts. The entry contradicted
itself, and JRC makes neither claim.

⛔ The check runs over EVERY layer in every locale, not the one that was caught.
A guard written for a single known offender finds the next one never.
"""
import json
import pathlib
import re

LOCALES = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "public" / "locales"

#: Fields that are prose about a layer. `label` is a name, not a claim.
_PROSE_FIELDS = ("description", "reading", "source", "updateFreq", "limitations")

_COMPLETENESS = re.compile(
    # ⚠️ {1,4}, not {1,2}: the wording actually shipped was "Every surface
    # water body on Earth" — three words between. The narrower pattern matched
    # nothing, and the fire-test below is what caught it.
    r"\bevery(\s+\w+){1,4}\s+on\s+earth\b"
    r"|\ball\s+\w+\s+(worldwide|on earth|globally)\b"
    r"|\bkażd\w+\s+\w+\s+na\s+(ziemi|świecie)\b"
    r"|\bchaque\s+\w+\s+(sur|de la)\s+terre\b"
    r"|\bjede[sr]?\s+\w+\s+der\s+welt\b",
    re.IGNORECASE)

_AUTHORITY = re.compile(
    r"\bthe (definitive|authoritative|canonical) (reference|source|record)\b"
    r"|\bdefinitywn\w+ (źródł|referencj)\w*"
    r"|\bla référence définitive\b"
    r"|\bdie (maßgebliche|definitive) referenz\b",
    re.IGNORECASE)


def _entries():
    """(locale, layer key, field, text) for every prose string we ship."""
    for loc in sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file()):
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        for key, entry in (d.get("layers") or {}).items():
            if not isinstance(entry, dict):
                continue
            for field in _PROSE_FIELDS:
                v = entry.get(field)
                if isinstance(v, str) and v:
                    yield loc.name, key, field, v


def test_the_sweep_reads_the_field_that_carried_the_claim():
    # ⛔ Narrowing _PROSE_FIELDS is a silent way to disarm this whole file: with
    # the corpus clean, checking fewer fields reddens nothing. `description` is
    # where both claims lived, so its presence is asserted directly.
    assert "description" in _PROSE_FIELDS, (
        "the sweep no longer reads `description`, which is the field that "
        "carried both the completeness and the authority claim"
    )
    assert set(_PROSE_FIELDS) >= {"description", "reading", "limitations"}


def test_the_fixture_reads_a_real_corpus():
    rows = list(_entries())
    assert len(rows) > 100, (
        f"fixture problem: only {len(rows)} prose strings found — the sweep "
        "below would be checking almost nothing"
    )
    assert len({r[0] for r in rows}) >= 2, "fixture problem: fewer than two locales"


def test_the_patterns_would_actually_catch_the_wording_that_was_there():
    # ⛔ Prove the regexes fire. A pattern that matches nothing turns the sweep
    # into a green light that means nothing.
    was_there = ("Every surface water body on Earth tracked from 1984 to 2021 ... "
                 "It is the definitive reference for understanding water availability.")
    assert _COMPLETENESS.search(was_there), "the completeness pattern is dead"
    assert _AUTHORITY.search(was_there), "the authority pattern is dead"


def test_no_layer_claims_to_cover_everything():
    offenders = [f"{loc}/{key}.{field}: {text[:70]}"
                 for loc, key, field, text in _entries()
                 if _COMPLETENESS.search(text)]
    assert not offenders, (
        "these entries claim total coverage, which no Earth-observation dataset "
        f"supports: {offenders}"
    )


def test_no_layer_calls_itself_the_definitive_reference():
    offenders = [f"{loc}/{key}.{field}: {text[:70]}"
                 for loc, key, field, text in _entries()
                 if _AUTHORITY.search(text)]
    assert not offenders, (
        f"these entries crown themselves the authority on their subject: {offenders}"
    )


def test_a_layer_that_states_a_resolution_limit_does_not_also_claim_completeness():
    # The specific self-contradiction that made this worth guarding: an entry
    # whose limitations say things are invisible while its description says it
    # sees everything.
    by_layer = {}
    for loc, key, field, text in _entries():
        by_layer.setdefault((loc, key), {})[field] = text
    offenders = []
    for (loc, key), fields in by_layer.items():
        lim = fields.get("limitations", "")
        if not re.search(r"invisible|niewidoczn|invisibles|unsichtbar", lim, re.IGNORECASE):
            continue
        desc = fields.get("description", "")
        if _COMPLETENESS.search(desc):
            offenders.append(f"{loc}/{key}")
    assert not offenders, (
        f"{offenders} say in one field that features are invisible and in "
        "another that everything is covered"
    )
