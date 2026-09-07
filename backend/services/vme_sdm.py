# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""VME / deep-sea coral habitat-suitability SDM — pure helpers + bake orchestration.

MODELED analysis layer (MaxEnt). Not observed data, and never presented as observation.
Heavy deps (elapid/sklearn/PyCO2SYS/numpy) are imported lazily so these helpers
and their unit tests stay light.
"""
from __future__ import annotations

import math
import os
import pathlib

CACHE_DIR = pathlib.Path(os.getenv("VME_CACHE_DIR", "/var/cache/abyssal-vme"))

TAXON_SET = "reef_scleractinia_v1"
# Resolved at bake time via worms_taxa; canonical names for provenance/citation.
TAXON_NAMES = ["Desmophyllum pertusum", "Solenosmilia variabilis"]
TAXON_SYNONYMS = ["Lophelia pertusa"]  # -> Desmophyllum pertusum

SUITABILITY_VMIN = 0.0
SUITABILITY_VMAX = 1.0

# Sequential viridis-ish ramp (low->high suitability). Hex kept in sync with the legend.
RAMP_HEX = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]

CITATION = (
    "Modeled (MaxEnt/elapid). Occurrences: NOAA DSCRTP. Taxonomy: WoRMS. "
    "Predictors: GEBCO 2024; seabed substrate Dutkiewicz et al. 2015; WOA23; ISAS; "
    "GLODAPv2 (Lauvset et al. 2016; Key et al. 2015) "
    "with aragonite saturation via PyCO2SYS. Relative habitat suitability, not probability of "
    "presence. Not observed data; not for impact/causal inference."
)


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def encode_suitability_to_rgba(value):
    """Map suitability 0..1 to an RGBA tuple; None -> muted slate (matches marine-carbon null)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return (100, 116, 139, 140)
    t = max(0.0, min(1.0, (float(value) - SUITABILITY_VMIN) / (SUITABILITY_VMAX - SUITABILITY_VMIN)))
    stops = [_hex(h) for h in RAMP_HEX]
    pos = t * (len(stops) - 1)
    i = int(math.floor(pos))
    if i >= len(stops) - 1:
        r, g, b = stops[-1]
    else:
        f = pos - i
        (r0, g0, b0), (r1, g1, b1) = stops[i], stops[i + 1]
        r, g, b = (int(r0 + (r1 - r0) * f), int(g0 + (g1 - g0) * f), int(b0 + (b1 - b0) * f))
    return (r, g, b, 190)


def omega_arag(dic, talk, temp_c, salinity, pressure_dbar):
    """Aragonite saturation state from the carbonate system (PyCO2SYS). None on bad input."""
    vals = [dic, talk, temp_c, salinity, pressure_dbar]
    if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in vals):
        return None
    import PyCO2SYS as pyco2  # lazy
    try:
        res = pyco2.sys(
            par1=float(talk), par1_type=1,   # 1 = total alkalinity (umol/kg)
            par2=float(dic), par2_type=2,     # 2 = dissolved inorganic carbon (umol/kg)
            temperature=float(temp_c), salinity=float(salinity),
            pressure=float(pressure_dbar),
        )
        om = float(res["saturation_aragonite"])
    except Exception:
        return None
    if math.isnan(om):
        return None
    return om


def thin_to_cells(points, precision=2):
    """Keep one point per (rounded-cell, species). points: (lat, lon, species_id)."""
    seen = set()
    out = []
    for lat, lon, sp in points:
        key = (round(float(lat), precision), round(float(lon), precision), sp)
        if key in seen:
            continue
        seen.add(key)
        out.append((lat, lon, sp))
    return out


def spatial_blocks(coords, block_deg=5.0, k=5):
    """Assign each (lat, lon) to one of k spatial-block folds (block-checkerboard)."""
    folds = []
    for lat, lon in coords:
        bi = int(math.floor(lat / block_deg))
        bj = int(math.floor(lon / block_deg))
        folds.append((bi + bj) % k)
    return folds


