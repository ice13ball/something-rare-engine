# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo DOXY import: GDAC synthetic-profile index -> changed floats' Sprof files -> argo_doxy_profiles.

Runs ONLY inside argo_doxy_worker (own cgroup). ⛔ Never imported by the API process.

- The index (8 MB gz) says which DOXY profiles exist and when each changed (`date_update`). Only floats with a
  profile whose stored stamp differs are downloaded, one Sprof at a time through SCRATCH_DIR.
- ONE transaction per float: upsert the changed profiles, delete the ones the index no longer lists. A float
  that fails (network, truncated or corrupt file, unexpected shape) keeps its live rows and is counted; the run
  goes on. Only a lost database connection ends the run (every later float would fail the same way).
- Memory is bounded by one profile: the Sprof is read through `open_sprof` (a generator) and every profile is
  turned into its thinned stored row before the next is read.
- A profile the index lists with DOXY whose Sprof carries no usable value is remembered in argo_doxy_empty, so
  its float is not downloaded again on every run.
- An index listing < 90 % of the stored profiles blocks the whole run before anything is written or deleted.
- Deletions are gated on the deletions themselves (a net-count gate is blind to a lost small DAC offset by new
  profiles): all held above max(500, 1 % of stored); one DAC's held when ALL of its keys, or more than 10 % (and
  more than DELETE_DAC_MIN), would go; keys on index lines we could not interpret are never deleted; more than 1 %
  malformed lines is a format change (outcome 'schema'). Upserts always proceed.
- A stored profile whose re-read Sprof carries no usable DOXY any more ("emptied") is a deletion too, and goes through
  the SAME holds, per DAC and globally, counted together with that DAC's vanished profiles: a DAC reprocessing its
  files with blanked DOXY is the same outage as a DAC vanishing from the index. Emptied profiles are collected while
  a DAC's floats are processed and judged once that DAC is finished (so the verdict does not depend on float order);
  held ones keep their live row and write no marker, are reported as `empties_held` (and in `deletions_held`), and
  are re-read on the next run. A DAC the run did not finish (budget, disk, unreachable) is not judged: its emptied
  profiles stay as they are and are re-read next run.
- A change to OUR rules (RULES_VERSION) re-reads every float holding a row or empty marker built under another
  version, spread over runs by the budget; rows carry the version, so a half-done re-read resumes.
