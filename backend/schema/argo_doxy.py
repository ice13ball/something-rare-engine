# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Re-export: the BGC-Argo DOXY DDL lives in ingestion/argo_doxy_ddl.py (a leaf module, so the worker does not
import the API stack through schema/__init__). ensure_schema() still calls ensure_argo_doxy from here."""
from ingestion.argo_doxy_ddl import (EMPTY_DDL, PROFILES_DDL, SOURCE_DDL, UPSERT_EMPTY_SQL, UPSERT_SQL,  # noqa: F401
                                     ensure_argo_doxy)
