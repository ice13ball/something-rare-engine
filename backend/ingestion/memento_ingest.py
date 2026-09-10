# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""MEMENTO (GEOMAR marine CH4 + N2O) ingest.

Pure CSV parsing (build_samples/derive_casts, unit-tested offline against real
fixtures) + an authenticated downloader for the one-time scrape. Credentials
come from env at run time and are never stored. Source is a frozen archive
(no updates since ~2020); we pull one leg per request to avoid the portal's
known large-request bug.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
import logging

log = logging.getLogger(__name__)

NO_VALUE = -999.0
# Columns promoted to first-class table columns (everything else -> params JSONB).
FIRST_CLASS = ("ch4", "n2o", "n2o_perc", "o2", "temp", "sal")

# Per-gas atmospheric threshold. MEMENTO publishes Methane_Ocean [nmol/l] and
# Methane_Atmosphere [ppb] under one column name; the CSV export drops the
# distinction. Cruise medians separate them with a clean physical gap:
#   CH4: 1622.0 (air) vs 247.0 (highest credible seawater cruise median)
#   N2O:  311.8 (air) vs 108.5 (real OMZ cruise median)
GAS_THRESHOLD: dict[str, float] = {"ch4": 500.0, "n2o": 200.0}


def is_atmospheric(gas: str, label, cruise_median, value) -> bool:
    """True when this gas value is an atmospheric mole fraction, not a dissolved
    concentration. Per-gas and per-value: a row flagged for CH4 may still carry a
    perfectly good oceanic N2O.

    `label` ending in `_Air` is MEMENTO's own annotation. The cruise-median test is
    OUR inference and must be disclosed as platform-derived wherever it is surfaced.
    """
    if label is not None and str(label).endswith("_Air"):
        return True
    if value is None or cruise_median is None:
        return False
    t = GAS_THRESHOLD.get(gas)
    if t is None:
        return False
    return float(cruise_median) >= t and float(value) >= t
_FIXED = {"set", "station", "time", "latitude", "longitude", "depth [m]", "label"}
_BASE = "https://portal.geomar.de/memento"
_CSV_TPL = (
    _BASE + "/bottle/list?format=csv&extension=csv&legs={id}"
    "&minYear=1970&maxYear=2014&minLatitude=-90.0&maxLatitude=90.0"
    "&minLongitude=-180.0&maxLongitude=180.0&max=99999&parameterType.id=null"
)


def _num(v):
    """Parse a float; map blank and the -999 sentinel to None."""
    if v is None:
        return None
    s = v.strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return None if f == NO_VALUE else f


#: What the SOURCE gave, decided by which format matched — never by looking at
#: the parsed value afterwards.
_TIME_FORMATS = (
    ("%Y-%m-%d %H:%M",    "minute"),
    ("%Y-%m-%d %H:%M:%S", "minute"),
    ("%Y-%m-%d",          "day"),
)


def _parse_time(v):
    """Return (datetime, precision) — precision is 'minute', 'day', or None.

    ⛔ The precision CANNOT be recovered from the value. Measured on production
    2026-09-10: 59,295 of 218,271 samples (27%) sit at exactly 00:00, and 8,822
    of those on the first of a month. Midnight is a real time and the first is
    a real day, so a cast genuinely taken at 00:00 on the 1st is
    indistinguishable from a bare date the parser padded — unless we record
    which format matched, at the moment it matched.

    Before this, all three formats fell into one column and a date-only record
    read as a precise sampling minute.

    ⚠️ The '%Y-%m-%d' fallback is real but, measured against every leg on
    production 2026-09-10, NEVER TAKEN: MEMENTO always ships a full
    'YYYY-MM-DD HH:MM' string, padding the time to 00:00 INSIDE it when the
    time is unknown. So this function alone labels 100% of samples 'minute',
    including all 59,295 that sit at midnight. It is kept because it is
    correct about the string, and because a future export could omit the time.
    The padding is caught one level up — see `_leg_is_month_dated`.
    """
    s = (v or "").strip()
    for fmt, precision in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc), precision
        except ValueError:
            continue
    return None, None