def boyce_index(pred_at_presence, pred_background, n_bins=10):
    """Continuous Boyce index: Spearman corr of predicted/expected (P/E) ratio vs suitability bin.

    P/E > 1 where presences are over-represented relative to available background.
    Returns a value in [-1, 1]; > 0 means the model ranks presences above background.
    """
    import numpy as np  # lazy
    pres = np.asarray(pred_at_presence, dtype=float)
    bg = np.asarray(pred_background, dtype=float)
    if pres.size == 0 or bg.size == 0:
        return float("nan")
    lo = float(min(pres.min(), bg.min()))
    hi = float(max(pres.max(), bg.max()))
    if hi <= lo:
        return float("nan")
    edges = np.linspace(lo, hi, n_bins + 1)
    centers, pe = [], []
    for idx in range(n_bins):
        a, b = edges[idx], edges[idx + 1]
        last = idx == n_bins - 1
        pres_in = (pres >= a) & (pres <= b) if last else (pres >= a) & (pres < b)
        bg_in = (bg >= a) & (bg <= b) if last else (bg >= a) & (bg < b)
        p = float(pres_in.sum()) / pres.size
        e = float(bg_in.sum()) / bg.size
        if e > 0:
            centers.append((a + b) / 2.0)
            pe.append(p / e)
    if len(pe) < 2:
        return float("nan")
    # Spearman = Pearson on ranks
    c = np.argsort(np.argsort(np.asarray(centers)))
    r = np.argsort(np.argsort(np.asarray(pe)))
    cc = np.corrcoef(c, r)[0, 1]
    return float(cc) if not math.isnan(cc) else float("nan")


PREDICTOR_KEYS = ["depth_m", "temp_c", "salinity", "o2", "substrate", "omega_arag"]

# Display metadata for the panel's "top predictors" list (label + unit per predictor).
PREDICTOR_LABELS = {
    "depth_m":     ("Seafloor depth", "m"),
    "temp_c":      ("Temperature", "°C"),
    "salinity":    ("Salinity", "PSU"),
    "o2":          ("Dissolved O₂", "µmol/kg"),
    "substrate":   ("Substrate class", ""),
    "omega_arag":  ("Aragonite Ω", ""),
}


def format_top_predictors(top):
    """Turn the stored {predictor_key: value} dict into the panel's ordered
    [{key, label, value, units}] list (FEATURE_ORDER order; skips keys absent from the dict)."""
    out = []
    for k in FEATURE_ORDER:
        if top is None or k not in top:
            continue
        label, units = PREDICTOR_LABELS.get(k, (k, ""))
        out.append({"key": k, "label": label, "value": top[k], "units": units})
    return out


def _depth_at(lat, lon):
    from services import bathymetry_grid_export as bg
    d = bg.sample("depth", lat, lon, None)
    return None if d is None else float(d)


def _woa_at(var, lat, lon, depth_m):
    from services import woa_climatology as woa
    return woa.sample(var, lat, lon, depth_m, None)


def _substrate_at(lat, lon):
    from services import seabed_lithology as sl
    return sl.sample(lat, lon)


def _o2_at(lat, lon, depth_m, grid):
    from services import oxygen_deox as ox
    if grid is None:
        return None
    return ox.nearest_grid_value(grid.lats, grid.lons, grid.depths, grid.data, lat, lon, depth_m)


def _glodap_at(var, lat, lon, depth_m):
    from services import glodap_carbon as gc
    return gc.sample(var, lat, lon, depth_m)


def load_oxy_grid():
    """Load the ISAS recent-O2 grid once per bake (may be None)."""
    from services import oxygen_deox as ox
    return ox.load_recent_grid()


