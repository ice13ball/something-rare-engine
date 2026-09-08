# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Standalone AIS WebSocket ingestor.

Runs as its own systemd service (`ais-ingestor`) separate from the
FastAPI app — a `uvicorn --reload` cycle must never drop the stream.

Connects to AISStream.io, subscribes to bboxes derived from the `aois`
table, decodes PositionReport + ShipStaticData messages, and writes to
`ais_vessels` + `ais_positions` via the helpers in `ais_sync.py`.

Usage:
    python -m ais_ingestor

Environment:
    DATABASE_URL          Postgres DSN (inherited from FastAPI app)
    AISSTREAM_API_KEY     AISStream.io token (free, unlimited)
    AIS_AOI_BUFFER_KM     AOI buffer when seeding (default 25)
    AIS_BATCH_SIZE        Rows per DB flush (default 200)
    AIS_BATCH_INTERVAL_S  Max seconds between flushes (default 5)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Any

import asyncpg

import db
import log_redaction
from ais_sync import (
    ensure_ais_schema,
    seed_aois_from_existing_layers,
    get_aoi_bboxes,
    upsert_vessel,
    append_positions,
    run_partition_maintenance,
)

log = logging.getLogger("ais_ingestor")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Own process, own logging setup — so it needs its own install() call. See
# backend/log_redaction.py.
log_redaction.install()

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "")
BATCH_SIZE = int(os.getenv("AIS_BATCH_SIZE", "200"))
BATCH_INTERVAL_S = float(os.getenv("AIS_BATCH_INTERVAL_S", "5"))

# Message types we care about. AISStream sends other types (SafetyBroadcast,
# AidsToNavigationReport, ...) — we silently drop them.
POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}
STATIC_TYPES   = {"ShipStaticData", "StaticDataReport"}


class BatchBuffer:
    """Accumulates rows; flushes on size or interval."""

    def __init__(self) -> None:
        self.positions: list[dict[str, Any]] = []
        self.vessels: dict[int, dict[str, Any]] = {}
        self.last_flush = asyncio.get_event_loop().time()

    def should_flush(self) -> bool:
        return (
            len(self.positions) >= BATCH_SIZE
            or len(self.vessels) >= BATCH_SIZE
            or asyncio.get_event_loop().time() - self.last_flush >= BATCH_INTERVAL_S
        )

    async def flush(self) -> None:
        if not self.positions and not self.vessels:
            self.last_flush = asyncio.get_event_loop().time()
            return
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                for v in self.vessels.values():
                    await upsert_vessel(conn, v)
                if self.positions:
                    await append_positions(conn, self.positions)
        log.info("Flushed %d positions, %d vessel identities",
                 len(self.positions), len(self.vessels))
        self.positions.clear()
        self.vessels.clear()
        self.last_flush = asyncio.get_event_loop().time()


def _decode_message(msg: dict[str, Any], buf: BatchBuffer) -> None:
    """Route an AISStream frame into vessel/position batches."""
    msg_type = msg.get("MessageType", "")
    meta = msg.get("MetaData", {})
    mmsi = meta.get("MMSI") or msg.get("Message", {}).get(msg_type, {}).get("UserID")
    if not mmsi:
        return

    if msg_type in POSITION_TYPES:
        body = msg.get("Message", {}).get(msg_type, {})
        lat = body.get("Latitude")
        lon = body.get("Longitude")
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            return
        ts_str = meta.get("time_utc") or msg.get("time_utc")
        ts = _parse_ts(ts_str) if ts_str else datetime.now(timezone.utc)
        buf.positions.append({
            "mmsi": int(mmsi),
            "ts": ts,
            "lon": float(lon),
            "lat": float(lat),
            "sog_knots":   body.get("Sog"),
            "cog_deg":     body.get("Cog"),
            "heading_deg": body.get("TrueHeading") if body.get("TrueHeading", 511) != 511 else None,
            "nav_status":  body.get("NavigationalStatus"),
        })
        # Seed a minimal vessel row if we haven't seen this MMSI yet this batch
        if int(mmsi) not in buf.vessels:
            name = meta.get("ShipName")
            if name:
                buf.vessels[int(mmsi)] = {"mmsi": int(mmsi), "name": name.strip()}

    elif msg_type in STATIC_TYPES:
        body = msg.get("Message", {}).get(msg_type, {})
        # Dimensions: AISStream reports Dimension{A,B,C,D} offsets in meters
        dim = body.get("Dimension", {}) or {}
        length_m = (dim.get("A") or 0) + (dim.get("B") or 0) or None
        width_m  = (dim.get("C") or 0) + (dim.get("D") or 0) or None
        buf.vessels[int(mmsi)] = {
            "mmsi":        int(mmsi),
            "name":        (body.get("Name") or meta.get("ShipName") or "").strip() or None,
            "callsign":    (body.get("CallSign") or "").strip() or None,
            "imo":         body.get("ImoNumber") or None,
            "flag":        None,  # AISStream doesn't send flag; derive from MID later
            "ship_type":   body.get("Type"),
            "length_m":    length_m,
            "width_m":     width_m,
            "draught_m":   body.get("MaximumStaticDraught"),
            "destination": (body.get("Destination") or "").strip() or None,
            "eta":         _parse_eta(body.get("Eta")),
        }


