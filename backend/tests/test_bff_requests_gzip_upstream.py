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

⚠️ A shape test on server.js: there is no JS test harness in this repo, and the
behaviour lives in a proxy callback that only runs against a real upstream.
"""
import pathlib
import re

SERVER_JS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "server.js"


def _proxy_req_block() -> str:
    src = SERVER_JS.read_text(encoding="utf-8")
    start = src.index("app.use('/api', createProxyMiddleware(")
    end = src.index("proxyRes:", start)
    return src[start:end]


def test_server_js_is_where_we_think_it_is():
    assert SERVER_JS.is_file(), f"not found: {SERVER_JS}"


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