def seafloor_sample(lat, lon, oxy_grid=None):
    """Sample every predictor at the seafloor depth beneath (lat, lon).

    Depth-matching rule (spec 5.3): take the GEBCO seafloor depth, then sample every
    depth-resolved predictor at that depth level, never the surface. If a predictor is
    undefined at seafloor depth, its value is None and the row is flagged
    `predictors_missing`.

    `predictors_missing` is NOT the same thing as `vme_cells.extrapolated` — it means "we
    could not sample here", and such cells are dropped by bake_vme rather than stored. True
    extrapolation (a cell whose environment lies outside the range the model was fitted on)
    is a separate judgement made against the training envelope — see is_extrapolated().

    WOA var keys are the top-level WOA_VARS keys ("temperature", "salinity"), NOT the
    nested an_var codes ("t_an", "s_an") — woa_climatology.sample() rejects anything not
    in WOA_VARS and returns None.
    """
    depth = _depth_at(lat, lon)
    if depth is None or depth >= 0:  # land or missing bathymetry -> no seafloor sample
        return {k: None for k in PREDICTOR_KEYS} | {"predictors_missing": True}
    depth_pos = abs(depth)  # positive metres below surface for depth-indexed grids

    temp = _woa_at("temperature", lat, lon, depth_pos)
    sal = _woa_at("salinity", lat, lon, depth_pos)
    o2 = _o2_at(lat, lon, depth_pos, oxy_grid)
    substrate = _substrate_at(lat, lon)
    dic = _glodap_at("dic", lat, lon, depth_pos)
    talk = _glodap_at("talk", lat, lon, depth_pos)
    pressure_dbar = depth_pos  # ~1 dbar per metre; adequate for Omega
    om = omega_arag(dic, talk, temp, sal, pressure_dbar) if None not in (dic, talk, temp, sal) else None

    row = {
        "depth_m": depth_pos,
        "temp_c": None if temp is None else float(temp),
        "salinity": None if sal is None else float(sal),
        "o2": None if o2 is None else float(o2),
        "substrate": None if substrate is None else int(substrate),
        "omega_arag": om,
    }
    row["predictors_missing"] = any(row[k] is None for k in PREDICTOR_KEYS if k != "depth_m")
    return row


async def resolve_aphia_ids(conn):
    """Resolve the reef-former taxon set to accepted WoRMS AphiaIDs (incl. synonyms).

    Schema note: worms_taxa's name column is `scientificname` (not `valid_name`), and
    taxon_name_map's input column is `raw_name` (not `input_name`) — verified against the
    live schema at implementation time (2026-07-16); adapted from the brief accordingly.
    """
    names = TAXON_NAMES + TAXON_SYNONYMS
    rows = await conn.fetch(
        """
        SELECT DISTINCT aphia_id FROM worms_taxa
         WHERE scientificname = ANY($1::text[]) AND aphia_id IS NOT NULL
        UNION
        SELECT DISTINCT matched_aphia_id AS aphia_id FROM taxon_name_map
         WHERE raw_name = ANY($1::text[]) AND matched_aphia_id IS NOT NULL AND verified
        """,
        names,
    )
    return [int(r["aphia_id"]) for r in rows if r["aphia_id"] is not None]


