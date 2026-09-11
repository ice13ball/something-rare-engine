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

## Derived products are labelled

Some layers are models this platform computed, not measurements it received.
These carry an explicit banner and are never presented as observations:

- `vme-suitability` — a MaxEnt habitat-suitability model
- `coral-acid-exposure` — modelled exposure derived from the above
- `noise-risk` — a derived index combining two independent noise datasets

A whole layer is not the only thing that can be derived. A single **field** on an
otherwise pass-through layer can be ours too, and then it says so:

- `chess.habitat_type` — a keyword classification this platform runs over
  ChEssBase's free-text ecosystem description. It resolves to `whale_fall`,
  `seep` or `vent`, and to `unclassified` when no keyword matches. ⛔ The
  fallback must never carry the name of a real habitat: labelling it `omz`
  once put an oxygen-minimum-zone claim on 3,605 of 3,715 records (97.0%)
  that the classifier has no pattern to detect at all.

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
