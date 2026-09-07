# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.api_access.geoip import GeoIP


class _Country:
    def __init__(self, iso): self.country = type("C", (), {"iso_code": iso})()
class _Asn:
    def __init__(self, n): self.autonomous_system_number = n


class _CountryReader:
    def country(self, ip):
        if ip == "8.8.8.8": return _Country("US")
        raise ValueError("not found")
class _AsnReader:
    def asn(self, ip):
        if ip == "8.8.8.8": return _Asn(15169)
        raise ValueError("not found")


def test_lookup_resolves_country_and_asn():
    g = GeoIP(_CountryReader(), _AsnReader())
    assert g.lookup("8.8.8.8") == ("US", 15169)


def test_lookup_unknown_ip_returns_none_pair():
    g = GeoIP(_CountryReader(), _AsnReader())
    assert g.lookup("10.0.0.1") == (None, None)


def test_lookup_invalid_ip_string_is_safe():
    g = GeoIP(_CountryReader(), _AsnReader())
    assert g.lookup("not-an-ip") == (None, None)


def test_lookup_none_ip_is_safe():
    assert GeoIP(_CountryReader(), _AsnReader()).lookup(None) == (None, None)


def test_lookup_no_readers_returns_none_pair():
    g = GeoIP(None, None)
    assert g.lookup("8.8.8.8") == (None, None)
