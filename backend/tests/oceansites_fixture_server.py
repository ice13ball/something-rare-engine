# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""An httpx transport that answers with bytes RECORDED from the real OceanSITES
OPeNDAP server (tests/fixtures/oceansites_gdac/opendap/, captured 2026-10-01).

The only invented thing here is the dispatch. A ``.ascii`` request is answered
only when its decoded constraint equals the one the production code sent to the
real server when the fixture was recorded; any other constraint is a 400, so a
change in what we ask for fails a test instead of being served a stale answer.
"""
import json
import re
import urllib.parse
from pathlib import Path

import httpx

FIX = Path(__file__).parent / "fixtures" / "oceansites_gdac" / "opendap"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
REAL_400_DUPLICATE = (FIX / "real_400_duplicate_reference.txt").read_bytes()

# catalogue-style path ("DATA/<dir>/<name>.nc") of every recorded file
FILES = {Path(v["file"]).stem: v["file"] for v in MANIFEST.values()}
T0N140W = "DATA/T0N140W/OS_T0N140W_DM092A-20140916_D_TEMP_10min.nc"
PAP2 = "DATA/PAP/OS_PAP-2_200406_D_CTD.nc"
IRMINGSEA = "DATA/LOCO-IRMINGSEA/OS_IRMINGSEA-1_200309_SBE37.nc"
MBARI = "DATA/MBARI/OS_MBARI-M0_20040604_R_TS.nc"
T8S165E = "DATA/T8S165E/OS_T8S165E_PM079A-19990313_D_SST_10min.nc"
PAPA = "DATA/PAPA/OS_PAPA_2017PA011_D_SALT-1hr.nc"
K276 = "DATA/K276/OS_K276_19830419_D_mooring27604rcm.nc"
BATS_BTL = "DATA/BATS/OS_BATS-1_BATSCR-0269-4_D_BTL.nc"


def read(stem: str, ext: str) -> bytes:
    return (FIX / f"{stem}.{ext}").read_bytes()


class FixtureServer:
    """MockTransport handler. ``requests`` keeps (method, path, decoded query)."""

    def __init__(self, *, status: int | None = None, reject_multi_variable: bool = False):
        self.status = status                          # answer EVERYTHING with this code
        self.reject_multi_variable = reject_multi_variable
        self.requests: list[tuple[str, str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = urllib.parse.unquote(request.url.path)
        query = urllib.parse.unquote(request.url.query.decode()) if request.url.query else ""
        self.requests.append((request.method, path, query))
        if self.status is not None:
            return httpx.Response(self.status, text="Service Unavailable")
        stem = Path(path).name.rsplit(".nc", 1)[0]
        if path.endswith(".dds") or path.endswith(".das"):
            f = FIX / f"{stem}{path[-4:]}"
            return httpx.Response(200, content=f.read_bytes()) if f.exists() else httpx.Response(404)
        if ".ascii" in path:
            entry = MANIFEST.get(stem, {})
            names = [re.split(r"[.\[]", i)[0] for i in query.split(",")] if query else []
            data_vars = [n for n in names if n.upper() != "TIME"
                         and not n.upper().startswith("DEPTH") and not n.endswith("_QC")]
            if self.reject_multi_variable and len(data_vars) > 1:
                return httpx.Response(400, content=REAL_400_DUPLICATE)
            if entry.get("ascii_query") == query:
                return httpx.Response(200, content=read(stem, "ascii"))
            if query in entry.get("ascii_extra", {}):
                return httpx.Response(200, content=(FIX / entry["ascii_extra"][query]).read_bytes())
            return httpx.Response(400, text="Error { message = \"constraint not recorded\"; };")
        return httpx.Response(404)