- The run stops between floats at RUN_BUDGET_S (outcome 'partial', floats left pending for the next tick) or
  when the disk passes DISK_STOP (outcome 'disk'), or after FLOAT_FAILURE_STREAK floats in a row failed on the
  network (outcome 'unreachable': transient, no back-off, those floats stay pending; see argo_doxy_rules)."""
from __future__ import annotations

import asyncio
import collections
import gzip
import http.client
import io
import json
import logging
import os
import pathlib
import shutil
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

import asyncpg

import db
from ingestion import USER_AGENT
from ingestion.argo_doxy_ddl import STAMP_PROFILES_SQL, UPSERT_EMPTY_SQL, UPSERT_SQL
from ingestion.argo_doxy_rules import (FLOAT_FAILURE_STREAK, INDEX_URL, PROFILE_COLUMNS, RULES_VERSION, SHRINK_LIMIT,
                                       SOURCE, UNREACHABLE_OUTCOME, UNREACHABLE_PREFIX,
                                       UPDATED_WITH_REJECTS_PREFIX, IndexRow, build_profile, check_index_header,
                                       index_line_key, parse_index_line, profile_stamp, sprof_url)
from ingestion.argo_doxy_sprof import open_sprof
from sync_log import log_sync, log_sync_skipped

log = logging.getLogger("argo_doxy")
SCRATCH_DIR = pathlib.Path(os.getenv("ARGO_DOXY_SCRATCH_DIR", "/var/cache/abyssal-argo-doxy"))
RUN_BUDGET_S = 3.5 * 3600
DISK_STOP = 0.83
DISK_CHECK_EVERY = 50
MAX_SPROF_BYTES = 400 * 2**20         # largest measured 96 MB; a 400 MB file is a source anomaly, not data
HTTP_TIMEOUT_S = 120                  # one socket read; a trickle is bounded by FETCH_DEADLINE_S, not by this
FETCH_DEADLINE_S = 20 * 60            # wall clock for ONE Sprof (the biggest, 96 MB, needs < 2 min on a healthy link);
#                                       must stay well under the unit's 1 h margin (a test pins it)
FLOAT_FAILURE_LIMIT_MIN = 10
FLOAT_FAILURE_LIMIT_FRAC = 0.02
DELETE_ALL_FLOOR = 500                # deletions held entirely above max(this, DELETE_ALL_FRAC of stored)
DELETE_ALL_FRAC = 0.01
DELETE_DAC_FRAC = 0.10                # one DAC's deletions held above this share of its stored keys ...
DELETE_DAC_MIN = 5                    # ... when more than this many (a 7-profile DAC losing 1 is not an outage)
MALFORMED_LIMIT = 0.01                # more malformed index lines than this share of all data lines = format change
_CONNECTION_ERRORS = (asyncpg.PostgresConnectionError, asyncpg.InterfaceError)


class FloatFailed(Exception):
    pass


class FetchDeadline(FloatFailed):
    """One Sprof download outlived FETCH_DEADLINE_S (a trickle: every read within HTTP_TIMEOUT_S, the file never ends)."""


class ConnectionLost(Exception):
    """The database connection died under a float: the run ends instead of failing every remaining float."""


def fetch_index() -> bytes:
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
        return r.read()


def fetch_sprof(dac: str, wmo: str, dest: pathlib.Path, clock=time.monotonic) -> int:
    req = urllib.request.Request(sprof_url(dac, wmo), headers={"User-Agent": USER_AGENT})
    deadline = clock() + FETCH_DEADLINE_S
    n = 0
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r, open(dest, "wb") as f:
        # ⛔ read1, not read(n): HTTPResponse.read(n) loops inside until n bytes have arrived, so a server delivering
        # a few bytes per HTTP_TIMEOUT_S never returns to this loop and the deadline below is never looked at.
        # read1 returns what one recv gave; the per-read socket timeout still bounds each wait.
        while chunk := r.read1(64 * 1024):
            if clock() > deadline:
                raise FetchDeadline(f"Sprof download still running after {FETCH_DEADLINE_S} s ({n} B so far)")
            n += len(chunk)
            if n > MAX_SPROF_BYTES:
                raise FloatFailed(f"Sprof larger than {MAX_SPROF_BYTES} B")
            f.write(chunk)
        declared = r.headers.get("Content-Length")
        if declared is not None and n != int(declared):      # read(n) raised this itself; read1 just returns b""
            raise http.client.IncompleteRead(b"", int(declared) - n)
    return n


def is_network_failure(e: BaseException) -> bool:
    """A float failure that says the GDAC (or the path to it) is down: connection, timeout, TLS, a response cut
    short, a 5xx, a download over its deadline. NOT: 4xx (the server answered), a corrupt or oversized file, an
    unexpected shape, a local disk error."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError,
                          http.client.HTTPException, FetchDeadline))


def _disk_used_fraction() -> float:
    u = shutil.disk_usage(SCRATCH_DIR if SCRATCH_DIR.exists() else "/")
    return u.used / u.total


