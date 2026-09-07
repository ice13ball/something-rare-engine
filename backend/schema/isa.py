# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — isa domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations
import logging

# Restored 2026-08-21. The split of schema.py into this package left `log`
# behind in the original module while nine `log.debug(...)` calls came across —
# every one of them inside an `except` clause. A tolerated DDL failure would
# therefore raise NameError from its own handler and take the boot down with it.
# The DDL snapshot test could not see this: it compares statements, not error paths.
log = logging.getLogger(__name__)

# All ISA contractors keyed by ContractID — covers both active (layer 32) and relinquished (layer 34)
ISA_CONTRACT_SEED = [
    # Active exploration contracts
    ("BGRPMN1",      "Federal Institute for Geosciences and Natural Resources (BGR), Germany"),
    ("BGRPMS1",      "Federal Institute for Geosciences and Natural Resources (BGR), Germany"),
    ("BMJPMN1",      "Beijing Minmetals Joint Venture, China"),
    ("BPHDCPMN1",    "Beijing Pioneer Hi-Tech Development Corporation (BPHDC), China"),
    ("BrazilCRFC1",  "Federal Government of Brazil"),
    ("CIICPMN1",     "China International Seabed Area Investment and Development Corp. (CIICAD)"),
    ("CMMPMN1",      "China Minmetals Corporation"),
    ("COMRACRFC1",   "China Ocean Mineral Resources R&D Association (COMRA)"),
    ("COMRAPMN1",    "China Ocean Mineral Resources R&D Association (COMRA)"),
    ("COMRAPMS1",    "China Ocean Mineral Resources R&D Association (COMRA)"),
    ("DORDPMN1",     "Deep Ocean Resources Development Co., Ltd. (DORD), Japan"),
    ("GSRPMN1",      "Global Sea Mineral Resources NV (GSR), Belgium"),
    ("IFREMERPMN1",  "French Research Institute for Exploitation of the Sea (IFREMER)"),
    ("IFREMERPMS1",  "French Research Institute for Exploitation of the Sea (IFREMER)"),
    ("IOMPMN1",      "Interoceanmetal Joint Organization (IOM)"),
    ("IndiaPMN1",    "Government of India / National Institute of Ocean Technology (NIOT)"),
    ("IndiaPMS1",    "Government of India / National Institute of Ocean Technology (NIOT)"),
    ("JOGMECCRFC1",  "Japan Oil, Gas and Metals National Corporation (JOGMEC)"),
    ("KOREACRFC1",   "Korea Institute of Ocean Science and Technology (KIOST)"),
    ("KOREAPMN1",    "Korea Institute of Ocean Science and Technology (KIOST)"),
    ("KOREAPMS1",    "Korea Institute of Ocean Science and Technology (KIOST)"),
    ("MARAWAPMN1",   "Marawa Research and Exploration Ltd., Kiribati"),
    ("NORIPMN1",     "Nauru Ocean Resources Inc. (NORI) / The Metals Company"),
    ("OMSPMN1",      "Ocean Mineral Singapore Pte. Ltd."),
    ("POLPMS1",      "KGHM Polska Miedź S.A. / Government of Poland"),
    ("RUSFEDPMS1",   "Russian Federation"),
    ("RUSMNCRFC1",   "Russian Federation (Ministry of Natural Resources)"),
    ("RUSMNRCRFC1",  "Russian Federation (Ministry of Natural Resources)"),
    ("TOMLPMN1",     "Tonga Offshore Mining Ltd. (TOML)"),
    ("UKSRLPMN1",    "UK Seabed Resources Ltd."),
    ("UKSRLPMN2",    "UK Seabed Resources Ltd."),
    ("YUZHPMN1",     "Yuzhmorgeologiya, Russian Federation"),
]


async def ensure_mining_contracts_columns(conn) -> None:
    """mining_contracts enrichment ALTER columns."""

    # Add boundary-enrichment columns to mining_contracts (safe to re-run).
    # These ALTER TABLEs need ACCESS EXCLUSIVE lock — if blocked by long queries,
    # lock_timeout will raise an error. We catch and log so startup can continue;
    # the columns will be added on the next restart when locks are free.
    for col_sql in [
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS jurisdiction_text TEXT DEFAULT 'International Waters / ISA'",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearest_eez_country TEXT",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearest_eez_dist_km DOUBLE PRECISION",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearest_unesco_site TEXT",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearest_unesco_dist_km DOUBLE PRECISION",
        # Cached SEO counts — populated by isa.enrich_claim_boundaries() weekly.
        # Eliminates the 5 expensive spatial subqueries that previously ran on
        # every /v1/seo/concession/{isa_id} request (each one a 5M-row
        # ST_DWithin against biodiversity_hotspots).
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS vent_conflicts INTEGER",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearby_species INTEGER",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearby_argo_floats INTEGER",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearby_onc_stations INTEGER",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS nearby_oceansites_moorings INTEGER",
        "ALTER TABLE mining_contracts ADD COLUMN IF NOT EXISTS seo_enriched_at TIMESTAMPTZ",
    ]:
        try:
            await conn.execute(col_sql)
        except Exception as e:
            log.warning("DDL skipped (lock timeout?): %s — %s", col_sql[:60], e)


async def ensure_isa_seed(conn) -> None:
    """isa_contract_lookup seed upsert (ISA_CONTRACT_SEED)."""

    # Upsert contractor lookup (new entries added, names updated if changed)
    await conn.executemany(
        """INSERT INTO isa_contract_lookup (contract_id, contractor_name)
           VALUES ($1, $2)
           ON CONFLICT (contract_id) DO UPDATE SET contractor_name = EXCLUDED.contractor_name""",
        ISA_CONTRACT_SEED,
    )


