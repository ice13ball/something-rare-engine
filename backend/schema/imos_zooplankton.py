# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""IMOS zooplankton (AusCPR + National Reference Stations): DDL as text.

Two tables, filled by the one-shot import `python -m ingestion.imos_zooplankton <dir>` (never by the API, never
periodically). The import builds `<table>_new` and swaps in one transaction, so every constraint and index name is
derived from the table name (`constraint_names` / `index_names`): the swap renames them to the live names, which
keeps the next run's `_new` names free. No statement contains a semicolon, the DDL snapshot splits on it.

NULL semantics, all of it in the column comments: a taxon the source gave as JSON null was NOT COUNTED in that
sample and has no row at all. A row with abundance 0 is a counted absence. For the NRS non-copepod file the source
lists present taxa only, so there an absent taxon is unknown (`noncopepod_zeros_explicit` = false).
"""
from __future__ import annotations

SAMPLES_TABLE = "imos_zoop_samples"
ABUNDANCE_TABLE = "imos_zoop_abundance"

_SAMPLES = """
CREATE TABLE IF NOT EXISTS {t} (
  sample_key text CONSTRAINT {t}_pkey PRIMARY KEY,  -- cpr:<Sample_ID> for AusCPR, nrs:<TripCode> for the National Reference Stations
  programme text NOT NULL CHECK (programme IN ('auscpr','nrs')),
  trip_code text,  -- source TripCode
  region text,  -- AusCPR region name, NULL for NRS
  station_code text,  -- NRS StationCode, NULL for AusCPR
  station_name text,  -- NRS StationName, NULL for AusCPR
  lat double precision NOT NULL,  -- degrees north, from the Latitude column (the source geom column has lat and lon swapped)
  lon double precision NOT NULL,  -- degrees east, from the Longitude column
  geom geometry(Point, 4326) NOT NULL,
  sample_time_utc timestamptz,  -- SampleTime_UTC, NULL when the source gave none
  sample_depth_m double precision,  -- NRS SampleDepth_m, NULL for AusCPR (the source gives no depth per CPR sample)
  sample_volume_m3 double precision,  -- AusCPR SampleVolume_m3 (water filtered), NULL for NRS
  biomass_mgm3 double precision,  -- mg per m3: AusCPR BiomassIndex_mgm3 (an index), NRS Biomass_mgm3 (measured)
  copepod_total_m3 double precision,  -- individuals per m3, sum of the counted copepod taxa, NULL = no copepod taxon was counted (unknown, not zero)
  n_copepod_taxa_present integer,  -- number of copepod taxa with abundance above zero, NULL when copepod_total_m3 is NULL
  noncopepod_zeros_explicit boolean NOT NULL,  -- true: a non-copepod taxon with abundance 0 was counted and absent. false (NRS): the source lists present taxa only, an unlisted taxon is UNKNOWN
  snapshot date NOT NULL  -- date the AODN WFS export was taken
)"""

_ABUNDANCE = """
CREATE TABLE IF NOT EXISTS {t} (
  sample_key text NOT NULL,  -- imos_zoop_samples.sample_key
  taxon text NOT NULL,  -- taxon name as in the source, whitespace trimmed
  is_copepod boolean NOT NULL,  -- true: from the copepod file, false: from the non-copepod file (7 names occur in both)
  abundance_m3 double precision NOT NULL CHECK (abundance_m3 >= 0),  -- individuals per m3, 0 = counted and absent. A taxon the source gave as null has no row
  CONSTRAINT {t}_pkey PRIMARY KEY (sample_key, taxon, is_copepod),
  CONSTRAINT {t}_sample_fk FOREIGN KEY (sample_key) REFERENCES {s} (sample_key) ON DELETE CASCADE
)"""


def samples_ddl(suffix: str = "") -> list[str]:
    t = SAMPLES_TABLE + suffix
    return [
        _SAMPLES.replace("{t}", t),
        f"ALTER TABLE {t} OWNER TO abyssal_user",
        f"CREATE INDEX IF NOT EXISTS {t}_geom_gix ON {t} USING GIST (geom)",
    ]


def abundance_ddl(suffix: str = "") -> list[str]:
    t = ABUNDANCE_TABLE + suffix
    return [
        _ABUNDANCE.replace("{t}", t).replace("{s}", SAMPLES_TABLE + suffix),
        f"ALTER TABLE {t} OWNER TO abyssal_user",
        f"CREATE INDEX IF NOT EXISTS {t}_taxon_idx ON {t} (taxon, is_copepod)",
    ]


def renames(suffix: str = "_new") -> dict[str, list[tuple[str, str]]]:
    """Per table: (kind, name-with-suffix) pairs for the post-swap rename. kind is 'constraint' or 'index'."""
    s, a = SAMPLES_TABLE + suffix, ABUNDANCE_TABLE + suffix
    return {
        SAMPLES_TABLE: [("constraint", f"{s}_pkey"), ("index", f"{s}_geom_gix")],
        ABUNDANCE_TABLE: [("constraint", f"{a}_pkey"), ("constraint", f"{a}_sample_fk"),
                          ("index", f"{a}_taxon_idx")],
    }


async def ensure_imos_zooplankton(conn) -> None:
    """The live tables, empty until the first import. The importer builds the `_new` pair itself."""
    for sql in samples_ddl() + abundance_ddl():
        await conn.execute(sql)