async def fetch_presences(conn, aphia_ids):
    """DSCRTP occurrences for the taxon set as (lat, lon, species_id).

    Schema note: noaa_corals_records already stores `lat`/`lon` as double precision columns
    (its `geom` is a generated `geography(Point,4326)`, not `geometry`, and ST_X/ST_Y don't
    accept geography) — read lat/lon directly instead of the brief's ST_Y(geom)/ST_X(geom).

    The brief's `biodiversity_hotspots` UNION arm is DROPPED: that table has no `aphia_id`,
    `lat`, or `lon` column at all (verified 2026-07-16 via \\d biodiversity_hotspots) — only
    `scientific_name` + a `geometry(Point,4326)` `geom`. There is no aphia_id-keyed join path
    without inventing a name-matching heuristic, which is out of scope here. v1 presences are
    DSCRTP-only; OBIS/biodiversity_hotspots enrichment is a documented follow-up, not a bug.
    """
    if not aphia_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT lat, lon, aphia_id
          FROM noaa_corals_records
         WHERE aphia_id = ANY($1::int[]) AND lat IS NOT NULL AND lon IS NOT NULL
        """,
        aphia_ids,
    )
    return [(float(r["lat"]), float(r["lon"]), int(r["aphia_id"])) for r in rows]


async def fetch_target_group_background(conn, n=10000):
    """Target-group background: sample from ALL DSCRTP coral/sponge survey locations to
    correct sampling bias (background shares the presence sampling footprint).

    Schema note: reads lat/lon columns directly, same reasoning as fetch_presences.
    """
    rows = await conn.fetch(
        """
        SELECT lat, lon
          FROM noaa_corals_records
         WHERE lat IS NOT NULL AND lon IS NOT NULL
         ORDER BY random()
         LIMIT $1
        """,
        n,
    )
    return [(float(r["lat"]), float(r["lon"])) for r in rows]


# FEATURE_ORDER aliases PREDICTOR_KEYS (never a second literal list) so the model's feature
# order and the seafloor_sample() column order can never drift apart.
FEATURE_ORDER = PREDICTOR_KEYS
MIN_AUC = 0.70
MIN_BOYCE = 0.0

# `substrate` is a categorical lithology CLASS, not a magnitude — a min/max range test on it
# is meaningless (class 3 is not "between" 2 and 4). Membership of the fitted class set is
# the only sound extrapolation test for it. Everything else is continuous.
_CATEGORICAL_PREDICTORS = frozenset({"substrate"})


def training_envelope(Xtr):
    """Per-predictor description of the environment the model was actually fitted on.

    Continuous predictors -> ("range", lo, hi); categorical -> ("set", {classes seen}).
    Returns None for an empty matrix, which is_extrapolated() reads as "cannot judge".
    """
    if not Xtr:
        return None
    env = {}
    for i, key in enumerate(FEATURE_ORDER):
        vals = [row[i] for row in Xtr]
        if key in _CATEGORICAL_PREDICTORS:
            env[key] = ("set", frozenset(vals))
        else:
            env[key] = ("range", min(vals), max(vals))
    return env


def is_extrapolated(feats, envelope):
    """True when a cell's environment falls outside the range the model was fitted on.

    This is what `vme_cells.extrapolated` means and what the panel claims: the model is
    predicting into conditions it never saw, so the score is a reach. It is deliberately
    NOT `predictors_missing` (see seafloor_sample) — the two were conflated until
    2026-07-16, which made the column tautologically FALSE and the panel warning dead:
    bake_vme drops every predictor-gap cell before insert, so the only rows that could
    have carried the old flag were exactly the rows never stored.

    Univariate (a MESS-style envelope test), so it does NOT catch a novel *combination* of
    individually-in-range predictors. Uncertainty remains the better guide to those.
    """
    if not envelope:
        return False
    for i, key in enumerate(FEATURE_ORDER):
        spec = envelope.get(key)
        val = feats[i]
        if spec is None or val is None:
            continue
        if spec[0] == "set":
            if val not in spec[1]:
                return True
        elif val < spec[1] or val > spec[2]:
            return True
    return False
MIN_OCCURRENCES = 50


def fit_and_evaluate(X, y, coords, k=5):
    """Fit MaxEnt with spatial-block CV. Returns per-fold models + AUC/Boyce/importance.

    Per-fold models double as the prediction ensemble (mean=suitability, std=uncertainty).

    elapid MaxentModel API verified live on the VPS venv (2026-07-16):
      __init__(..., n_cpus: int = 8, ...) -> capped to 4 here (global ≤4-CPU constraint).
      fit(x, y, ...) -> None
      predict(x) -> numpy.ndarray, shape (n_rows,) — already a flat per-row score array
      (cloglog-transformed suitability in [0, 1]), so `np.asarray(...).ravel()` is a no-op
      safety net, not a reshape of a DataFrame/2-col array.
    """
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from elapid import MaxentModel

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    folds = np.asarray(spatial_blocks(coords, k=k))
    uniq = sorted(set(int(f) for f in folds))
    models, aucs, boyces = [], [], []
    for f in uniq:
        test = folds == f
        train = ~test
        if y[train].sum() < 5 or y[test].sum() < 1:
            continue
        m = MaxentModel(n_cpus=4)
        m.fit(X[train], y[train])
        p_test = np.asarray(m.predict(X[test])).ravel()
        try:
            aucs.append(float(roc_auc_score(y[test], p_test)))
        except ValueError:
            pass
        pres_scores = p_test[y[test] == 1].tolist()
        bg_scores = p_test[y[test] == 0].tolist()
        b = boyce_index(pres_scores, bg_scores)
        if not math.isnan(b):
            boyces.append(b)
        models.append(m)

    # Variable importance: permutation drop in AUC on the full data, averaged over models.
    importance = _permutation_importance(models, X, y)
    return {
        "models": models,
        "auc": float(np.mean(aucs)) if aucs else float("nan"),
        "boyce": float(np.mean(boyces)) if boyces else float("nan"),
        "var_importance": importance,
        "n_occurrences": int(y.sum()),
    }


def _permutation_importance(models, X, y):
    import numpy as np
    from sklearn.metrics import roc_auc_score
    if not models:
        return {}
    X = np.asarray(X, dtype=float)
    base_pred, _ = predict_ensemble(models, X)
    try:
        base = roc_auc_score(y, base_pred)
    except ValueError:
        return {}
    rng = np.random.default_rng(0)
    out = {}
    for i, name in enumerate(FEATURE_ORDER):
        Xp = X.copy()
        Xp[:, i] = rng.permutation(Xp[:, i])
        pred, _ = predict_ensemble(models, Xp)
        try:
            out[name] = round(float(base - roc_auc_score(y, pred)), 4)
        except ValueError:
            out[name] = 0.0
    return out


def predict_ensemble(models, Xgrid):
    """Predict with every fold model; return (mean suitability, std uncertainty) per row."""
    import numpy as np
    X = np.asarray(Xgrid, dtype=float)
    if not models:
        return [float("nan")] * len(X), [float("nan")] * len(X)
    preds = np.stack([np.asarray(m.predict(X)).ravel() for m in models], axis=0)
    mean = np.clip(preds.mean(axis=0), 0.0, 1.0)
    std = preds.std(axis=0)
    return mean.tolist(), std.tolist()


async def bake_vme(pool):
    """Full offline bake: resolve taxa -> occurrences -> thin -> background -> seafloor-sample
    -> fit+CV -> predict every hex cell -> write vme_cells/vme_models. Fail-closed on the
    publish threshold (does not overwrite a prior good surface)."""
    import numpy as np
    import json
    import logging
    log = logging.getLogger("vme_sdm")

    async with pool.acquire() as conn:
        aphia_ids = await resolve_aphia_ids(conn)
        presences = await fetch_presences(conn, aphia_ids)
        background = await fetch_target_group_background(conn)
        cells = await conn.fetch(
            "SELECT cell_id, ST_Y(ST_Centroid(geom)) AS lat, ST_X(ST_Centroid(geom)) AS lon "
            "FROM density_hex_cells"
        )

    thinned = thin_to_cells(presences)
    if len(thinned) < MIN_OCCURRENCES:
        log.warning("vme: only %d thinned occurrences (< %d) — not publishing", len(thinned), MIN_OCCURRENCES)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vme_models (taxon_set, model, n_occurrences, auc, boyce, var_importance, aphia_ids, published)"
                " VALUES ($1,'maxent',$2,NULL,NULL,'{}'::jsonb,$3,FALSE)",
                TAXON_SET, len(thinned), aphia_ids)
        return {"cells": 0, "auc": None, "boyce": None, "published": False}

    oxy = load_oxy_grid()

    def _row(lat, lon):
        s = seafloor_sample(lat, lon, oxy)
        return [s[k] for k in FEATURE_ORDER], s["predictors_missing"]

    # training matrix
    Xtr, ytr, coords = [], [], []
    for lat, lon, _sp in thinned:
        feats, _ex = _row(lat, lon)
        if any(f is None for f in feats):
            continue
        Xtr.append(feats); ytr.append(1); coords.append((lat, lon))
    for lat, lon in background:
        feats, _ex = _row(lat, lon)
        if any(f is None for f in feats):
            continue
        Xtr.append(feats); ytr.append(0); coords.append((lat, lon))

    n_pres_usable = sum(ytr)
    log.info("vme: presences thinned=%d usable=%d (dropped=%d for missing predictors); background usable=%d",
              len(thinned), n_pres_usable, len(thinned) - n_pres_usable, len(ytr) - n_pres_usable)

    if sum(ytr) < MIN_OCCURRENCES:
        log.warning("vme: usable presences after sampling %d < %d — not publishing", sum(ytr), MIN_OCCURRENCES)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO vme_models (taxon_set, model, n_occurrences, auc, boyce, var_importance, aphia_ids, published)"
                " VALUES ($1,'maxent',$2,NULL,NULL,'{}'::jsonb,$3,FALSE)",
                TAXON_SET, sum(ytr), aphia_ids)
        return {"cells": 0, "auc": None, "boyce": None, "published": False}

    res = fit_and_evaluate(Xtr, ytr, coords)
    published = (
        not math.isnan(res["auc"]) and res["auc"] >= MIN_AUC
        and not math.isnan(res["boyce"]) and res["boyce"] > MIN_BOYCE
        and res["n_occurrences"] >= MIN_OCCURRENCES
    )

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO vme_models (taxon_set, model, n_occurrences, auc, boyce, var_importance, aphia_ids, published)"
            " VALUES ($1,'maxent',$2,$3,$4,$5::jsonb,$6,$7)",
            TAXON_SET, res["n_occurrences"],
            None if math.isnan(res["auc"]) else res["auc"],
            None if math.isnan(res["boyce"]) else res["boyce"],
            json.dumps(res["var_importance"]), aphia_ids, published)

    if not published:
        log.warning("vme: model below publish threshold (auc=%.3f boyce=%.3f) — keeping prior surface",
                    res["auc"], res["boyce"])
        return {"cells": 0, "auc": res["auc"], "boyce": res["boyce"], "published": False}

    # The envelope must come from Xtr — the rows actually fitted — not from the raw
    # occurrences, so it reflects what the model saw after predictor-gap drops.
    envelope = training_envelope(Xtr)

    # predict every deep-sea cell in chunks (memory-bounded)
    n_written = 0
    n_extrap = 0
    CHUNK = 2000
    buf = []
    for c in cells:
        lat, lon = float(c["lat"]), float(c["lon"])
        feats, missing = _row(lat, lon)
        if missing or any(f is None for f in feats):
            continue  # not deep-sea / predictor gap -> no cell
        ex = is_extrapolated(feats, envelope)
        n_extrap += ex
        buf.append((c["cell_id"], lat, lon, feats, ex))
        if len(buf) >= CHUNK:
            n_written += await _write_cells(pool, buf, res["models"])
            buf = []
    if buf:
        n_written += await _write_cells(pool, buf, res["models"])

    log.info("vme: published surface auc=%.3f boyce=%.3f cells=%d extrapolated=%d (%.1f%%)",
             res["auc"], res["boyce"], n_written, n_extrap,
             (100.0 * n_extrap / n_written) if n_written else 0.0)
    return {"cells": n_written, "auc": res["auc"], "boyce": res["boyce"], "published": True}


async def _write_cells(pool, buf, models):
    import json
    Xgrid = [b[3] for b in buf]
    mean, std = predict_ensemble(models, Xgrid)
    rows = []
    for (cell_id, lat, lon, feats, ex), m, s in zip(buf, mean, std):
        top = {k: feats[i] for i, k in enumerate(FEATURE_ORDER)}
        rows.append((TAXON_SET, cell_id, float(m), float(s), bool(ex), json.dumps(top)))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """INSERT INTO vme_cells (taxon_set, cell_id, suitability, uncertainty, extrapolated, top_predictors)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                   ON CONFLICT (taxon_set, cell_id) DO UPDATE SET
                     suitability=EXCLUDED.suitability, uncertainty=EXCLUDED.uncertainty,
                     extrapolated=EXCLUDED.extrapolated, top_predictors=EXCLUDED.top_predictors""",
                rows)
    return len(rows)