def _is_month_stamp(t) -> bool:
    """Midnight on the first of a month — the shape MEMENTO pads a month into."""
    return t is not None and (t.day, t.hour, t.minute, t.second) == (1, 0, 0, 0)


def _leg_is_month_dated(rows: list[dict]) -> bool:
    """True when EVERY sample of a leg is stamped midnight-on-the-first.

    MEMENTO pads inside the timestamp string, so `_parse_time` cannot see it:
    a month-only record arrives as a full 'YYYY-MM-01 00:00' and matches the
    minute format like any other. Measured on production 2026-09-10, 100% of
    218,271 samples came back "minute", including all 59,295 at midnight.

    What does show is the SHAPE OF A WHOLE LEG. Real fixture
    `leg_300_baltic.csv`: 978 rows, 11 distinct timestamps, every one of them
    midnight on the first of a month (2011-08-01, 2011-11-01, 2012-02-01 …).
    A cruise does not sample only on the first of the month at midnight.

    Measured over all 294 legs:

        legs where EVERY sample is midnight-on-the-1st .... 27  -> 6,724 samples
        legs MIXED (some are, some are not) .............. 41  -> 2,098 samples

    ⛔ The 41 mixed legs are deliberately NOT touched. In a leg carrying real
    varying minutes, a sample at exactly 00:00 on the 1st may be a genuine
    cast; nothing in the data separates it from a pad, so 2,098 samples stay
    labelled "minute" and the ambiguity is recorded in the layer rule instead
    of being guessed away.

    ⛔ Midnight alone is not enough either — 59,295 samples sit at midnight and
    most belong to legs whose other samples carry real minutes.
    """
    times = [r["sample_time"] for r in rows if r["sample_time"] is not None]
    if len(times) <= 1:
        # A leg of one shows no pattern. The smallest real all-padded leg on
        # production holds 4 samples, so this costs nothing.
        return False
    return all(_is_month_stamp(t) for t in times)


