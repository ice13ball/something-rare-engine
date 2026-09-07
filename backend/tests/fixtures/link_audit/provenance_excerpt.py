# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

_FIELDS: dict[str, FieldSource] = {
    "socat-co2": FieldSource(
        id="socat-co2", label="Surface CO₂ (SOCAT v2026)", sampler="socat_co2",
        vars=("fco2", "sst", "salinity", "density"), has_depth=False, has_decade=True,
        cap=20_000,
        prov=Provenance(
            source="SOCAT v2026 (decadal gridded)",
            source_url="https://www.socat.info/",
            license="CC-BY 4.0",
            citation="Bakker et al. 2026 (NCEI Accession 0315110, doi:10.25921/8dba-fr90)",
            note="Sparse / non-gap-filled; ~21% of cells have data.",
        ),
    ),
    "glodap-carbon": FieldSource(
        id="glodap-carbon", label="Interior carbon (GLODAP v2.2016b)", sampler="glodap_carbon",
        vars=("dic", "talk", "ph", "cant"), has_depth=True, has_decade=False,
        cap=20_000,
        prov=Provenance(
            source="GLODAP v2.2016b Mapped Climatology",
            source_url="https://www.glodap.info/",
            license="CC-BY 4.0",
            citation="Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
        ),
    ),
}
