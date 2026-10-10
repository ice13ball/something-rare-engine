# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Plankton map tiles (stage 2): filter vocabulary, tile SQL, the disk cache and the pre-bake.

No FastAPI here: the API route (domains/plankton.py) and the import worker (pre-bake after a swap) share it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass

import asyncpg

from pathlib import Path

from schema.plankton import DECADES, DEPTH_BANDS, GROUPS

log = logging.getLogger(__name__)

KEY_RE = re.compile(r"all|g[0-9a-f]{2}-d[0-9a-f]{3}-b[0-9a-f]-e[01]")
# int() alone also accepts "1_950", "+1" and non-ASCII digits; the client gets exactly one spelling per value.
_INT_RE = re.compile(r"-?[0-9]+", re.ASCII)


def _to_int(token: str) -> int:
    if not _INT_RE.fullmatch(token):
        raise ValueError(token)
    return int(token)


@dataclass(frozen=True)
class TileFilter:
    """One combination of the four map filters; every tuple in vocabulary order (canonical)."""
    groups: tuple[str, ...]
    decades: tuple[int, ...]
    bands: tuple[int, ...]
    edna: bool

    @property
    def key(self) -> str:
        """Cache key: "all" for the default view, else bitmasks over the vocabularies (path-safe)."""
        if self == DEFAULT_FILTER:
            return "all"
        gm = sum(1 << GROUPS.index(g) for g in self.groups)
        dm = sum(1 << DECADES.index(d) for d in self.decades)
        bm = sum(1 << DEPTH_BANDS.index(b) for b in self.bands)
        return f"g{gm:02x}-d{dm:03x}-b{bm:x}-e{int(self.edna)}"

    def sql_args(self) -> list:
        return [list(self.groups), list(self.decades), list(self.bands), self.edna]


DEFAULT_FILTER = TileFilter(GROUPS, DECADES, DEPTH_BANDS, True)


def _values(raw: str | None, vocab: tuple, convert, name: str) -> tuple:
    if raw is None or raw.strip() == "":
        return vocab
    chosen = set()
    for part in raw.split(","):
        token = part.strip()
        try:
            value = convert(token)
        except ValueError:
            raise ValueError(f"{name}: {token!r} is not a valid value") from None
        if value not in vocab:
            raise ValueError(f"{name}: {token!r} is not a valid value")
        chosen.add(value)
    return tuple(v for v in vocab if v in chosen)


def parse_filter(g: str | None = None, d: str | None = None, b: str | None = None,
                 e: str | None = None) -> TileFilter:
    """Validate the four query parameters against the fixed vocabulary; absent or empty = everything.
    Raises ValueError (the route answers 400) on any other value."""
    if e not in (None, "", "0", "1"):
        raise ValueError(f"e: {e!r} is not 0 or 1")
    return TileFilter(_values(g, GROUPS, str, "g"), _values(d, DECADES, _to_int, "d"),
                      _values(b, DEPTH_BANDS, _to_int, "b"), e != "0")


SITE_MIN_ZOOM = 7
TILE_STATEMENT_TIMEOUT = "10s"     # a long reader would hold up the monthly swap's ACCESS EXCLUSIVE lock
VERSION_RE = re.compile(r"[0-9]{14}-[0-9a-f]{6}")
MVT_EXTENT, MVT_BUFFER = 4096, 64
# The envelope the rows are selected by is the tile grown by the SAME buffer ST_AsMVTGeom clips with
# (fraction of the tile size), so a point within 64 px of an edge is emitted in both neighbouring tiles.
_ENV = f"ST_TileEnvelope($1::int, $2::int, $3::int, margin => {MVT_BUFFER / MVT_EXTENT})"
_GROUPS_ARRAY = "ARRAY[" + ", ".join(f"'{g}'" for g in GROUPS) + "]::text[]"


def grid_res(z: int) -> float:
    return 1.0 if z <= 3 else 0.25