def build_samples(csv_text: str, set_name: str) -> list[dict]:
    """Parse one leg CSV into sample dicts. Dynamic param columns -> first-class
    cols (FIRST_CLASS) + a params JSONB carrying every other value AND every flag."""
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader, None)
    if not header:
        return []
    cols = [h.strip() for h in header]
    lower = [c.lower() for c in cols]
    idx = {name: i for i, name in enumerate(lower)}
    # parameter columns = everything not fixed and not a *_flag
    param_cols = [c for c in lower if c not in _FIXED and not c.endswith("_flag")]

    out: list[dict] = []
    for row in reader:
        if not row or len(row) < len(cols):
            continue
        lat = _num(row[idx["latitude"]])
        lon = _num(row[idx["longitude"]])
        if lat is None or lon is None:
            continue
        sample_time, time_precision = _parse_time(row[idx["time"]])
        params: dict = {}
        for p in param_cols:
            params[p] = _num(row[idx[p]])
            fcol = p + "_flag"
            if fcol in idx:
                fv = row[idx[fcol]].strip()
                params[fcol] = int(float(fv)) if fv != "" else None
        rec = {
            "set_name": set_name,
            "station": (row[idx["station"]].strip() or None) if "station" in idx else None,
            "sample_time": sample_time,
            # ⛔ Carried beside the value, never derived from it. See _parse_time.
            "time_precision": time_precision,
            "lat": lat,
            "lon": lon,
            "depth_m": _num(row[idx["depth [m]"]]),
            "label": row[idx["label"]].strip() if "label" in idx else None,
            "params": params,
        }
        for fc in FIRST_CLASS:
            rec[fc] = params.get(fc)
            params.pop(fc, None)  # first-class values live top-level only; their _flag stays in params
        rec["decade"] = (sample_time.year // 10 * 10) if sample_time else None
        rec["cast_id"] = _cast_id(rec)
        out.append(rec)

    # ⛔ Decided per LEG, after the whole leg is parsed, because the evidence is
    # cardinality and a single row cannot show it. `_parse_time` sees only one
    # string at a time and MEMENTO pads inside the string, so this is the only
    # level at which the padding is visible.
    if _leg_is_month_dated(out):
        for rec in out:
            rec["time_precision"] = "month"
    return out


def _cast_id(rec: dict) -> str:
    key = "|".join([
        rec["set_name"] or "", rec.get("station") or "",
        rec["sample_time"].isoformat() if rec["sample_time"] else "",
        f"{rec['lat']:.5f}", f"{rec['lon']:.5f}",
    ])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def derive_casts(samples: list[dict]) -> list[dict]:
    """Group samples by cast_id; compute counts, depth range, gas presence, and the
    shallowest non-null gas value (surface representative for dot colouring)."""
    by: dict[str, list[dict]] = {}
    for s in samples:
        by.setdefault(s["cast_id"], []).append(s)
    casts = []
    for cast_id, grp in by.items():
        grp_sorted = sorted(grp, key=lambda s: (s["depth_m"] if s["depth_m"] is not None else 1e9))
        depths = [s["depth_m"] for s in grp if s["depth_m"] is not None]
        first = grp_sorted[0]

        def surf(gas):
            """Shallowest *water* value: skips MEMENTO's own `_Air` rows and
            `<gas>_flag == 9` (missing-as-zero), plus non-positive values.
            The cruise-median rule cannot run here — it needs the whole archive —
            so `_recompute_memento_atmospheric()` refines this afterwards."""
            for s in grp_sorted:
                v = s.get(gas)
                if v is None or v <= 0:
                    continue
                label = s.get("label")
                if label is not None and str(label).endswith("_Air"):
                    continue
                if s["params"].get(f"{gas}_flag") == 9:
                    continue
                return v
            return None

        casts.append({
            "cast_id": cast_id,
            "set_name": first["set_name"],
            "station": first["station"],
            "sample_time": first["sample_time"],
            "time_precision": first["time_precision"],
            "lat": first["lat"],
            "lon": first["lon"],
            "decade": first["decade"],
            "n_samples": len(grp),
            "min_depth_m": min(depths) if depths else None,
            "max_depth_m": max(depths) if depths else None,
            "has_ch4": any(s.get("ch4") is not None or (s["params"].get("ch4_kg") is not None) for s in grp),
            "has_n2o": any(s.get("n2o") is not None or (s["params"].get("n2o_kg") is not None) for s in grp),
            "ch4_surf": surf("ch4"),
            "n2o_surf": surf("n2o"),
        })
    return casts


# ── Authenticated download (one-time scrape; creds from env, never stored) ──

#: How many times to re-attempt the login handshake before giving up.
LOGIN_ATTEMPTS = 3


def login_session(email: str, password: str, *, attempts: int = LOGIN_ATTEMPTS,
                  sleep=None):
    """VERIFIED flow (2026-06-22): the login form POSTs to /user/authenticate (NOT
    /user/login) with fields `email` + `password`; a successful POST sets JSESSIONID
    and redirects to /user/agree. Visiting /user/agree + / finalises the session so
    /bottle/list CSV downloads work.

    ⛔ Retried, because this is the FIRST call of the whole sync and everything
    downstream depends on it. Observed live 2026-09-10: a forced run died on
    `ReadTimeout: portal.geomar.de ... read timeout=60` during the handshake and
    the entire ingest was discarded, credentials perfectly valid. Check 25e —
    the same shape as the ArgoVis vocabulary call.

    ⛔ A REJECTED credential is not retried. Hammering a login form with a
    password the server has already refused is how an account gets locked; only
    transport failures earn another attempt. That is why the JSESSIONID check
    raises immediately instead of continuing the loop.
    """
    import time as _time

    import requests

    sleep = sleep or _time.sleep
    last = None
    for attempt in range(attempts):
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 abyssal-claims/1.0 (data ingest)"
        try:
            s.get(_BASE + "/user/login", timeout=60)
            r = s.post(_BASE + "/user/authenticate",
                       data={"email": email, "password": password}, timeout=60,
                       allow_redirects=False)
        except requests.exceptions.RequestException as exc:
            last = exc
            log.warning("memento: login transport failure (attempt %d/%d): %s",
                        attempt + 1, attempts, type(exc).__name__)
            if attempt + 1 < attempts:
                sleep(2 * (attempt + 1))
            continue
        if "JSESSIONID" not in s.cookies:
            # ⛔ Deliberately NOT retried. See the docstring.
            raise RuntimeError(
                f"MEMENTO login failed (status {r.status_code}); check credentials")
        s.get(_BASE + "/user/agree", timeout=60)
        s.get(_BASE + "/", timeout=60)
        return s
    raise last if last else RuntimeError("MEMENTO login failed: no attempt was made")


def fetch_leg_index(session) -> list[dict]:
    """Return [{'id','name'}] for all legs by parsing the #legs <select> on the home page."""
    html = session.get(_BASE + "/", timeout=60).text
    m = re.search(r'<select[^>]*id="legs"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return []
    return [{"id": v, "name": re.sub(r"\s+", " ", n).strip()}
            for v, n in re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', m.group(1), re.S)]


def download_leg_csv(session, leg_id: str) -> str:
    r = session.get(_CSV_TPL.format(id=leg_id), timeout=180)
    r.raise_for_status()
    return r.text


async def load_memento(pool, samples: list[dict], casts: list[dict]) -> int:
    """Replace memento tables with the freshly scraped snapshot.

    ⛔ THIS TRUNCATES. The previous version of this docstring said "never called with
    empty input (caller guards) so a failed scrape never wipes a good load", and that
    reassurance was wrong in the case that actually happened. The caller's guard only
    caught a scrape yielding ZERO samples. A PARTIAL scrape sailed straight through:
    on 2026-09-08 two of 313 legs died on a momentary "Connection refused" and this
    function replaced a complete table with one 9,831 casts smaller — 155,418 down to
    145,587 — with nothing louder than a WARNING anywhere in the run.

    The caller now also refuses to publish a scrape that lost legs AND carries fewer
    samples than are already stored. Keep that check there: by the time control
    reaches this function the TRUNCATE is one statement away and it does not come
    back."""
    import json
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE memento_samples, memento_casts")
            await conn.executemany(
                """INSERT INTO memento_samples
                   (cast_id,set_name,station,sample_time,time_precision,lat,lon,depth_m,label,decade,
                    ch4,n2o,n2o_perc,o2,temp,sal,params,geom)
                   VALUES ($1,$2,$3,$4,$17,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,
                           ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                [(s["cast_id"], s["set_name"], s["station"], s["sample_time"], s["lat"], s["lon"],
                  s["depth_m"], s["label"], s["decade"], s["ch4"], s["n2o"], s["n2o_perc"],
                  s["o2"], s["temp"], s["sal"], json.dumps(s["params"]),
                  s["time_precision"]) for s in samples],
            )
            await conn.executemany(
                """INSERT INTO memento_casts
                   (cast_id,set_name,station,sample_time,time_precision,lat,lon,decade,n_samples,min_depth_m,
                    max_depth_m,has_ch4,has_n2o,ch4_surf,n2o_surf,geom)
                   VALUES ($1,$2,$3,$4,$15,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                           ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                [(c["cast_id"], c["set_name"], c["station"], c["sample_time"], c["lat"], c["lon"],
                  c["decade"], c["n_samples"], c["min_depth_m"], c["max_depth_m"],
                  c["has_ch4"], c["has_n2o"], c["ch4_surf"], c["n2o_surf"],
                  c["time_precision"]) for c in casts],
            )
    return len(samples)
