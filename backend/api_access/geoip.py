# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import ipaddress
import logging
import os

log = logging.getLogger(__name__)


class GeoIP:
    """Resolve an IP to (country_iso, asn) via injected MaxMind readers.

    Readers are the geoip2.database.Reader objects (or test doubles). Either may
    be None (DB not configured) — the corresponding field then resolves to None.
    Every failure path returns None rather than raising; this runs in the log
    writer and must never break logging.
    """

    def __init__(self, country_reader=None, asn_reader=None):
        self._country = country_reader
        self._asn = asn_reader

    def lookup(self, ip: str | None) -> tuple[str | None, int | None]:
        if not ip:
            return (None, None)
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return (None, None)
        country = None
        asn = None
        if self._country is not None:
            try:
                country = self._country.country(ip).country.iso_code
            except Exception:
                country = None
        if self._asn is not None:
            try:
                asn = self._asn.asn(ip).autonomous_system_number
            except Exception:
                asn = None
        return (country, asn)


def load_geoip() -> GeoIP:
    """Build a GeoIP from GEOIP_COUNTRY_DB / GEOIP_ASN_DB env paths.

    Returns a GeoIP with None readers (→ NULL country/asn) if geoip2 isn't
    installed or the files are absent — Phase 2 ships and logs without GeoIP,
    and country/asn populate once the .mmdb files are installed on the host.
    """
    country_reader = None
    asn_reader = None
    cpath = os.getenv("GEOIP_COUNTRY_DB")
    apath = os.getenv("GEOIP_ASN_DB")
    try:
        import geoip2.database as gdb
        if cpath and os.path.exists(cpath):
            country_reader = gdb.Reader(cpath)
        if apath and os.path.exists(apath):
            asn_reader = gdb.Reader(apath)
    except Exception as e:  # geoip2 missing or unreadable DB
        log.warning("GeoIP readers unavailable: %s", e)
    if country_reader is None and asn_reader is None:
        log.warning(
            "GeoIP not configured (set GEOIP_COUNTRY_DB / GEOIP_ASN_DB to GeoLite2 "
            ".mmdb paths); request_log country/asn will be NULL"
        )
    return GeoIP(country_reader, asn_reader)