# Facet rows of the combination asked for. ⛔ One predicate per facet ROW, so "copepoda + 2010s" can only
# match rows that are copepods AND from the 2010s (never copepods of one decade plus anything of another).
_FACET_WHERE = ("{a}.taxon_group = ANY($4::text[]) AND {a}.decade = ANY($5::smallint[]) "
                "AND {a}.depth_band = ANY($6::smallint[]) AND ($7::boolean OR NOT {a}.is_edna)")

# Per feature: total n, the group with the most matching observations (ties: alphabetical), the groups
# present as a bitmask (bit i = GROUPS[i]) and whether EVERY matching observation is eDNA.
_ROLLUP = ("sum(f.n)::bigint AS n, (array_agg(f.taxon_group ORDER BY f.n DESC, f.taxon_group))[1] AS top_group, "
           f"bit_or(1 << (array_position({_GROUPS_ARRAY}, f.taxon_group) - 1)) AS groups, "
           "bool_and(f.edna_only) AS edna_only")

# ⛔ Lock order (see ingestion/plankton_obis.SWAP_LOCK_ORDER): the version row is read FIRST (render), then
# plankton_sites -> plankton_site_facets, or plankton_grid_facets alone — never against that order, or a
# swap's single LOCK TABLE and a tile statement could deadlock. Postgres locks tables in the order the
# query text names them, so keep the FROM clauses in this order.
# Grid features have NO site_key column at all (ST_AsMVT writes a key even for an all-NULL column).
_GRID_FEATURES = f"""
SELECT c.n, c.top_group, c.groups, c.edna_only, c.geom
FROM (
    SELECT {_ROLLUP}, any_value(f.geom) AS geom
    FROM (
        SELECT g.cell_x, g.cell_y, g.taxon_group, sum(g.n)::bigint AS n,
               bool_and(g.is_edna) AS edna_only, any_value(g.geom_3857) AS geom
        FROM plankton_grid_facets g
        WHERE g.res = $8::real AND g.geom_3857 && {_ENV}
          AND {_FACET_WHERE.format(a='g')}
        GROUP BY g.cell_x, g.cell_y, g.taxon_group
    ) f
    GROUP BY f.cell_x, f.cell_y
) c"""

_SITE_FEATURES = f"""
SELECT c.n, c.top_group, c.groups, c.edna_only, s.site_key, s.geom_3857 AS geom
FROM (
    SELECT f.site_id, {_ROLLUP}
    FROM (
        SELECT sf.site_id, sf.taxon_group, sum(sf.n)::bigint AS n, bool_and(sf.is_edna) AS edna_only
        FROM plankton_sites s0 JOIN plankton_site_facets sf ON sf.site_id = s0.site_id
        WHERE s0.geom_3857 && {_ENV}
          AND {_FACET_WHERE.format(a='sf')}
        GROUP BY sf.site_id, sf.taxon_group
    ) f
    GROUP BY f.site_id
) c JOIN plankton_sites s ON s.site_id = c.site_id"""


def _is_site_zoom(z: int) -> bool:
    return z >= SITE_MIN_ZOOM


def _features_sql(z: int) -> str:
    return _SITE_FEATURES if _is_site_zoom(z) else _GRID_FEATURES


def _args(z: int, x: int, y: int, f: TileFilter) -> list:
    args = [z, x, y, *f.sql_args()]
    if not _is_site_zoom(z):
        args.append(grid_res(z))
    return args


async def tile_features(conn, z: int, x: int, y: int, f: TileFilter) -> list[dict]:
    """The features of one tile as rows (lon/lat in degrees): the same SQL render() encodes.
    site_key is None on grid features."""
    site_key = "t.site_key" if _is_site_zoom(z) else "NULL::text"
    rows = await conn.fetch(
        f"SELECT t.n, t.top_group, t.groups, t.edna_only, {site_key} AS site_key, "
        "ST_X(ST_Transform(t.geom, 4326)) AS lon, ST_Y(ST_Transform(t.geom, 4326)) AS lat "
        f"FROM ({_features_sql(z)}) t ORDER BY lon, lat", *_args(z, x, y, f))
    return [dict(r) for r in rows]


