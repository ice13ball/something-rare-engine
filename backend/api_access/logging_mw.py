# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

API_PREFIXES = ("/v1", "/v2")


@dataclass
class RequestLogRecord:
    ts: datetime
    key_id: int | None
    org_id: int | None
    method: str
    path: str
    endpoint_label: str
    status_code: int
    response_bytes: int
    ip: str | None
    user_agent: str | None


def read_state_ids(scope) -> tuple[int | None, int | None]:
    """Read (api_key_id, api_org_id) from an ASGI scope's request state.

    Phase 1's get_api_key sets request.state.api_key_id/api_org_id; on current
    Starlette that lands in scope['state'] as a plain dict, but we read both a
    dict and an attribute-style State object so a Starlette change can't silently
    null out key attribution.
    """
    state = scope.get("state")
    if state is None:
        return (None, None)
    if isinstance(state, dict):
        return (state.get("api_key_id"), state.get("api_org_id"))
    return (getattr(state, "api_key_id", None), getattr(state, "api_org_id", None))


def should_log(path: str) -> bool:
    return path.startswith(API_PREFIXES)


def client_ip(xff: str | None, client_host: str | None) -> str | None:
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return client_host


def build_record(*, method: str, path: str, route_template: str | None,
                 status: int, resp_bytes: int, xff: str | None,
                 client_host: str | None, user_agent: str | None,
                 key_id: int | None, org_id: int | None,
                 now: datetime) -> RequestLogRecord:
    return RequestLogRecord(
        ts=now,
        key_id=key_id,
        org_id=org_id,
        method=method,
        path=path,
        endpoint_label=route_template or path,
        status_code=status,
        response_bytes=resp_bytes,
        ip=client_ip(xff, client_host),
        user_agent=user_agent,
    )


class LogPipe:
    """Bounded queue with a drop counter. offer() never blocks or raises."""

    def __init__(self, maxsize: int = 10000):
        self.queue: asyncio.Queue[RequestLogRecord] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, rec: RequestLogRecord) -> None:
        try:
            self.queue.put_nowait(rec)
        except asyncio.QueueFull:
            self.dropped += 1


class RequestLogMiddleware:
    """Pure ASGI middleware: capture status + content-length from the response,
    read the resolved key/org id from scope['state'] (set by get_api_key), and
    offer a log record. Never blocks the request; all failures are swallowed.
    """

    def __init__(self, app, pipe: LogPipe):
        self.app = app
        self.pipe = pipe

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        captured = {"status": 0, "bytes": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                for k, v in message.get("headers", []):
                    if k == b"content-length":
                        try:
                            captured["bytes"] = int(v)
                        except (TypeError, ValueError):
                            pass
            await send(message)

        await self.app(scope, receive, send_wrapper)

        try:
            path = scope.get("path", "")
            if not should_log(path):
                return
            headers = {k.decode("latin-1"): v.decode("latin-1")
                       for k, v in scope.get("headers", [])}
            key_id, org_id = read_state_ids(scope)
            route = scope.get("route")
            route_template = getattr(route, "path", None)
            client = scope.get("client")
            rec = build_record(
                method=scope.get("method", ""),
                path=path,
                route_template=route_template,
                status=captured["status"],
                resp_bytes=captured["bytes"],
                xff=headers.get("x-forwarded-for"),
                client_host=client[0] if client else None,
                user_agent=headers.get("user-agent"),
                key_id=key_id,
                org_id=org_id,
                now=datetime.now(timezone.utc),
            )
            self.pipe.offer(rec)
        except Exception:
            log.exception("request logging failed (non-fatal)")


_INSERT_SQL = """
INSERT INTO api_access.request_log
    (key_id, org_id, ts, method, path, endpoint_label, status_code,
     response_bytes, ip, country, asn, user_agent)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::inet,$10,$11,$12)
"""


async def _flush(pool, geoip, batch: list[RequestLogRecord]) -> None:
    args = []
    key_ids = set()
    for r in batch:
        country, asn = geoip.lookup(r.ip)
        args.append((r.key_id, r.org_id, r.ts, r.method, r.path, r.endpoint_label,
                     r.status_code, r.response_bytes, r.ip, country, asn, r.user_agent))
        if r.key_id is not None:
            key_ids.add(r.key_id)
    async with pool.acquire() as conn:
        await conn.executemany(_INSERT_SQL, args)
        if key_ids:
            await conn.execute(
                "UPDATE api_access.api_keys SET last_used_at = NOW() WHERE id = ANY($1::bigint[])",
                list(key_ids),
            )


async def batch_writer(pool, pipe: LogPipe, geoip, *, batch_size: int = 200) -> None:
    """Drain the pipe and bulk-insert. Blocks on an empty queue, then drains up
    to batch_size already-queued records, so it batches under load and flushes
    promptly when idle. A failed flush drops that batch and continues — logging
    must never crash the writer.
    """
    while True:
        rec = await pipe.queue.get()
        batch = [rec]
        try:
            while len(batch) < batch_size:
                batch.append(pipe.queue.get_nowait())
        except asyncio.QueueEmpty:
            pass
        try:
            await _flush(pool, geoip, batch)
        except Exception:
            log.exception("request_log flush failed; dropped %d records", len(batch))