def parse_index(gz: bytes, stored_keys=frozenset()):
    """-> (rows, rejects, latest date_update, untrusted keys).

    `untrusted` = keys the index mentions but that we cannot read a state from: both lines of a duplicate, a
    malformed DOXY line whose path still parses, and (only for keys in `stored_keys`) a line that no longer lists
    DOXY. A stored row on an untrusted key must never be deleted on the strength of that line."""
    rows: dict[str, IndexRow] = {}
    dup: set[str] = set()
    untrusted: set[str] = set()
    rejects: collections.Counter = collections.Counter()
    latest: datetime | None = None
    header_seen = False
    total = 0
    with gzip.open(io.BytesIO(gz), "rt", encoding="ascii", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            if not header_seen:
                check_index_header(line)                     # ValueError -> outcome 'schema'
                header_seen = True
                continue
            total += 1
            got = parse_index_line(line)
            if got is None:
                if stored_keys:
                    k = index_line_key(line)
                    if k is not None and k in stored_keys:
                        untrusted.add(k)
                        rejects["index_doxy_dropped"] += 1
                continue
            if isinstance(got, str):
                rejects[got] += 1
                k = index_line_key(line)
                if k is not None:
                    untrusted.add(k)
                continue
            if got.key in rows or got.key in dup:
                # two index lines for one key: neither can be trusted, both are dropped from the plan
                rejects["index_duplicate"] += 1 + (got.key in rows)
                rows.pop(got.key, None)
                dup.add(got.key)
                untrusted.add(got.key)
                continue
            rows[got.key] = got
            latest = got.date_update if latest is None or got.date_update > latest else latest
    if not header_seen:
        raise ValueError("index has no column line")
    if rejects["index_malformed"] > MALFORMED_LIMIT * total:
        raise ValueError(f"index format changed: {rejects['index_malformed']} of {total} lines are malformed")
    return rows, rejects, latest, untrusted


def plan_floats(index_rows, stored, outdated=frozenset(), untrusted=frozenset()):
    """-> (need, gone). A profile is needed when its stored stamp differs from the index's or its stored row was built
    under another RULES_VERSION (`outdated`). `gone` = stored keys the index no longer lists, minus `untrusted`."""
    need: dict[tuple[str, str], list[IndexRow]] = collections.defaultdict(list)
    for row in index_rows.values():
        if stored.get(row.key) != row.date_update or row.key in outdated:
            need[(row.dac, row.wmo)].append(row)
    gone: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for key in stored.keys() - index_rows.keys() - untrusted:
        dac, wmo, _ = key.split("_", 2)
        gone[(dac, wmo)].append(key)
    return dict(need), dict(gone)


def _all_held(total: int, n_stored: int) -> bool:
    return total > max(DELETE_ALL_FLOOR, DELETE_ALL_FRAC * n_stored)


def _dac_held(n: int, dac_stored: int) -> bool:
    return n == dac_stored or (n > DELETE_DAC_MIN and n > DELETE_DAC_FRAC * dac_stored)


def hold_deletions(gone, stored):
    """-> (gone to apply, held: {'all': n} or {dac: n}). Gate on the deletions themselves:
    - all held above max(DELETE_ALL_FLOOR, DELETE_ALL_FRAC of stored);
    - one DAC held when every stored key of it would go, or more than DELETE_DAC_FRAC of them (and more than
      DELETE_DAC_MIN). A DAC vanishing from a regenerated index is an outage until proven otherwise."""
    total = sum(len(v) for v in gone.values())
    if _all_held(total, len(stored)):
        return {}, {"all": total}
    per_dac_stored = collections.Counter(k.split("_", 1)[0] for k in stored)
    per_dac_gone = collections.Counter()
    for (dac, _), keys in gone.items():
        per_dac_gone[dac] += len(keys)
    held_dacs = {d: n for d, n in per_dac_gone.items() if _dac_held(n, per_dac_stored[d])}
    kept = {fl: keys for fl, keys in gone.items() if fl[0] not in held_dacs}
    return kept, held_dacs


def _parse_float(path: pathlib.Path, rows: list[IndexRow], rejects: collections.Counter):
    """-> (profile tuples to upsert, [(key, stamp)] of profiles that now carry no DOXY value).

    Streams the Sprof: only the (cycle, direction) pairs in `rows` are read, one profile at a time. A pair that
    occurs twice in one file is resolved by `prefer_duplicate` and counted as 'sprof_duplicate'."""
    by_pair = {(r.cycle, r.descending): r for r in rows}
    built: dict[tuple[int, bool], dict | None] = {}
    with open_sprof(path, want=by_pair) as (upd, profiles):
        for raw in profiles:
            pair = (raw["cycle"], raw["descending"])
            p = build_profile(raw, by_pair[pair], upd)
            if pair in built:
                rejects["sprof_duplicate"] += 1
                if not prefer_duplicate(p, built[pair]):
                    continue
            built[pair] = p
    out, empty = [], []
    for pair, row in by_pair.items():
        if pair not in built:
            rejects["not_in_sprof"] += 1                 # the Sprof lags its index: keep the old row, retry later
            continue
        p = built[pair]
        if p is None:
            rejects["no_doxy_values"] += 1
            empty.append((row.key, profile_stamp(row, upd)))
            continue
        out.append(tuple(p[c] for c in PROFILE_COLUMNS))
    return out, empty


def _usefulness(p: dict | None) -> tuple:
    return (p is not None, bool(p and p["drawable"]), p["n_good"] if p else 0, p["n_levels_source"] if p else 0)


def prefer_duplicate(new: dict | None, old: dict | None) -> bool:
    """Duplicate (cycle, direction) inside ONE Sprof: True when `new` (the later entry) replaces `old`.

    Argo names one file per (cycle, direction) (S<R|D><wmo>_<cycle>[D].nc) and the index lists each once. Measured
    2026-10-06 on 288 randomly chosen DOXY floats from the GDAC (35 000 DOXY profiles; the two largest, > 70 MB,
    were skipped): ZERO such duplicates. So this is a defence against a DAC error, and it must not guess: keep
    the entry a map can use, i.e. drawable, then more good adjusted levels, then more levels. A tie keeps the
    FIRST entry — in an Argo multi-profile file the primary sampling profile comes first, a secondary
    (near-surface) one after it, so 'the last in the file' would prefer the wrong one. The loser is counted as
    `sprof_duplicate`, never silently dropped."""
    return _usefulness(new) > _usefulness(old)


async def _process_float(conn, fl, rows, gone_keys, fetch, rejects, live_keys=frozenset()):
    """-> (upserted, deleted, emptied). `emptied` = [(key, stamp)] of STORED profiles (`live_keys`) whose new Sprof
    carries no usable DOXY: they are neither deleted nor marked here, the caller judges them against the deletion
    holds once the whole DAC is done (see _apply_empties). An empty profile that was never stored is just marked."""
    dac, wmo = fl
    path = SCRATCH_DIR / f"{dac}_{wmo}_Sprof.nc"
    local: collections.Counter = collections.Counter()
    try:
        upserts, empty = [], []
        if rows:
            await asyncio.to_thread(fetch, dac, wmo, path)
            upserts, empty = await asyncio.to_thread(_parse_float, path, rows, local)
        written_keys = [u[0] for u in upserts]
        emptied = [(k, st) for k, st in empty if k in live_keys]
        empty = [(k, st) for k, st in empty if k not in live_keys]
        drop_profiles = list(gone_keys)
        drop_empty = list(gone_keys) + written_keys
        try:
            async with conn.transaction():
                deleted = 0
                if drop_profiles:
                    res = await conn.execute("DELETE FROM argo_doxy_profiles WHERE profile_key = ANY($1::text[])",
                                             drop_profiles)
                    deleted = int(res.split()[-1])
                if drop_empty:
                    await conn.execute("DELETE FROM argo_doxy_empty WHERE profile_key = ANY($1::text[])", drop_empty)
                if upserts:
                    await conn.executemany(UPSERT_SQL, upserts)
                if upserts:
                    await conn.execute(STAMP_PROFILES_SQL, RULES_VERSION, written_keys)
                if empty:
                    await conn.executemany(UPSERT_EMPTY_SQL, [(k, st, RULES_VERSION) for k, st in empty])
        except _CONNECTION_ERRORS as e:
            raise ConnectionLost(f"{type(e).__name__}: {e}") from e
        rejects.update(local)                             # counted only for a float that committed
        return len(upserts), deleted, emptied
    finally:
        path.unlink(missing_ok=True)


async def _apply_empties(conn, emptied) -> int:
    """Delete the live rows of `emptied` [(key, stamp)] and remember them as empty, in one transaction -> deleted."""
    try:
        async with conn.transaction():
            res = await conn.execute("DELETE FROM argo_doxy_profiles WHERE profile_key = ANY($1::text[])",
                                     [k for k, _ in emptied])
            await conn.executemany(UPSERT_EMPTY_SQL, [(k, st, RULES_VERSION) for k, st in emptied])
    except _CONNECTION_ERRORS as e:
        raise ConnectionLost(f"{type(e).__name__}: {e}") from e
    return int(res.split()[-1])


def _clear_scratch() -> None:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    for p in SCRATCH_DIR.glob("*.nc"):
        p.unlink(missing_ok=True)


async def sync_argo_doxy(*, fetch_index=fetch_index, fetch_sprof=fetch_sprof, budget_s: float = RUN_BUDGET_S,
                         clock=time.monotonic, disk_used=None) -> dict:
    disk_used = disk_used or _disk_used_fraction         # resolved at call time, so a test can replace it
    _clear_scratch()
    try:
        return await _run(fetch_index, fetch_sprof, budget_s, clock, disk_used)
    except Exception as e:                               # nothing below may leave the run with no recorded outcome
        log.exception("argo-doxy: run failed")
        try:
            await log_sync_skipped(SOURCE, f"error: {type(e).__name__}: {str(e)[:200]}")
        except Exception:
            log.warning("argo-doxy: could not record the failure either")
        return {"outcome": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        _clear_scratch()


async def _run(fetch_index, fetch_sprof, budget_s, clock, disk_used) -> dict:
    try:
        gz = await asyncio.to_thread(fetch_index)
    except Exception as e:
        log.warning("argo-doxy: index download failed: %s: %s", type(e).__name__, e)
        await log_sync_skipped(SOURCE, f"index failed: {type(e).__name__}, will retry on the next timer run")
        return {"outcome": "index failed"}
    async with db.pool.acquire() as conn:
        run_started = await conn.fetchval("SELECT clock_timestamp()")
        stored: dict = {}
        outdated: set[str] = set()                       # rows / markers built under another RULES_VERSION
        live: set[str] = set()                           # keys with a stored (drawn or not) profile row
        # profiles with no usable DOXY are part of what the index "has already been seen to list"
        for table in ("argo_doxy_profiles", "argo_doxy_empty"):
            for r in await conn.fetch(f"SELECT profile_key, gdac_date_update, rules_version FROM {table}"):
                stored[r["profile_key"]] = r["gdac_date_update"]
                if table == "argo_doxy_profiles":
                    live.add(r["profile_key"])
                if r["rules_version"] != RULES_VERSION:
                    outdated.add(r["profile_key"])
        try:
            index_rows, rejects, latest, untrusted = await asyncio.to_thread(parse_index, gz, frozenset(stored))
        except ValueError as e:
            await log_sync_skipped(SOURCE, f"schema: {e}")
            return {"outcome": "schema", "error": str(e)}
        if stored and len(index_rows) < SHRINK_LIMIT * len(stored):
            msg = (f"blocked: the index lists {len(index_rows)} DOXY profiles, {len(stored)} are stored "
                   f"(more than {round((1 - SHRINK_LIMIT) * 100)} % fewer); nothing written or deleted")
            await log_sync_skipped(SOURCE, msg)
            return {"outcome": "blocked", "error": msg}
        need, gone = plan_floats(index_rows, stored, outdated, untrusted)
        gone_planned = {dac: sum(len(v) for (d, _), v in gone.items() if d == dac) for dac in {d for d, _ in gone}}
        gone, held = hold_deletions(gone, stored)
        floats = sorted(set(need) | set(gone))
        per_dac_stored = collections.Counter(k.split("_", 1)[0] for k in stored)
        start = clock()
        done = written = deleted = 0
        failed: dict[str, str] = {}
        empties_held: dict[str, int] = {}
        emptied_by_dac: dict[str, list] = collections.defaultdict(list)
        empties_applied = 0
        streak = 0                                       # consecutive floats that failed on the network
        stop = None

        async def judge_empties(dac: str) -> int:
            """Stored profiles of `dac` that lost their DOXY: apply or hold, by the rules of vanished profiles."""
            nonlocal empties_applied
            items = emptied_by_dac.pop(dac, [])
            if not items:
                return 0
            n = len(items)
            if (_all_held(sum(gone_planned.values()) + empties_applied + n, len(stored))
                    or _dac_held(gone_planned.get(dac, 0) + n, per_dac_stored[dac])):
                empties_held[dac] = n
                log.warning("argo-doxy: %d stored %s profiles lost all DOXY values: held, live rows kept", n, dac)
                return 0
            try:
                deleted_now = await _apply_empties(conn, items)
            except ConnectionLost:
                raise
            except Exception as e:                       # this DAC's batch rolled back whole: rows stay, run goes on
                if conn.is_closed():
                    raise ConnectionLost(f"{type(e).__name__}: {e}") from e
                failed[f"{dac}/emptied"] = f"{type(e).__name__}: {str(e)[:160]}"
                rejects["failed_emptied_profiles"] += n
                log.warning("argo-doxy: %s emptied-profile batch failed: %s", dac, failed[f"{dac}/emptied"])
                return 0
            empties_applied += n
            return deleted_now

        cur_dac = None
        for n, fl in enumerate(floats):
            if fl[0] != cur_dac:                         # floats are sorted: the previous DAC is complete
                if cur_dac is not None:
                    deleted += await judge_empties(cur_dac)
                cur_dac = fl[0]
            if clock() - start > budget_s:
                stop = "partial"
                break
            if n % DISK_CHECK_EVERY == 0 and disk_used() > DISK_STOP:
                stop = "disk"
                break
            try:
                w, d, emptied = await _process_float(conn, fl, need.get(fl, []), gone.get(fl, []), fetch_sprof,
                                                     rejects, live)
                written += w
                deleted += d
                emptied_by_dac[fl[0]] += emptied
                if need.get(fl):
                    streak = 0                           # a download went through
            except ConnectionLost:
                raise
            except Exception as e:                       # one float never sinks the run; its live rows stay
                if conn.is_closed():
                    raise ConnectionLost(f"{type(e).__name__}: {e}") from e
                failed[f"{fl[0]}/{fl[1]}"] = f"{type(e).__name__}: {str(e)[:160]}"
                rejects["failed_float_profiles"] += len(need.get(fl, []))
                log.warning("argo-doxy: float %s/%s failed: %s", fl[0], fl[1], failed[f"{fl[0]}/{fl[1]}"])
                streak = streak + 1 if is_network_failure(e) else 0
            done += 1
            if streak >= FLOAT_FAILURE_STREAK:           # the GDAC is down: stop hammering it, keep these pending
                stop = UNREACHABLE_OUTCOME
                done -= streak
                break
        else:
            if cur_dac is not None:                      # every float done: the last DAC is complete too
                deleted += await judge_empties(cur_dac)
        pending = len(floats) - done
        limit = max(FLOAT_FAILURE_LIMIT_MIN, int(FLOAT_FAILURE_LIMIT_FRAC * len(floats)))
        if stop == UNREACHABLE_OUTCOME:
            outcome = stop
        elif failed and len(failed) >= limit:
            outcome = "error"
        elif stop:
            outcome = stop
        elif written or deleted:
            outcome = "updated"
        else:
            outcome = "unchanged"
        counts = await conn.fetchrow("SELECT count(*) AS n, count(*) FILTER (WHERE drawable) AS d "
                                     "FROM argo_doxy_profiles")
        report = {**rejects, "failed_floats": dict(list(failed.items())[:50]), "n_failed_floats": len(failed)}
        if empties_held:
            report["empties_held"] = empties_held
        all_held = {k: held.get(k, 0) + empties_held.get(k, 0) for k in {*held, *empties_held}}
        if all_held:
            report["deletions_held"] = all_held          # what /meta shows: vanished AND emptied profiles held
        complete = pending == 0 and outcome in ("updated", "unchanged")
        current = (complete and not failed and not rejects["not_in_sprof"]      # every row built under RULES_VERSION
                   and not empties_held)
        await conn.execute(
            "UPDATE argo_doxy_source SET index_bytes=$1, index_date_update_max=$2, n_index_doxy=$3, "
            "n_profiles=$4, n_drawable=$5, pending_floats=$6, last_rejects=$7::jsonb, last_rejects_at=now(), "
            "loaded_at = CASE WHEN $8 OR loaded_at IS NULL AND $4 > 0 THEN now() ELSE loaded_at END, "
            "last_complete_at = CASE WHEN $9 THEN now() ELSE last_complete_at END, "
            "refresh_requested_at = CASE WHEN $9 AND refresh_requested_at <= $10 THEN NULL "
            "ELSE refresh_requested_at END, "
            "rules_version = CASE WHEN $11 THEN $12 ELSE rules_version END WHERE id = 1",
            len(gz), latest, len(index_rows), counts["n"], counts["d"], pending,
            json.dumps(report, allow_nan=False), bool(written or deleted), complete,
            run_started, current, RULES_VERSION)
    result = {"outcome": outcome, "floats_planned": len(floats), "floats_done": done, "written": written,
              "deleted": deleted, "rejects": dict(rejects), "failed_floats": failed, "pending": pending}
    if outcome in ("updated", "unchanged", "partial"):
        await log_sync(SOURCE, written, counts["n"])
        notes = []
        if failed:
            notes.append(f"{len(failed)} of {len(floats)} floats kept their previous rows")
        if all_held:
            notes.append("deletions held (" + ", ".join(f"{k}: {v}" for k, v in all_held.items()) + ")")
        if empties_held:
            notes.append("of which profiles that lost all DOXY values (" +
                         ", ".join(f"{k}: {v}" for k, v in empties_held.items()) + ")")
        if notes:
            await log_sync_skipped(SOURCE, f"{UPDATED_WITH_REJECTS_PREFIX}: " + "; ".join(notes))
    elif outcome == UNREACHABLE_OUTCOME:
        await log_sync_skipped(SOURCE, f"{UNREACHABLE_PREFIX}: {FLOAT_FAILURE_STREAK} floats in a row failed on the "
                                       f"network; stopped after {done} of {len(floats)}, the rest stays pending")
    elif outcome == "disk":
        await log_sync_skipped(SOURCE, f"disk above {int(DISK_STOP * 100)} %: stopped after {done} of "
                                       f"{len(floats)} floats")
    else:                                                # error
        await log_sync_skipped(SOURCE, f"error: {len(failed)} of {len(floats)} floats failed")
    return result