def _parse_ts(s: str) -> datetime:
    # AISStream sends e.g. "2024-01-15 12:34:56.789 +0000 UTC"
    try:
        head = s.split(" +")[0].replace("T", " ")
        if "." in head:
            return datetime.strptime(head, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        return datetime.strptime(head, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _parse_eta(eta: dict[str, int] | None) -> datetime | None:
    if not eta:
        return None
    try:
        now = datetime.now(timezone.utc)
        return datetime(
            now.year, eta["Month"], eta["Day"], eta["Hour"], eta["Minute"],
            tzinfo=timezone.utc,
        )
    except (KeyError, ValueError):
        return None


async def run() -> None:
    try:
        import websockets
    except ImportError:
        raise SystemExit("websockets package not installed — add to requirements.txt")

    if not AISSTREAM_API_KEY:
        raise SystemExit("AISSTREAM_API_KEY not set")

    dsn = os.environ["DATABASE_URL"]
    db.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    await ensure_ais_schema()
    await seed_aois_from_existing_layers()
    await run_partition_maintenance()   # ensure current/next weekly partition exists before inserts

    bboxes = await get_aoi_bboxes()
    if not bboxes:
        log.warning("No AOIs — ingestor has nothing to subscribe to. Seed mining_contracts first.")
        return

    # AISStream bbox format: [[min_lat, min_lon], [max_lat, max_lon]]
    subscription = {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": [
            [[min_lat, min_lon], [max_lat, max_lon]]
            for (min_lon, min_lat, max_lon, max_lat) in bboxes
        ],
        "FilterMessageTypes": list(POSITION_TYPES | STATIC_TYPES),
    }

    buf = BatchBuffer()
    stop = asyncio.Event()

    def _shutdown(*_: object) -> None:
        log.info("Shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    backoff = 1.0
    while not stop.is_set():
        try:
            log.info("Connecting to %s (%d bboxes)", AISSTREAM_URL, len(bboxes))
            async with websockets.connect(AISSTREAM_URL, ping_interval=30) as ws:
                await ws.send(json.dumps(subscription))
                backoff = 1.0  # reset on successful connect
                flush_task = asyncio.create_task(_periodic_flush(buf, stop))
                try:
                    async for raw in ws:
                        if stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        _decode_message(msg, buf)
                        if buf.should_flush():
                            await buf.flush()
                finally:
                    flush_task.cancel()
                    await buf.flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("WebSocket loop error; reconnecting in %.1fs", backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60.0)  # exponential, cap 1 min

    await db.pool.close()
    log.info("Ingestor stopped cleanly")


async def _periodic_flush(buf: BatchBuffer, stop: asyncio.Event) -> None:
    """Guarantees a flush at least every BATCH_INTERVAL_S even on a quiet stream."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=BATCH_INTERVAL_S)
        except asyncio.TimeoutError:
            if buf.should_flush():
                try:
                    await buf.flush()
                except Exception:
                    log.exception("Periodic flush failed")


if __name__ == "__main__":
    asyncio.run(run())
