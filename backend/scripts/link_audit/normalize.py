# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure URL normalization and classification.

Deliberately conservative: normalization makes a URL *fetchable*, it does not
make it *better*. Anything that would improve a URL (http -> https, collapsing
a doubled slash) is a fix the audit must be able to report, so it is left
untouched here.
"""
from __future__ import annotations

import re

# A DOI is "10." + registrant + "/" + suffix.
_BARE_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_TRAILING_PROSE = ".,;:!?"

_ENDPOINT_MARKERS = (
    "/query", "f=json", "featureserver", "mapserver",
    "/wfs", "/wms", "/rest/services", "/arcgis/",
)


def normalize_url(raw: str) -> str:
    """Return a fetchable absolute URL. Never upgrades the scheme."""
    s = raw.strip()
    # Strip prose punctuation that trails a URL embedded in a sentence.
    while s and s[-1] in _TRAILING_PROSE:
        s = s[:-1]
    if _BARE_DOI.match(s):
        return f"https://doi.org/{s}"
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith(("http://", "https://")):
        return s
    return f"https://{s}"


def classify_kind(url: str) -> str:
    low = url.lower()
    if "${" in url:
        return "deep-link"
    if "doi.org/" in low or _BARE_DOI.match(url):
        return "doi"
    if any(m in low for m in _ENDPOINT_MARKERS):
        return "endpoint"
    return "homepage"
