# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The BFF must ask the origin for gzip regardless of what the client sent.

Production 2026-09-09, after the backend started compressing:

    curl --compressed  -> 200, 4,687,536 B
    curl (no header)   -> 500, 0 B

Cloud Run refuses a response over 32 MiB and enforces it on the bytes it
RECEIVES from the origin. /v1/map/argo/trails is 40.1 MB uncompressed and
4.69 MB gzipped, so one request header decided whether the endpoint worked.

The proxy forwarded the client's Accept-Encoding, so browsers — which always
advertise gzip — saw a healthy map while every script, curl and API consumer
got a 500. The origin hop belongs to us and must not depend on what a caller
happened to send.

⚠️ A shape test: the behaviour lives in a proxy callback that only runs against
a real upstream.

⛔ The proxy MOVED on 2026-09-18 — out of `frontend/server.js` and into
`frontend/seo/api-proxy.js`, so it could be unit-tested without importing
server.js (which calls app.listen() at import time). This guard went red on the
move, which is the correct outcome: a test that had silently kept passing
against the old file would have been watching an empty room. It now reads the
proxy wherever it lives, and fails if that file disappears rather than falling
back to "no gzip rule found here, so fine".
"""
import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
# In move order, newest first. The first one that exists is the one read.
PROXY_CANDIDATES = [FRONTEND / "seo" / "api-proxy.js", FRONTEND / "server.js"]


def _proxy_source() -> tuple[pathlib.Path, str]:
    for path in PROXY_CANDIDATES:
        if path.is_file():
            src = path.read_text(encoding="utf-8")
            if "createProxyMiddleware(" in src:
                return path, src
    raise AssertionError(
        "no file among "
        f"{[str(p) for p in PROXY_CANDIDATES]} contains the /api proxy. It has "
        "moved again — point this guard at its new home; deleting the guard "
        "would leave the 32 MiB Cloud Run limit unprotected.")


def _proxy_req_block() -> str:
    _, src = _proxy_source()
    start = src.index("proxyReq:")
    end = src.index("proxyRes:", start)
    return src[start:end]


def test_the_proxy_is_where_we_think_it_is():
    path, _ = _proxy_source()
    assert path.is_file(), f"not found: {path}"


def test_the_api_proxy_forces_gzip_from_the_origin():
    block = _proxy_req_block()
    assert re.search(r"setHeader\(\s*['\"]Accept-Encoding['\"]\s*,\s*['\"][^'\"]*gzip",
                     block, re.IGNORECASE), (
        "the /api proxy does not force Accept-Encoding: gzip upstream. Without "
        "it a caller that omits the header makes the origin send 40 MB to Cloud "
        "Run, which refuses anything over 32 MiB — and because browsers always "
        "send it, the failure is invisible from a browser.\n\n" + block
    )


def test_the_api_key_is_still_set():
    """The header the proxy already had — so this test fails loudly if the
    block is ever restructured in a way that drops it."""
    assert "X-API-Key" in _proxy_req_block()
