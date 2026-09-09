# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""When each layer's data is FROM — the anchor a modeller needs before pooling it.

⛔ THIS IS NOT ABOUT DISPLAYING A DATE. It answers one question: *may these values
be combined with recent data, or are they a different state of the world?* A carbon
field that mixes a 1934 station with a 2018 station into one interpolated surface
teaches a model that those are the same ocean. IO PAN raised exactly this on
2026-09-04 and it is the reason this table exists.

⭐ **Any time frame beats none, and precision is not the point.** A 48-year range is
useful; a bare publication year is useful; silence is not. So the unit here is a
YEAR span, not a date — a year is what the "can I pool these?" decision actually
turns on, and pretending to a day we were not given would break the passthrough
rule in `docs/methods/data-passthrough.md`.

## Two tiers, and why the second one exists

  Tier 1 — per record: the sample date or window, where the source dates its rows
           (`date_precision`, five levels, see the methods doc).
  Tier 2 — per layer: THIS table. The span of the data THIS LAYER SERVES, cited
           to the publisher wherever the publisher states it. Where our ingest
           takes a narrower window than the upstream release, the narrower one
           is the truth for a modeller and the publisher's wider claim goes in
           `wording` — WOD is the case: NCEI's release reaches back to 1772, we
           ingest from 1900.

Tier 2 is not a fallback for tier 1; it is a different fact, and it is often
present when tier 1 is absent. ChEssBase is the case that proved it: not one of
its 3,715 occurrence records carries `eventDate` — verified four ways against the
live GBIF API — yet the GBIF *dataset* record states
`temporalCoverages: [{start: 1977-01-01, end: 2025-09-15}]`. Per record: nothing.
Per dataset: a 48-year anchor. Looking only at the record level answers the wrong
question and reports "no date" about data that is perfectly well dated.

## `kind` is the field that actually answers the modelling question

Two layers can both say "1955–2017" and mean incompatible things:

  observations  dated measurements spread across the span. A model MAY filter by
                period, because each row carries its own time.
  climatology   ONE value per cell, averaged over the span. ⛔ Cannot be filtered
                by period at all, and must never be pooled with dated observations
                as though contemporaneous. This is the distinction that makes a
                naive merge wrong.
  modelled      a derived product; the span is that of its INPUTS, not of any
                measurement campaign.
  compilation   assembled from many independent studies; the span is the
                bibliography's, and per-record dating is partial or absent.
  publication   only a release year is known. Weak, but still an anchor.

