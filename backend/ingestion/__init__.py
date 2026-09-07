# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Shared ingestion helpers."""

# How we identify ourselves to every upstream. One string, one place: a source
# that blocks us should be able to look us up and find a contact, and we should
# be able to prove what we sent when we ask them why.
# ⛔ Never make this imitate a browser. Being identifiable and circumventing a
# block are different acts, and only the first one is ours to take.
USER_AGENT = (
    "AbyssalClaims/1.0 (+https://something-rare.com; "
    "contact m.mazurowski@ai-wall.com)"
)
