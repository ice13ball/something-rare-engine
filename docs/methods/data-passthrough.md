# How this platform handles units

This platform is a conduit. It shows each measurement as the source published
it, with the unit the source declared. Where a source declares no unit, this is
stated rather than filled in.

## What this means in practice

- No measured value is converted to a different unit anywhere between fetch and
  display.
- A column name is not treated as evidence of a unit. Where a source ships a
  unit field, that field is stored and shown; where it does not, the value is
  presented without a unit and labelled as such.
- Quality flags published by a source are requested, stored, and honoured.

## The one exception

A source's documented no-data code — WRI Aqueduct's `-9999`, for example — is
stored as SQL `NULL`. `NULL` is that code's faithful rendering in a database
that has a way to say "no value"; storing `-9999` in a 0-5 score column would
add meaning the source did not intend.

## Coordinates are not corrected either

The same rule governs position. Where a source publishes a coordinate this
platform renders that coordinate, including when it is visibly wrong.

Until 2026-09-22 there was one exception, and it is worth naming because it was
removed rather than kept. ChEssBase publishes a whale-fall record,
`Grey Whale Carcass, San Diego Trough`, at 33.350 N / 117.300 W — a point 122 m
above sea level in inland California, while the same record states a depth of
1240 m. This platform used to substitute the position given by Smith & Baco
(2003), 32.5833 N / 117.4833 W, where the seabed is 1220 m down.

That substitution was accurate and is gone anyway. A platform that quietly
repairs its sources cannot be checked against them, and the repair concealed
exactly the kind of defect a reader might want to find. The record now renders
where ChEssBase puts it: on land.

Source errors are reported to the publisher instead. The coordinate errors
found in ChEssBase were reported to EurOBIS on 2026-09-22 and are tracked by
them under ticket `EUROBIS-959`.

A second correction was removed on 2026-09-23, and this one was wrong as well
as unwanted. The NOAA passive-acoustic ingest negated any longitude between 100
and 180 in a "Pacific" sea area, to repair a few US Navy sites off Southern
California published as `118.78` instead of `-118.78`. The western Pacific has
positive longitudes too. The rule moved three NOAA PIFSC moorings across the
ocean: Wake_S, published at 166.31 E, was drawn about 2,900 km east of Wake
Island, and Saipan_A and Tinian_A about 7,400 km east of the Marianas. All
three now render where NOAA puts them, and so do the Navy sites, at the
longitudes they were published with.

A longitude above 180 is still rewritten as its equivalent below it (`241.22`
becomes `-118.78`). That names the same meridian in a different notation and
moves nothing.

## Derived products are labelled

Some layers are models this platform computed, not measurements it received.
These carry an explicit banner and are never presented as observations:

- `vme-suitability` — a MaxEnt habitat-suitability model
- `coral-acid-exposure` — modelled exposure derived from the above
- `noise-risk` — a derived index combining two independent noise datasets

A whole layer is not the only thing that can be derived. A single **field** on an
otherwise pass-through layer can be ours too. One such field existed here, and on
**2026-09-21 it was removed** rather than improved:

- `chess.habitat_type` — **removed.** It was a keyword classification this platform
  ran over ChEssBase's free-text `locality`, resolving to `whale_fall`, `seep`,
  `vent`, or `unclassified`. It no longer exists in the database rows we write, the
  API response, the map, or the Area Export.

  It was removed because **ChEssBase publishes no habitat field at all.** Sampled
  from the GBIF API on 2026-09-21, the Darwin Core terms that could carry one —
  `habitat`, `waterBody`, `occurrenceRemarks`, `samplingProtocol`,
  `dynamicProperties` — are empty in 100 of 100 records. There was no source value
  to pass through, so every value in that column was a claim of ours wearing the
  source's clothes.

  It was also wrong, in both directions and measurably:

  | | |
  |---|---|
  | rows that fell through to `unclassified` | 3,605 of 3,715 (97.0%) |
  | `Blake Ridge`, a gas-hydrate seep province | labelled `vent`, because "ridge" |
  | `Mariana fields` | never matched `\bfield\b`, losing 225 rows to a plural |
  | chess records within 5 km of a catalogued vent | 1,205 |
  | …of those, kept by the `habitat_type = 'vent'` filter | 19 |
  | …so hydrothermal vents carrying any species at all | 1 of 721 |

  A further group could not be labelled correctly under any fix: at least 13
  localities are **sunken-wood falls** — the Oregon-coast station series carries
  *Xylophaga*, the wood-boring bivalve — and the four-value vocabulary had no slot
  for them. This dataset's own export description already named wood falls.

  ⛔ **Nothing replaces it.** The species list is better evidence than any label
  this platform could compute: *Bathymodiolus azoricus* on a record identifies a
  hydrothermal vent community more precisely than a word in a place name ever did.
  Re-introducing a derived habitat label is a decision for the maintainer, not a
  refactor.

