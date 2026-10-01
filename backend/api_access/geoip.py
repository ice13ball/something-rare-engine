# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import ipaddress
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)


RELOAD_CHECK_INTERVAL_S = 300.0


def _open_reader(path: str):
    import geoip2.database as gdb
    return gdb.Reader(path)


def _signature(path: str) -> tuple[int, int]:
    """(inode, mtime_ns). geoipupdate renames a fresh file into place, so a new
    inode is the reliable change signal; mtime alone can be preserved."""
    st = os.stat(path)
    return (st.st_ino, st.st_mtime_ns)


class _Slot:
    """One mmdb: the reader in use, its path, and the file signature it was opened from."""

    def __init__(self, path: str | None, reader=None, sig: tuple[int, int] | None = None):
        self.path = path
        self.reader = reader
        self.sig = sig


class GeoIP:
    """Resolve an IP to (country_iso, asn) via injected MaxMind readers.

    Readers are the geoip2.database.Reader objects (or test doubles). Either may
    be None (DB not configured) — the corresponding field then resolves to None.
    Every failure path returns None rather than raising; this runs in the log
    writer and must never break logging.

    When paths are given, the files are re-checked at most every
    RELOAD_CHECK_INTERVAL_S (monotonic) and a changed or newly appeared file is
    opened and swapped in; a file that fails to open leaves the old reader in
    place. Old readers are dropped, never closed, as a lookup may still hold one.
    """

    def __init__(self, country_reader=None, asn_reader=None, *, country_path=None,
                 asn_path=None, country_sig=None, asn_sig=None,
                 check_interval=RELOAD_CHECK_INTERVAL_S, clock=time.monotonic):
        self._country_slot = _Slot(country_path, country_reader, country_sig)
        self._asn_slot = _Slot(asn_path, asn_reader, asn_sig)
        self._interval = check_interval
        self._clock = clock
        self._next_check = clock() + check_interval
        self._warned: set[tuple[str, str]] = set()

    @property
    def _country(self):
        return self._country_slot.reader

    @property
    def _asn(self):
        return self._asn_slot.reader

    def status(self) -> dict:
        def mtime(slot):
            if slot.reader is None or slot.sig is None:
                return None
            return datetime.fromtimestamp(slot.sig[1] / 1e9, tz=timezone.utc).isoformat()
        return {
            "country": self._country is not None,
            "asn": self._asn is not None,
            "country_db_mtime": mtime(self._country_slot),
            "asn_db_mtime": mtime(self._asn_slot),
        }

    def _warn_once(self, what: str, exc: Exception) -> None:
        key = (what, type(exc).__name__)
        if key not in self._warned:
            self._warned.add(key)
            log.warning("GeoIP %s failed (%s: %s); further failures of this kind not logged",
                        what, type(exc).__name__, exc)

    def _maybe_reload(self) -> None:
        try:
            now = self._clock()
            if now < self._next_check:
                return
            self._next_check = now + self._interval
            for name, slot in (("country", self._country_slot), ("asn", self._asn_slot)):
                if not slot.path:
                    continue
                try:
                    sig = _signature(slot.path)
                    if sig == slot.sig:
                        continue
                    slot.reader, slot.sig = _open_reader(slot.path), sig
                    log.info("GeoIP %s database (re)loaded from %s", name, slot.path)
                except Exception as e:  # missing/half-written file: keep the old reader
                    self._warn_once(f"{name} reload", e)
        except Exception as e:
            self._warn_once("reload check", e)

    def lookup(self, ip: str | None) -> tuple[str | None, int | None]:
        self._maybe_reload()
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
    A file that appears later is picked up by GeoIP's periodic re-check.
    """
    global _current
    cpath = os.getenv("GEOIP_COUNTRY_DB") or None
    apath = os.getenv("GEOIP_ASN_DB") or None
    readers, sigs = {}, {}
    for key, path in (("country", cpath), ("asn", apath)):
        readers[key] = sigs[key] = None
        if not path or not os.path.exists(path):
            continue
        try:
            sigs[key] = _signature(path)
            readers[key] = _open_reader(path)
        except Exception as e:  # geoip2 missing or unreadable DB
            sigs[key] = None
            log.warning("GeoIP reader unavailable for %s: %s", path, e)
    if readers["country"] is None and readers["asn"] is None:
        log.warning(
            "GeoIP not configured (set GEOIP_COUNTRY_DB / GEOIP_ASN_DB to GeoLite2 "
            ".mmdb paths); request_log country/asn will be NULL"
        )
    _current = GeoIP(readers["country"], readers["asn"], country_path=cpath, asn_path=apath,
                     country_sig=sigs["country"], asn_sig=sigs["asn"])
    return _current


_current: GeoIP | None = None


def geoip_status() -> dict:
    """State of the GeoIP instance loaded in this process (for the admin overview)."""
    if _current is None:
        return {"country": False, "asn": False, "country_db_mtime": None, "asn_db_mtime": None}
    return _current.status()