async def render(conn, z: int, x: int, y: int, f: TileFilter) -> tuple[str | None, bytes]:
    """(version, MVT bytes) from ONE statement: the tile and the version it is filed under come from one
    snapshot, even if a swap commits in between. Past TILE_STATEMENT_TIMEOUT asyncpg.QueryCanceledError
    propagates (the transaction/savepoint is rolled back) — the caller must not cache anything then.
    The version row is the first thing the statement reads: that is the head of the lock order."""
    cols = "t.n, t.top_group, t.groups, t.edna_only" + (", t.site_key" if _is_site_zoom(z) else "")
    sql = ("SELECT (SELECT version FROM plankton_tile_version WHERE id = 1) AS version, "
           "(SELECT ST_AsMVT(m, 'plankton', 4096, 'geom') FROM ("
           f"SELECT {cols}, "
           f"ST_AsMVTGeom(t.geom, ST_TileEnvelope($1::int, $2::int, $3::int), {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom "
           f"FROM ({_features_sql(z)}) t) m) AS mvt")
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{TILE_STATEMENT_TIMEOUT}'")
        row = await conn.fetchrow(sql, *_args(z, x, y, f))
    version = row["version"]
    return (version if version and VERSION_RE.fullmatch(version) else None), bytes(row["mvt"] or b"")


async def current_version(conn) -> str | None:
    """The live tile version, or None (aggregates not built yet, or the table is missing)."""
    try:
        async with conn.transaction():
            v = await conn.fetchval("SELECT version FROM plankton_tile_version WHERE id = 1")
    except asyncpg.UndefinedTableError:
        return None
    return v if v and VERSION_RE.fullmatch(v) else None


CACHE_CAP_BYTES = 2 * 1024 ** 3
CACHE_MAX_ENTRIES = 400_000   # files + directories; the 9.7 M inodes of the VPS root fs are shared with Postgres
PRUNE_TARGET = 0.9
PRUNE_EVERY = 256
STALE_TMP_S = 3600


def cache_root() -> Path:
    """Read at call time, so the worker unit and the tests can point it elsewhere."""
    return Path(os.getenv("PLANKTON_TILE_CACHE_DIR", "/var/cache/abyssal-plankton-tiles"))


def tile_path(root: Path, version: str, key: str, z: int, x: int, y: int) -> Path:
    """<root>/<version>/<filter key>/<z>/<x>/<y>.pbf. Only a well-formed version and key are ever joined
    into a path. That includes the client's `v` on the hit path, once VERSION_RE has matched it (the route
    does that before calling here, and this function checks again). It is safe because VERSION_RE admits
    only 14 ASCII digits, a hyphen and 6 lowercase hex digits: no `/`, no `..`, no NUL, no other character
    that could leave the cache root. An unknown but well-formed `v` is only a miss; the client can never
    name a file outside <root>/<version>/..."""
    if not VERSION_RE.fullmatch(version) or not KEY_RE.fullmatch(key):
        raise ValueError("unsafe tile cache path component")
    return root / version / key / str(int(z)) / str(int(x)) / f"{int(y)}.pbf"


