# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""How often each source's UPSTREAM publishes — and what we do about it.

Written 2026-09-03 after an audit found 42 of 106 sources more than 7 days
stale, the worst at 144 days. Reconstructing "how often does this provider
publish?" took three parallel investigations because the answer lived nowhere.
It lives here now.

⛔ `Static` and `Days(9999)` are NOT interchangeable. `Static` says the upstream
is a finished publication and stopping is correct. `Days` says it moves and we
have chosen a refresh window. Only the second is a defect when it stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Static:
    """Upstream is a one-off publication. Never refresh; that is correct."""
    reason: str


@dataclass(frozen=True)
class Days:
    """Refresh once the local copy is older than `n` days.

    `n` is a POLICY, not a fact about the provider: it starts from the upstream
    cadence and may be set longer where a refresh is expensive. The provider's
    actual cadence belongs in `reason`, so the two never get confused.
    """
    n: int
    reason: str


@dataclass(frozen=True)
class Blocked:
    """Deliberately withheld — licence, upstream block, pending permission.

    NOT a failure. Never attempt the fetch, and never let this log like one.
    """
    reason: str


CADENCE: dict[str, Static | Days | Blocked] = {
    "mining_footprints": Static("Maus et al. 2022, PANGAEA — one-off publication"),
    "landslides":        Static("NASA COOLR — irregular/one-off"),
    "dams":              Static("Global Dam Watch — irregular/one-off"),
    "water_risk":        Static("WRI Aqueduct — irregular/one-off"),
    "tailings":          Static("Hudson-Edwards et al. 2023 — one-off"),
    # ⛔ NOT Static, however much the name reads like a post-processing step.
    # `_enrich_tailings_from_grid` GETs tailing.grida.no/api/tailings_all on
    # every run and INSERTS the facilities we do not already hold. It derives
    # nothing locally. It carried Static("local derivation over rows we already
    # hold") until 2026-09-03, which froze a live upstream permanently behind a
    # reason that read as correct — the exact failure this registry exists to end.
    "tailings_enrich":   Days(90, "GRID-Arendal Global Tailings Portal "
                                  "(tailing.grida.no/api/tailings_all) takes rolling "
                                  "corporate disclosures; quarterly matches how often "
                                  "the portal materially changes, and the <5 km spatial "
                                  "match against tailings_dams is expensive"),
    "kbas":              Blocked("BirdLife's KBA terms forbid redistribution through an "
                                 "interactive web map granting download access, plus a "
                                 "separate no-commercial-use clause. Withdrawn 2026-09-03. "
                                 "Refreshing a layer we no longer serve buys nothing and "
                                 "keeps a copy current for no purpose"),
    "wdpa":              Blocked("interactive-web-map redistribution needs prior written "
                                 "permission from UNEP-WCMC (protectedareas@unep-wcmc.org); "
                                 "requested 2026-09-03"),
    "memento":           Days(90,  "continuous upstream; quarterly is enough for a methane "
                                   "synthesis layer"),
    "sio-bic":           Blocked("sioapps.ucsd.edu returns 403 to an identified client. "
                                 "Measured 2026-09-03: 403 both WITH our User-Agent and "
                                 "without it, so this is not a bare-agent WAF rejection — "
                                 "it is a deliberate block or a changed endpoint. Upstream "
                                 "cadence is ~weekly; retest and un-Block once SIO-BIC "
                                 "replies. Do not work around it."),
    "ncei_icoads_files": Days(7,   "NCEI publishes daily; weekly is enough and the fetch "
                                   "is heavy"),
}


def should_sync(source: str, last_synced_at: datetime | None,
                now: datetime, *, force: bool = False) -> tuple[bool, str]:
    """Return (run_it, human-readable reason).

    An UNREGISTERED source runs. Forgetting to add an entry must cost an extra
    sync, never silent staleness — that failure mode is the one this file exists
    to end.

    `force` is the admin Force Sync button and the staleness monitor's remedy.
    It bypasses the CADENCE WINDOW — that is a policy about how often we bother
    an upstream, and a person asking for it once overrides it.

    ⛔ It does NOT bypass `Blocked`. That is not a schedule, it is a licence or
    an upstream refusal, and a click on an admin button must not be able to
    fetch data we have no right to hold. The Blocked branch therefore comes
    FIRST and force is checked after it — the order is the rule. If a Blocked
    source becomes fetchable, the fix is to change its CADENCE entry, in a
    commit someone can read, not to press a button.
    """
    rule = CADENCE.get(source)
    if rule is None:
        return True, f"{source}: unregistered in CADENCE — running"
    if isinstance(rule, Blocked):
        # ⛔ Before the `force` check, deliberately. Do not reorder.
        return False, f"{source}: BLOCKED — {rule.reason}"
    if force:
        return True, f"{source}: forced by hand — cadence gate bypassed"
    if isinstance(rule, Static):
        return False, f"{source}: static source — {rule.reason}"
    if last_synced_at is None:
        return True, f"{source}: never synced — running"
    age = now - last_synced_at
    if age >= timedelta(days=rule.n):
        return True, f"{source}: {age.days}d old, window {rule.n}d — running"
    return False, f"{source}: {age.days}d old, window {rule.n}d — fresh"
