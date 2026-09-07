# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio
from datetime import datetime, timezone

from backend.api_access.logging_mw import (
    LogPipe, build_record, client_ip, should_log,
)

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def test_should_log_only_api_prefixes():
    assert should_log("/v1/map/claims")
    assert should_log("/v2/spatial/tiles/x/1/2/3")
    assert not should_log("/admin/dashboard")
    assert not should_log("/healthz")
    assert not should_log("/report/v2/argo/123")


def test_client_ip_prefers_first_xff_hop():
    assert client_ip("203.0.113.9, 10.0.0.1", "10.0.0.1") == "203.0.113.9"
    assert client_ip(None, "198.51.100.7") == "198.51.100.7"
    assert client_ip("", "198.51.100.7") == "198.51.100.7"


def test_build_record_maps_fields():
    rec = build_record(
        method="GET", path="/v1/hydrophones/ABC/soundscape",
        route_template="/v1/hydrophones/{station_id}/soundscape",
        status=200, resp_bytes=1234,
        xff="203.0.113.9, 10.0.0.1", client_host="10.0.0.1",
        user_agent="python-requests/2.31", key_id=7, org_id=3, now=NOW,
    )
    assert rec.endpoint_label == "/v1/hydrophones/{station_id}/soundscape"
    assert rec.ip == "203.0.113.9"
    assert rec.status_code == 200 and rec.response_bytes == 1234
    assert rec.key_id == 7 and rec.org_id == 3
    assert rec.method == "GET" and rec.user_agent == "python-requests/2.31"
    assert rec.ts == NOW


def test_logpipe_drops_when_full_without_raising():
    pipe = LogPipe(maxsize=2)
    r = build_record(method="GET", path="/v1/x", route_template="/v1/x",
                     status=200, resp_bytes=0, xff=None, client_host=None,
                     user_agent=None, key_id=None, org_id=None, now=NOW)
    pipe.offer(r); pipe.offer(r); pipe.offer(r)  # third exceeds maxsize
    assert pipe.dropped == 1
    assert pipe.queue.qsize() == 2


def test_read_state_ids_reads_values_set_via_request_state():
    from starlette.requests import Request
    from backend.api_access.logging_mw import read_state_ids
    scope = {"type": "http", "headers": [], "method": "GET", "path": "/v1/x"}
    req = Request(scope)
    req.state.api_key_id = 7
    req.state.api_org_id = 3
    assert read_state_ids(req.scope) == (7, 3)


def test_read_state_ids_missing_state_is_none_pair():
    from backend.api_access.logging_mw import read_state_ids
    assert read_state_ids({"type": "http"}) == (None, None)
