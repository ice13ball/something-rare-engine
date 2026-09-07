# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from routers.feedback import FeedbackBody, KIND_EMOJI


def test_api_key_kind_is_valid():
    b = FeedbackBody(kind="api_key", message="please send a key", dwell_ms=5000)
    assert b.kind == "api_key"


def test_api_key_emoji_present():
    assert KIND_EMOJI["api_key"] == "🔑"
