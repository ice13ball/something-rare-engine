# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SQL constants and the shared row->FeatureCollection mapping for the three
hex-density-histogram endpoints in domains/geochem.py (memento, geotraces,
mosaic).

This module imports NOTHING from the application -- `import json` only.
That is deliberate: importing `domains.geochem` has tripped a circular
import through `land_layers` before, which is exactly why the tests that
guard this SQL used to fall back to slicing the source text instead of
executing it. A leaf module with zero application imports removes that
failure mode permanently, so backend/tests/test_hex_hist_sql_exec.py can
`from domains.geochem_sql import ...` and run the real SQL against a real
database.
"""

import json

MEMENTO_HEX_SQL = """WITH per_cell_decade AS (
                   SELECT h.geom AS hgeom, c.decade, count(*) AS cnt,
                          min(EXTRACT(YEAR FROM c.sample_time))::int AS ymin,
                          max(EXTRACT(YEAR FROM c.sample_time))::int AS ymax,
                          count(*) FILTER (WHERE c.decade IS NULL) AS undated
                   FROM density_hex_cells h
                   JOIN memento_casts c ON c.geom && h.geom AND ST_Intersects(c.geom, h.geom)
                   GROUP BY h.geom, c.decade
               )
               SELECT ST_Y(ST_Centroid(hgeom)) AS lat,
                      ST_X(ST_Centroid(hgeom)) AS lon,
                      ST_AsGeoJSON(hgeom)      AS gj,
                      sum(cnt)::int            AS n,
                      min(ymin)                AS year_min,
                      max(ymax)                AS year_max,
                      sum(undated)::int        AS n_undated,
                      jsonb_object_agg(decade::text, cnt) FILTER (WHERE decade IS NOT NULL) AS by_decade
               FROM per_cell_decade
               GROUP BY hgeom"""


GEOTRACES_HEX_SQL = """WITH per_cell_decade AS (
                   SELECT h.geom AS hgeom, s.decade, count(*) AS cnt,
                          min(EXTRACT(YEAR FROM s.sample_time))::int AS ymin,
                          max(EXTRACT(YEAR FROM s.sample_time))::int AS ymax,
                          count(*) FILTER (WHERE s.decade IS NULL) AS undated
                   FROM density_hex_cells h
                   JOIN geotraces_stations s ON s.geom && h.geom AND ST_Intersects(s.geom, h.geom)
                   GROUP BY h.geom, s.decade
               )
               SELECT ST_Y(ST_Centroid(hgeom)) AS lat,
                      ST_X(ST_Centroid(hgeom)) AS lon,
                      ST_AsGeoJSON(hgeom)      AS gj,
                      sum(cnt)::int            AS n,
                      min(ymin)                AS year_min,
                      max(ymax)                AS year_max,
                      sum(undated)::int        AS n_undated,
                      jsonb_object_agg(decade::text, cnt) FILTER (WHERE decade IS NOT NULL) AS by_decade
               FROM per_cell_decade
               GROUP BY hgeom"""


MOSAIC_HEX_SQL = """WITH per_cell_decade AS (
                   SELECT h.geom AS hgeom, s.decade, count(*) AS cnt,
                          min(s.sampling_year) AS ymin, max(s.sampling_year) AS ymax,
                          count(*) FILTER (WHERE s.sampling_year IS NULL) AS undated
                   FROM density_hex_cells h
                   JOIN mosaic_cores s ON s.geom && h.geom AND ST_Intersects(s.geom, h.geom)
                   GROUP BY h.geom, s.decade
               )
               SELECT ST_Y(ST_Centroid(hgeom)) AS lat,
                      ST_X(ST_Centroid(hgeom)) AS lon,
                      ST_AsGeoJSON(hgeom)      AS gj,
                      sum(cnt)::int            AS n,
                      min(ymin)                AS year_min,
                      max(ymax)                AS year_max,
                      sum(undated)::int        AS n_undated,
                      jsonb_object_agg(decade::text, cnt) FILTER (WHERE decade IS NOT NULL) AS by_decade
               FROM per_cell_decade
               GROUP BY hgeom"""


def hex_feature_collection(rows) -> dict:
    """Shared row -> GeoJSON FeatureCollection mapping for the three hex-density
    histogram queries above. asyncpg returns JSONB columns as `str`, so
    `by_decade` must be json.loads()'d here -- without that call the client
    receives a JSON-encoded JSON string and `Object.entries` throws.
    """
    feats = [
        {
            "type": "Feature",
            "geometry": json.loads(r["gj"]),
            "properties": {
                "count": r["n"],
                "lat": r["lat"],
                "lon": r["lon"],
                "year_min": r["year_min"],
                "year_max": r["year_max"],
                "n_undated": r["n_undated"],
                "by_decade": json.loads(r["by_decade"]) if r["by_decade"] else {},
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": feats}
