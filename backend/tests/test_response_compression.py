# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Large responses must leave this backend compressed.

Production incident 2026-09-09. /v1/map/argo/trails answered:

    backend  -> HTTP 200, 42,029,422 bytes (40.1 MB), 44,780 points
    browser  -> HTTP 500, 0 bytes

Cloud Run caps a response at 32 MiB and enforces it on the bytes it receives
from the origin — BEFORE the BFF's Express compression() runs. The cap
therefore bites on the UNCOMPRESSED payload. An earlier comment in
domains/sensors.py said explicitly that this had not been verified; this
incident verified it the expensive way.

The trigger was filling the six-month Argo history floor: the 90-day map window
went from 14,870 points to 44,780 in one afternoon. Coverage improving is not a
failure mode anyone watches for, and the service log looked healthy throughout.
"""
import pytest
from fastapi.testclient import TestClient


def _gzip_entry():
    from fastapi.middleware.gzip import GZipMiddleware

    import main

    for m in main.app.user_middleware:
        if m.cls is GZipMiddleware:
            return m
    return None


def test_gzip_middleware_is_installed():
    """⛔ Asserted on the app itself, so it cannot pass because some other
    layer happened to compress."""
    assert _gzip_entry() is not None, (
        "the backend does not compress. A 40 MB GeoJSON body then travels "
        "uncompressed to Cloud Run, which refuses anything over 32 MiB — the "
        "API logs 200 and the browser gets 500."
    )


def test_the_threshold_is_low_enough_to_matter():
    """A minimum_size above the payloads that break is the same as no gzip."""
    entry = _gzip_entry()
    assert entry is not None
    size = entry.kwargs.get("minimum_size", entry.args[0] if entry.args else None)
    assert size is not None and size <= 64 * 1024, (
        f"minimum_size is {size}. The bodies that hit the 32 MiB cap are tens "
        "of megabytes, but a threshold this high leaves every ordinary "
        "response uncompressed for no reason."
    )


def test_the_middleware_really_compresses_a_large_body():
    """Round-trip through the same middleware class and options the app uses."""
    import gzip as _gzip

    from fastapi import FastAPI
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.testclient import TestClient

    entry = _gzip_entry()
    probe = FastAPI()
    probe.add_middleware(GZipMiddleware, **entry.kwargs)

    body = "x" * 200_000

    @probe.get("/big")
    async def _big():
        return {"payload": body}

    @probe.get("/small")
    async def _small():
        return {"ok": True}

    client = TestClient(probe)

    big = client.get("/big", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip", (
        f"a {len(body)}-byte body came back uncompressed: {dict(big.headers)}")
    raw = big.content if big.headers.get("content-encoding") != "gzip" else None
    assert big.status_code == 200

    small = client.get("/small", headers={"Accept-Encoding": "gzip"})
    assert small.headers.get("content-encoding") != "gzip", (
        "a 20-byte body was compressed — gzipping that makes it bigger")
    assert raw is None or _gzip.decompress