def read_cached(path: Path) -> bytes | None:
    """The cached tile; b"" is a cached EMPTY tile (a hit), None a miss. Unreadable = a miss, never an
    error. A hit refreshes mtime: prune() removes the least recently USED files."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        os.utime(path)
    except OSError:
        pass
    return data


def _mkdirs(d: Path) -> None:
    """mkdir -p with every NEW directory forced to 0775: the umask (022 under systemd) would otherwise make
    them 0755 and the other user (API / worker) could not add tiles beside ours."""
    missing = []
    while not d.exists():
        missing.append(d)
        d = d.parent
    for m in reversed(missing):
        try:
            m.mkdir()
        except FileExistsError:
            continue
        # chmod would clear a setgid bit the kernel inherited; keep the parent's so the shared group sticks.
        setgid = os.stat(m.parent).st_mode & stat.S_ISGID
        os.chmod(m, 0o775 | setgid)


def write_cached(path: Path, data: bytes) -> bool:
    """Atomic write (temp file + rename). Only a COMPLETE render is ever passed here — a timed-out one never
    is — so a 0-byte file always means "empty tile", never "failed".
    ⛔ chmod 0664: mkstemp creates 0600, and on a directory with a default ACL the group bits become the ACL
    mask, so the other user (API `abyssal` / worker `ice13ball`) could not read the file at all.
    Returns False (and logs) when the cache is not writable: the caller still serves the tile."""
    try:
        _mkdirs(path.parent)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o664)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError as exc:
        log.warning("plankton tile cache not writable (%s)", type(exc).__name__)
        return False
    return True


def drop_other_versions(root: Path, keep: str) -> int:
    """Remove every version directory except `keep`. Only names that ARE versions — nothing else under the
    root is ever touched. Returns the number of directories removed."""
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    removed = 0
    for child in children:
        if child.name != keep and VERSION_RE.fullmatch(child.name) and child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


_BLOCK = 512


def _disk_bytes(st: os.stat_result) -> int:
    """What a file really costs: its allocated blocks, and at least one 4 KiB block even when it is empty
    (an empty tile still takes an inode and a directory entry; st_size would count it as 0)."""
    return max(st.st_blocks * _BLOCK, 4096)


def prune(root: Path, cap_bytes: int = CACHE_CAP_BYTES) -> int:
    """Least-recently-used pruning down to PRUNE_TARGET of BOTH caps (disk bytes, entries) once either is
    exceeded. Bytes and entries count every file (tiles and temp files) AND every directory below the root:
    a request for a valid filter key at an empty high-zoom tile leaves <key>/<z>/<x> behind. Temp files older
    than STALE_TMP_S (a killed writer) are removed. Afterwards directories left empty are removed bottom-up
    (never the root, never a version directory). Returns the number of files removed."""
    files, total, entries, removed, now = [], 0, 0, 0, time.time()
    for dirpath, dirs, names in os.walk(root):
        for name in dirs:
            try:
                st = (Path(dirpath) / name).lstat()
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                total += _disk_bytes(st)
                entries += 1
        for name in names:
            p = Path(dirpath) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if name.endswith(".tmp") and now - st.st_mtime > STALE_TMP_S:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
                continue
            total += _disk_bytes(st)
            entries += 1
            if name.endswith(".pbf"):
                files.append((st.st_mtime, _disk_bytes(st), p))
    over_cap = total > cap_bytes or entries > CACHE_MAX_ENTRIES
    if over_cap:
        byte_target, entry_target = int(cap_bytes * PRUNE_TARGET), int(CACHE_MAX_ENTRIES * PRUNE_TARGET)
        for _mtime, size, p in sorted(files, key=lambda f: f[0]):
            if total <= byte_target and entries <= entry_target:
                break
            try:
                p.unlink()
            except OSError:
                continue
            total -= size
            entries -= 1
            removed += 1
    if removed or over_cap:   # empty directories alone can push the entry count over its cap
        _remove_empty_dirs(root)
    return removed


def _remove_empty_dirs(root: Path) -> None:
    """Bottom-up rmdir of empty directories. The root and the version directories directly under it stay.
    OSError (not empty, or a writer just recreated it) is ignored: write_cached recreates what it needs and
    reports False when it loses that race."""
    for dirpath, _dirs, _names in os.walk(root, topdown=False):
        d = Path(dirpath)
        if d == root or d.parent == root or d.is_symlink():
            continue
        try:
            d.rmdir()
        except OSError:
            pass


_writes = 0
_prune_task: asyncio.Task | None = None


def note_write(root: Path) -> None:
    """Count API cache writes; every PRUNE_EVERY-th starts one background prune (never two at once)."""
    global _writes, _prune_task
    _writes += 1
    if _writes % PRUNE_EVERY or (_prune_task is not None and not _prune_task.done()):
        return
    _prune_task = asyncio.get_running_loop().create_task(asyncio.to_thread(prune, root))


class PruneCounter:
    """`note_write` for a cache with its own cap: counts the API's writes, every PRUNE_EVERY-th starts one
    background prune (never two at once). One instance per cache directory."""

    def __init__(self, cap) -> None:
        self._cap = cap                      # callable -> bytes, read at prune time (env can point it elsewhere)
        self._writes = 0
        self._task: asyncio.Task | None = None

    def note_write(self, root: Path) -> None:
        self._writes += 1
        if self._writes % PRUNE_EVERY or (self._task is not None and not self._task.done()):
            return
        self._task = asyncio.get_running_loop().create_task(asyncio.to_thread(prune, root, self._cap()))


TILE_MAX_ZOOM = 12         # the map's MVTLayer maxZoom; deck.gl overzooms above it, so the route refuses z > 12
PREBAKE_MAX_ZOOM = 6       # z0-6 = 5,461 tiles of the default view


class BakeVersionChanged(RuntimeError):
    """The live version moved while baking: what is on disk under the old version is simply abandoned."""


class BakeNoVersion(RuntimeError):
    """The version row is missing or malformed (at the start, or in a render's statement)."""


class BakeStopped(RuntimeError):
    """The bake gave up: past its total deadline (see BakeConsecutiveTimeouts for the other cause)."""


class BakeConsecutiveTimeouts(BakeStopped):
    """The bake gave up after PREBAKE_MAX_CONSECUTIVE_TIMEOUTS tile timeouts in a row."""


PREBAKE_MAX_CONSECUTIVE_TIMEOUTS = 20
PREBAKE_DEADLINE_S = 2700          # 45 min; env PLANKTON_PREBAKE_DEADLINE_S. The lock 4242001 is held meanwhile.


async def prebake(pool, root: Path, max_zoom: int | None = None) -> tuple[int, int]:
    """After a swap: drop every other version's directory, then bake the default view (all filters on)
    for z0..max_zoom into the cache of the CURRENT version; tiles already on disk are skipped. Files are
    written only under the version render() returned WITH the bytes. A tile that times out is skipped, never
    written. Raises BakeVersionChanged (version moved), BakeNoVersion (no/malformed version row), BakeStopped
    (PREBAKE_MAX_CONSECUTIVE_TIMEOUTS in a row, or past the deadline), OSError (cache not writable) or a DB
    error. Returns (tiles written, tiles skipped because they timed out)."""
    if max_zoom is None:
        max_zoom = int(os.getenv("PLANKTON_PREBAKE_MAX_ZOOM", str(PREBAKE_MAX_ZOOM)))
    max_zoom = min(max_zoom, TILE_MAX_ZOOM)
    deadline = float(os.getenv("PLANKTON_PREBAKE_DEADLINE_S", str(PREBAKE_DEADLINE_S)))
    started = time.monotonic()
    written = skipped = streak = 0
    async with pool.acquire() as conn:
        version = await current_version(conn)
        if version is None:
            raise BakeNoVersion("no plankton tile version to bake")
        drop_other_versions(root, version)
        for z in range(max_zoom + 1):
            for x in range(2 ** z):
                for y in range(2 ** z):
                    path = tile_path(root, version, DEFAULT_FILTER.key, z, x, y)
                    if path.exists():
                        continue
                    if time.monotonic() - started >= deadline:
                        raise BakeStopped("plankton tile pre-bake deadline")
                    try:
                        got, data = await render(conn, z, x, y, DEFAULT_FILTER)
                    except asyncpg.QueryCanceledError:
                        skipped += 1
                        streak += 1
                        if streak >= PREBAKE_MAX_CONSECUTIVE_TIMEOUTS:
                            raise BakeConsecutiveTimeouts("plankton tile pre-bake: consecutive timeouts")
                        continue
                    streak = 0
                    if got is None:
                        raise BakeNoVersion("plankton tile version missing during the bake")
                    if got != version:
                        raise BakeVersionChanged("plankton tile version changed during the bake")
                    if not write_cached(path, data):
                        raise OSError("plankton tile cache not writable")
                    written += 1
    await asyncio.to_thread(prune, root)
    return written, skipped