⛔ `wording` is stored VERBATIM as the publisher states it. We never paraphrase a
publisher's temporal claim into our own words — if the source says "1991–2020
climatological mean" that is what a citing scientist must see, not our gloss.
`source_url` and `verified_on` are there so any row can be re-checked rather than
believed.
"""
from __future__ import annotations

import datetime
import logging
from typing import NamedTuple

import db

log = logging.getLogger(__name__)


class Coverage(NamedTuple):
    layer_id: str
    start_year: int | None
    end_year: int | None
    kind: str
    wording: str
    source_url: str
    verified_on: str


KINDS = ("observations", "climatology", "modelled", "compilation", "publication")


DDL = """
CREATE TABLE IF NOT EXISTS layer_temporal_coverage (
    layer_id     TEXT PRIMARY KEY,
    start_year   INTEGER,
    end_year     INTEGER,
    kind         TEXT NOT NULL,
    wording      TEXT NOT NULL,
    source_url   TEXT,
    verified_on  DATE NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT layer_temporal_coverage_kind_chk
      CHECK (kind IN ('observations','climatology','modelled','compilation','publication')),
    -- A span that ends before it starts is a data-entry slip, not a coverage.
    CONSTRAINT layer_temporal_coverage_order_chk
      CHECK (start_year IS NULL OR end_year IS NULL OR start_year <= end_year)
)
"""


# ─────────────────────────────────────────────────────────────────────────────
# The curated table. Every row was read at the SOURCE, not inferred from our own
# database — what we happen to hold says nothing about what the publisher covers.
# A layer with no row here is a gap that shows as "unknown", never as "none".
# ─────────────────────────────────────────────────────────────────────────────
COVERAGE: tuple[Coverage, ...] = (
    Coverage(
        layer_id="chess",
        start_year=1977, end_year=2025,
        kind="compilation",
        wording="temporalCoverages: range start 1977-01-01, end 2025-09-15",
        source_url="https://api.gbif.org/v1/dataset/dc5abc9f-84d5-4046-a3ef-9ab24ae53756",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="mosaic-sediment",
        start_year=1950, end_year=2020,
        kind="compilation",
        wording="Out of the 21,539 sediment cores stored in the database, 68% provide "
                "information of the sampling year, spanning from the 1950s until 2020",
        source_url="https://doi.org/10.5194/essd-15-4105-2023",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="arctic-sediment-carbon",
        start_year=1934, end_year=2018,
        kind="compilation",
        # ⚠️ DERIVED, and the wording says so. The publisher states no dataset-level
        # range anywhere we could find — not on the Bolin dataset pages, not in the
        # ESSD paper text we could index. The tempting fallback is the version-2
        # publication year, 2021, and it would be WORSE than nothing here: it would
        # present a collection reaching back to 1934 as recent. So the span is taken
        # from the source file's own YEAR column instead, which is the source's data
        # even though it is not the source's sentence.
        wording="no dataset-level range stated by the publisher; span read from the "
                "source file's own YEAR column (4,304 of 4,496 stations dated), "
                "CASCADE v2 published 2021-06-08",
        source_url="https://bolin.su.se/data/cascade-surface-sediment-2",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="arctic-catchments",
        start_year=1990, end_year=2019,
        kind="modelled",
        wording="calculated for each watershed from 1 January 1990 to 31 December 2019 "
                "(ERA5-Land runoff/temperature/precipitation); permafrost fraction input "
                "spans 2000-2016",
        source_url="https://doi.org/10.5194/essd-15-541-2023",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="permafrost-thaw",
        start_year=1950, end_year=2025,
        kind="compilation",
        # One layer, two upstreams. The span is the Alaska database's stated one; ARTS
        # publishes no dataset-level range, but it does date every feature (BaseMapDate
        # is an imagery WINDOW, e.g. "2020-07-05,2020-08-20", present on every object
        # in the sample checked 2026-09-08), so its rows anchor themselves.
        wording="This database spans observations from 1950 through present "
                "(Alaska Permafrost Thaw Database v2.0, 44 sources). ARTS v6.0.0 states "
                "no dataset range but carries a per-feature imagery window.",
        source_url="https://doi.org/10.5281/zenodo.16996415",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="sios-svalbard",
        start_year=2004, end_year=2021,
        kind="compilation",
        # A catalogue, not one collection: each of the ~25 datasets carries its own
        # temporal extent, and those are already stored per row in sios_datasets.
        wording="catalogue of ~25 datasets, each with its own temporal_extent; sampled "
                "extents run 2004-05-07 to 2021-09-27, most of them 2017-2021",
        source_url="https://sios-svalbard.org/rest/stations/data.json",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="arctic-rivers",
        start_year=2003, end_year=None,
        kind="observations",
        # end_year is deliberately open: ArcticGRO is an ongoing monitoring programme,
        # and stamping it with this year would age into a lie the moment nobody updates
        # this file.
        wording="Since 2003, ArcticGRO has provided essential data... Data are "
                "frequently updated. PANGAEA CAA series adds 2016-08-14 to 2019-08-13.",
        source_url="https://arcticgreatrivers.org/data",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="seabed-substrate",
        start_year=2015, end_year=2015,
        kind="publication",
        # ⚠️ The weakest anchor in this table, and that is the finding. The grid is a
        # synthesis of seabed samples collected over many decades; the publisher states
        # only when the synthesis was published, never when the samples were taken.
        wording="published online 5 Aug 2015 (Geology 43(9)); no underlying-sample "
                "collection period stated by the publisher",
        source_url="https://doi.org/10.1130/G36883.1",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="woa-climatology",
        start_year=1965, end_year=2022,
        kind="climatology",
        # ⛔ ONE release name, THREE different averaging windows. This is the single
        # most dangerous row in the table: a user who reads "WOA23" and assumes one
        # period will pool a 1971-2000 oxygen field with a 1991-2020 temperature field
        # as if they were the same decade. The span above is the outer envelope; the
        # per-variable windows are the fact that matters.
        wording="temperature/salinity: Annual 1991-2020 (duration P30Y) · "
                "oxygen/AOU/saturation: Annual 1971-2000 · "
                "nutrients (phosphate/silicate/nitrate): Annual 1965-2022 "
                "— read from the WOA23 NetCDF global attributes",
        source_url="https://www.ncei.noaa.gov/products/world-ocean-atlas",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="oxygen-deox",
        start_year=1971, end_year=2018,
        kind="climatology",
        # The layer IS a difference between two periods, so a single span is only the
        # envelope. Both ends must be visible or the change being shown is unreadable.
        wording="recent field: ISAS20 yearly mean of Argo dissolved oxygen over "
                "2014-2018 · baseline: WOA23N 1971-2000 'Climate Normal'. "
                "The deoxygenation delta is the difference between those two.",
        source_url="https://doi.org/10.17882/52367",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="memento",
        start_year=1971, end_year=2016,
        kind="compilation",
        # ⚠️ Span DERIVED, and the wording says so. The publisher's only temporal
        # statement is a 2015 cut-off, which our copy already outruns — it holds 2016
        # samples. Quoting the 2015 sentence alone would understate the layer.
        wording="publisher states only a cut-off: 'measurements included in MEMENTO as "
                "of January 2015' (Kock & Bange, Eos 2015). Span read from the source's "
                "own sample_time values: 1971-06-09 to 2016-12-19.",
        source_url="https://doi.org/10.1029/2015EO023665",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="geotraces",
        start_year=2005, end_year=2023,
        kind="compilation",
        wording="temporalCoverage: start 2005-01-10, end 2023-01-24 (IDP2025, "
                "publication date 2025-11-17)",
        source_url="https://doi.org/10.5285/42c92148-8d03-8be6-e063-7086abc09f0c",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="wod-oxygen",
        start_year=1900, end_year=2025,
        kind="compilation",
        # ⛔ 1900 is OUR ingestion window, not NCEI's release. The publisher's claim is
        # far wider and is quoted so the difference is visible rather than silently
        # inherited — a modeller must not be told this layer reaches 1772 when it does
        # not.
        wording="NCEI states 'WOD data spans from Captain Cook's 1772 voyage to the "
                "contemporary Argo period' (WOD23). This layer ingests from 1900 "
                "onward and holds profile dates 1900-05-26 to 2025-04-23.",
        source_url="https://www.ncei.noaa.gov/products/world-ocean-database",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="methane-seeps",
        start_year=1984, end_year=2019,
        kind="compilation",
        # Weakest of the geochemical rows. The compilation is frozen; the observation
        # years exist on barely a quarter of it, so the span is thinly attested at the
        # start and the wording has to say that out loud.
        wording="compilation frozen at the source ('SEAFLEAs_Feb2019_AllPoints'); the "
                "publisher states no start year. Observation years present on only "
                "2,890 of 10,385 records, running 1984-2016.",
        source_url="https://doi.org/10.1029/2019GC008747",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="ocean-carbon",
        start_year=1972, end_year=2013,
        kind="compilation",
        # ⛔ THE VERSION IN THE URL IS NOT THE DATA'S VINTAGE. glodap_carbon.py pulls
        # from a path containing "v2.2023", which is glodap.info's current hosting
        # folder — the mapped product itself is GLODAPv2.2016b and its observations
        # stop in 2013. Reading "2023" off the URL would age this layer by a decade
        # in the wrong direction.
        wording="GLODAPv2.2016b Mapped Climatology — 'covers all ocean basins over "
                "the years 1972 to 2013'. The v2.2023 in our download URL is the "
                "host's folder, not the data version.",
        source_url="https://doi.org/10.5194/essd-8-325-2016",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="ocean-co2-surface",
        start_year=1957, end_year=2026,
        kind="compilation",
        wording="SOCATv2026, temporalCoverage 1957-10-22/2026-01-31 (NCEI Accession "
                "0315110). Release year and observation span are different numbers: "
                "the 2026 release covers 69 years.",
        source_url="https://doi.org/10.25921/8dba-fr90",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="marine-carbon",
        start_year=1965, end_year=2026,
        kind="modelled",
        # ⛔ THE WIDEST SPAN IN THIS TABLE AND THE LEAST MEANINGFUL AS ONE NUMBER.
        # Four differently-dated inputs, so the range is only their envelope. The
        # enumeration below is the actual answer: a modeller who reads "1965-2026"
        # as one coherent record will combine a 1972-2013 interior-carbon field with
        # a 2020s-only surface-CO2 bin and never notice.
        wording="synthesis of four inputs with DIFFERENT spans, not one record: "
                "GLODAPv2.2016b interior carbon 1972-2013 · SOCATv2026 surface CO2, "
                "2020s decadal bin only · WOA23 physical/nutrients, itself three "
                "windows (T/S 1991-2020, O2 1971-2000, nutrients 1965-2022) · "
                "ISAS20 oxygen 2014-2018.",
        source_url="https://glodap.info/index.php/mapped-data-product/",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="ocean-acidification",
        start_year=1972, end_year=2013,
        kind="compilation",
        # Inherits GLODAP exactly and derives nothing of its own: the served OmegaA/
        # OmegaC come straight from GLODAP's own NetCDF variables. PyCO2SYS is in the
        # tree but only for an internal preindustrial estimate and a QC check — it
        # never produces the value shown, so it adds no second vintage here.
        wording="OmegaA/OmegaC read verbatim from GLODAPv2.2016b's own NetCDF "
                "variables — same synthesis, same 1972-2013 span as ocean-carbon.",
        source_url="https://doi.org/10.5194/essd-8-325-2016",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="cumulative-human-impact",
        start_year=2010, end_year=2020,
        kind="modelled",
        # ⛔ THE ONE THAT WAS ACTIVELY MISLEADING. The panel calls this "present-state"
        # and says "no future projection" — both true of the file we load — but NCEAS's
        # own "current" layer is a 2010-2020 composite, and we never said so. A reader
        # in 2026 sees "present state" and reasonably reads "now"; the data is 6-16
        # years older than that. Verified 2026-09-08 against the KNB package metadata.
        wording="'We mapped pressure data at 10 km resolution for both current "
                "(roughly 2010-2020) and future (typically 2041-2060, or midcentury) "
                "pressure intensities' — Halpern et al. 2025. This layer loads the "
                "CURRENT file only; the midcentury projections are deliberately not "
                "ingested.",
        source_url="https://doi.org/10.5063/F18K77KZ",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="vme-suitability",
        start_year=1873, end_year=2024,
        kind="modelled",
        # ⛔ THE SPAN IS THE ENVELOPE OF A MODEL, NOT OF A MEASUREMENT. Training
        # occurrences run 1873-2024 (98% of them 2000-2020), and the six predictors
        # come from THREE non-overlapping windows joined into one feature vector as
        # though simultaneous. No timestamp threads through the fit at all.
        #
        # That mismatch is normal SDM practice — a time-matched deep-ocean climatology
        # for the older decades does not exist at this resolution — but it was nowhere
        # disclosed, which is the actual defect.
        wording="MaxEnt fit. Occurrences (NOAA DSCRTP) 1873-2024, ~98% of them "
                "2000-2020. Predictors from three non-overlapping windows: WOA23 "
                "temperature/salinity 1991-2020 · ISAS20 oxygen 2014-2018 · GLODAP "
                "aragonite saturation, reference epoch ~2002. Depth (GEBCO 2024) and "
                "substrate (Dutkiewicz 2015) are treated as time-invariant.",
        source_url="https://something-rare.com/api-docs",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="coral-acid-exposure",
        start_year=1873, end_year=2024,
        kind="modelled",
        # Inherits vme-suitability's envelope because it is weighted by it. Its own
        # construction is a snapshot comparison — GLODAP present epoch (~2002) against
        # a pre-1850 preindustrial reconstruction — and that part is already disclosed
        # in docs/methods/coral-acid-exposure-methods.md. What was missing is that the
        # habitat weight it multiplies comes from a model with the mismatch above.
        wording="snapshot comparison, not a trend: GLODAPv2.2016b present epoch "
                "(~2002) against a pre-1850 preindustrial reconstruction, weighted by "
                "vme-suitability — whose own predictors span three non-overlapping "
                "windows. ⛔ CC-BY-NC lineage via seabed-lithology.",
        source_url="https://doi.org/10.5194/essd-8-325-2016",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="noise-risk",
        start_year=None, end_year=2024,
        kind="modelled",
        # start_year is deliberately open: the cetacean side is an unbounded OBIS pull
        # with no date filter anywhere, so there is no start to state. Writing one
        # would be a guess, and the whole point of this table is that a guess is worse
        # than an admission.
        # ⚠️ Corrected 2026-09-08. The earlier wording described THREE inputs and
        # ended "No observation-date column exists in this pipeline." Both were
        # wrong. The impulsive component is a separate EMODnet product whose own
        # `year` column spans 2014-2022 — counted at the source that day: 2014:63,
        # 2015:1283, 2016:1184, 2017:769, 2018:1010, 2019:1352, 2020:973, 2021:1684,
        # 2022:27 across 8,345 usable rows. `noise_ingest.py` was requesting that
        # column over the network and reading only the two beside it, so a cell whose
        # maximum came from 2015 sat next to one from 2021 with nothing recording
        # which. The year is kept per cell now; this row states the pooled span
        # because a per-cell maximum over nine years is still a pooled figure.
        wording="multiplies FOUR inputs of different vintage with no date join: "
                "EMODnet continuous SPL filtered to 2023 onward · EMODnet impulsive "
                "noise (Pulse Block Days) spanning 2014-2022, of which each cell "
                "keeps only its all-time maximum · cetacean density from an OBIS "
                "pull with NO date filter, spanning decades of opportunistic "
                "sightings · IUCN Red List 2024 status applied to all of them.",
        source_url="https://emodnet.ec.europa.eu/en/human-activities",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="monitoring-density",
        # ⛔ NOT null/null. Empty bounds render as "period not established", which
        # reads as a gap in our knowledge — the opposite of the truth here, where the
        # unbounded span IS the design. Stating 1900-ongoing warns a modeller that the
        # count includes century-old records, which is exactly what they need to know.
        start_year=1900, end_year=None,
        kind="compilation",
        # ⭐ The one layer where pooling decades is CORRECT rather than a defect: it
        # counts how much baseline monitoring has ever happened at a place. The gap was
        # that "baseline" was carrying that meaning implicitly. Said plainly here.
        wording="counts every monitoring record ever logged at a location across 15 "
                "sources, not current activity — an all-time cumulative count, which "
                "is what 'baseline' means here. Pooling a 1930s cruise with a 2024 "
                "float is the intent, not a mismatch. The earliest contributing record "
                "we hold is 1900 (World Ocean Database).",
        source_url="https://something-rare.com/api-docs",
        verified_on="2026-09-08",
    ),
    # ── LIFE & GEOLOGY menu group ────────────────────────────────────────────
    # Verified 2026-09-08 at the live source, not from our own tables: what we
    # happen to store says nothing about what the publisher covers.
    Coverage(
        layer_id="hydrothermal-vents",
        # ⭐ The only layer in this group with a real per-record date already in
        # production and already visible in the popup: `discovery_year` is filled
        # on 721/721 rows, 691 of them starting with a clean 4-digit year (min
        # 1800, max 2018 — counted on the live DB, not inferred). The remaining
        # 30 are 29× "NotProvided" plus one multi-event free text.
        start_year=1800, end_year=2018,
        kind="compilation",
        wording="Version 3.4 was completed on 25 March 2020 with a total of 721 "
                "vent fields. ⛔ That is the compilation's freeze date, not its "
                "measurement window: the vents themselves were discovered between "
                "1800 and 2018, and each row carries its own discovery year.",
        source_url="https://doi.pangaea.de/10.1594/PANGAEA.917894",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="seamounts",
        # ⛔ NOT 2020. The paper was published in 2020, but a predicted-seamount
        # catalogue is only as current as the bathymetry it was predicted FROM,
        # and that grid is SRTM30_PLUS v11 of November 2014. A modeller asking
        # "how current is this?" needs the input's vintage, not the paper's.
        start_year=2014, end_year=2014,
        kind="modelled",
        wording="It is based on the global bathymetry SRTM v.11 — a grid dated "
                "29 November 2014. The catalogue itself (37,889 peaks) was "
                "published 2020-08-18. No seamount carries its own date: every "
                "one inherits this single model vintage.",
        source_url="https://doi.org/10.1594/PANGAEA.921688",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="tectonic-plates",
        start_year=2003, end_year=2003,
        kind="modelled",
        wording="An updated digital model of plate boundaries — Bird, Geochemistry "
                "Geophysics Geosystems, 2003. A fixed-vintage interpreted model, "
                "not observations. ⛔ The GitHub redistribution we fetch retrieved "
                "Bird's files in June 2014; that is the mirror's date, not the "
                "model's.",
        source_url="https://doi.org/10.1029/2001GC000252",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="bathymetry",
        # Open-ended on purpose: GEBCO has shipped an annual release without a
        # break (2024 → 2025 → 2026, confirmed live on the WMS today), so a hard
        # end year would age into a lie within twelve months.
        start_year=1930, end_year=None,
        kind="compilation",
        wording="With the advent of acoustic data recording in the 1930's the "
                "volume of soundings has increased phenomenally. ⛔ The grid merges "
                "measured soundings with satellite-gravity interpolation, so a "
                "cell's depth may never have been sounded at all; GEBCO's TID grid "
                "records which is which, per cell.",
        source_url="https://www.gebco.net/about-us/faq",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="onc",
        # Measured on our own copy 2026-09-09: every stored reading carries the
        # sample time ONC gave it (139/139), and the sweep asks for a 365-day
        # window, so a shown value is at most a year old. The 2009 start is the
        # earliest deployment_start across the 937 instruments we hold.
        start_year=2009, end_year=None,
        kind="observations",
        wording="Each reading carries the measurement time ONC published for "
                "it, and the readings on one station can differ in age because "
                "each instrument category is fetched separately. ⛔ This layer "
                "holds only the LATEST value per measurement, requested within "
                "a 365-day window — it is a snapshot, not a time series, and "
                "nothing here can be pooled into a trend. ONC's own archive "
                "goes back further than what we store; the 2009 start is the "
                "earliest instrument deployment in our copy, not a figure the "
                "publisher states. Their pages render client-side and give no "
                "machine-readable coverage span.",
        source_url="https://data.oceannetworks.ca/",
        verified_on="2026-09-09",
    ),
    Coverage(
        layer_id="onc-instruments",
        # Measured 2026-09-09: 937 instruments, 571 with deployment_start
        # (61%), 79 with deployment_end. Range 2009-09-01 to 2026-08-26, open.
        start_year=2009, end_year=None,
        kind="observations",
        wording="Deployment windows for individual instruments: 571 of 937 "
                "carry a start date and 79 an end date, the rest none — so "
                "⚠️ a filter on this span silently excludes the 39% we cannot "
                "date. A deployment window is when the instrument was in the "
                "water, not when any particular measurement was taken. The "
                "range is read from our own copy; the publisher states no "
                "network-wide span.",
        source_url="https://data.oceannetworks.ca/",
        verified_on="2026-09-09",
    ),
    Coverage(
        layer_id="oceansites",
        # Measured at the source 2026-09-08: 5,788 of 5,795 platforms carry a real
        # deployment date, running 1948-10-01 to 2026-04-12. The earliest is Ocean
        # Weather Station Mike (STATION-M-1), a genuine 1948 record — not the
        # 1900-01-01 sentinel on the remaining 7, which this range excludes. End is
        # OPEN: the network is live and adds platforms continuously.
        start_year=1948, end_year=None,
        kind="observations",
        wording="OceanSITES is a worldwide system of long-term, open-ocean "
                "reference stations... providing multi-year time scales and "
                "real-time data access. The mission is to collect data from "
                "long-term, high-frequency observations at fixed locations in "
                "the open ocean. ⛔ Neither page states a network-wide start or "
                "end year, so this span was counted from the deployment dates "
                "OceanOPS publishes for the network's 5,795 platforms — not "
                "quoted from the publisher. Every platform is held, whatever "
                "its status, each with its own deployment date, so a record "
                "here can be filtered by this span. ⚠️ A deployment date is "
                "when the mooring went in, not the window it measured: a "
                "platform deployed in 1948 and closed decades later carries "
                "the one date, not the other.",
        source_url="https://www.ocean-ops.org/oceansites/about.html",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="air-quality",
        # Measured at the source 2026-09-08: datetime_first/datetime_last on
        # air_quality_stations span 2016-01-01 to 2026-09-09 across 25,438 of
        # 25,814 stations. ⚠️ That is station METADATA coverage, not measurement
        # coverage: readings currently exist for only a small fraction of those
        # stations, a gap this wording states rather than implies away.
        start_year=2016, end_year=None,
        kind="observations",
        wording="We started with real-time and historical data from "
                "reference-grade government monitors in 2015 and began "
                "ingesting data from air sensors starting in 2021 (OpenAQ, "
                "About Us). Our own station date fields span 2016-2026 across "
                "25,438 of 25,814 stations; actual readings are populated for "
                "only a small fraction of those stations, not all of them.",
        source_url="https://openaq.org/about/",
        verified_on="2026-09-08",
    ),
    Coverage(
        layer_id="biodiversity-hotspots",
        # ⛔ NOT 1103, which is what OBIS's own /v3/statistics reports as its
        # minimum year — an evident data-entry artefact, and below the 1750 floor
        # our own gate enforces for exactly this reason. 1842 is the earliest year
        # a NAMED deep-sea contributor states for itself (NOAA DSCRTP).
        start_year=1842, end_year=None,
        kind="observations",
        wording="OBIS reports a year range of 1103–2026, whose lower bound is an "
                "evident data-entry artefact; the earliest span a named deep-sea "
                "contributor states is NOAA DSCRTP's 1842-Present. ⛔ Our own copy "
                "stores NO per-record date — OBIS serves eventDate on the great "
                "majority of records and our ingest never asked for it — so this "
                "layer cannot be filtered by period here, only at the source.",
        source_url="https://api.obis.org/v3/statistics",
        verified_on="2026-09-08",
    ),
)


def seed_rows() -> list[tuple]:
    """COVERAGE as asyncpg parameter tuples.

    ⛔ `verified_on` MUST arrive as a `datetime.date`, not the ISO string the table
    above spells it with. asyncpg binds every parameter to a Postgres type BEFORE
    the query's own `::date` cast runs, so a str reaches the DATE codec and dies with
    `'str' object has no attribute 'toordinal'` — a message that names neither the
    column nor the value. This blew up in production on 2026-09-08 (the migrate gate
    caught it and refused to restart, so nothing went down) and it is why the
    conversion lives in a function a test can call without a database.
    """
    return [(c.layer_id, c.start_year, c.end_year, c.kind, c.wording, c.source_url,
             datetime.date.fromisoformat(c.verified_on)) for c in COVERAGE]


async def ensure_layer_temporal_coverage() -> None:
    """Create the table and upsert the curated rows.

    ⛔ Upsert, NOT `ON CONFLICT DO NOTHING` — unlike layer_config, whose rows an
    operator may legitimately have changed by hand, these rows are a sourced claim
    that lives in this file. If the file changes because a publisher restated its
    coverage, the database must follow, or the citation on screen stops matching
    the citation in git.
    """
    async with db.pool.acquire() as conn:
        await conn.execute(DDL)
        await conn.executemany(
            """INSERT INTO layer_temporal_coverage
                 (layer_id, start_year, end_year, kind, wording, source_url, verified_on)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (layer_id) DO UPDATE SET
                 start_year  = EXCLUDED.start_year,
                 end_year    = EXCLUDED.end_year,
                 kind        = EXCLUDED.kind,
                 wording     = EXCLUDED.wording,
                 source_url  = EXCLUDED.source_url,
                 verified_on = EXCLUDED.verified_on,
                 updated_at  = now()""",
            seed_rows(),
        )
    log.info("layer_temporal_coverage: %d layers anchored in time", len(COVERAGE))