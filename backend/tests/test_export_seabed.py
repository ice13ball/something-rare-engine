# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Tests for the seabed-substrate FieldSource export registry entry (Task 12)."""
from backend.services.export_registry import _FIELDS, FieldSource


def test_seabed_export_registered_with_nc_license():
    fs = _FIELDS["seabed-substrate"]
    assert fs.prov.license == "CC-BY-NC 4.0"
    assert "Non-commercial" in fs.prov.note
    assert fs.has_depth is False and fs.has_decade is False


def test_seabed_export_is_field_source():
    assert isinstance(_FIELDS["seabed-substrate"], FieldSource)


def test_seabed_export_sampler_and_vars():
    fs = _FIELDS["seabed-substrate"]
    assert fs.sampler == "seabed_lithology"
    assert fs.vars == ("class",)
    assert fs.cap == 50_000


def test_seabed_export_provenance():
    prov = _FIELDS["seabed-substrate"].prov
    assert "earthbyte" in prov.source_url.lower()
    assert "Dutkiewicz" in prov.citation
    assert "doi:10.1130/G36883.1" in prov.citation