- `tailings_dams.risk_class` — **removed 2026-09-22.** It was a six-tier scale
  (Extreme / Very High / High / Significant / Medium / Low) this platform derived
  by keyword-matching the hazard rating published in the Global Tailings Portal.

  Unlike the field above, the source here *does* publish a rating — so the defect
  was not invention but **flattening**. Sampled from the live API on 2026-09-22,
  the source carries 120 distinct rating strings drawn from **255 different
  classification systems**: the Canadian Dam Association, ANCOLD, SANS 10286,
  Anglo American's internal standard, "We follow the Japanese law (design
  standard)", and 250 more. "High" under one system is not "High" under another,
  and collapsing them into a single ordinal asserted a comparability that no
  source claims.

  Worse, the field that records *which* system produced a rating —
  `classification_system`, present on 2,139 of 2,144 facilities — was being
  fetched and discarded, along with 17 other published fields. A reader was shown
  our word and denied the one piece of information that would let them judge it.

  What is shown now is the operator's own rating verbatim, beside the name of the
  system it was issued under. Both come from the source; neither is ranked,
  scored, or coloured on a gradient by this platform.

## Underwater noise: the 80 dB reference and span

The underwater-noise layer normalises EMODnet's continuous sound pressure
level (SPL, dB re 1 uPa) onto a 0–1 scale using an 80 dB reference floor and
an 80 dB span. Both numbers are this platform's presentation choice for how
to spread the source values across the 0–1 range used elsewhere on the map —
they are not a property of the EMODnet source, which publishes SPL in dB
with no such floor or span attached.

## Known gaps

- _(none currently recorded)_

OpenAQ's per-sensor unit **used to be** the entry here. It no longer is: the
sync now reads `units` from each sensor's parameter record, stores it beside the
value, and `/air-quality` returns a per-pollutant unit map, so a reader is told
whether an ozone figure is ppm or ppb instead of being shown a hardcoded label.
A missing unit stores `NULL` and is shown as absent — never guessed from the
pollutant name.

## Sampling time

The same rule that governs units governs time: we show what the source gave.

A sample carries a `date_precision` that records how precisely the source
dated it. It is the only derived field on this path, and it describes the
source rather than the sample.

| `date_precision` | meaning | rendered as |
|---|---|---|
| `day` | source gave a calendar day | `2008-08-12` |
| `month` | source gave month, not day | `2008-08` |
| `year` | source gave year, not month | `2008` |
| `campaign` | no sample date; only a cruise window | `campaign: 2008-06-01 → 2008-09-15` |
| `none` | source gave no date at all | `no date at source` |

The words in that table — "campaign", "no date at source" — are localised, so
a reader of the German page sees German. The numbers are not: a date renders
as 2008-08-12 in every language, and the order of the fields never changes.
Anything rendering these must take the words from the translation catalogue
and leave the numeric format alone.

We **never widen** a date: a year does not become 1 January.
We **never round** a date away: a calendar day is not displayed as a decade.

A decade is a filter bucket, computed as `year // 10 * 10`. It is never shown
as something the source stated.

Three things that look like a sampling date and are not, so we never present
them as one: the date we synchronised the file, the date the file was created,
and the year the describing paper was published.
