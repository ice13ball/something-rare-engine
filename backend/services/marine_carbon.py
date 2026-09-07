# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Unified Marine Carbon readout — metadata + pure grouping helper.

Combines the four grid-aligned ocean field sources (GLODAP interior carbon,
SOCAT surface CO₂, ISAS oxygen, WOA physical/nutrients) into one co-located
per-location readout. This module holds ONLY metadata + a pure grouping
function; the actual sampling lives in the FastAPI endpoints (which import the
heavy NetCDF-backed service samplers). Keeping sampling out of here lets the
grouping logic be unit-tested without the data holdings installed.

HONESTY: this is a co-located readout, never a fused metric. Each value keeps
its own source, units and (in the panel) depth/time label.
"""
from __future__ import annotations

# key -> display metadata. `source` is the contributing dataset (for the panel
# section + citations). vmin/vmax drive the hex colour ramp for COLOR_VARS.
# Group order here is the section order in the click panel.
MARINE_CARBON_VARS: dict[str, dict] = {
    # Surface CO₂ (SOCAT) — sampled at the surface, latest decade
    "co2_fco2": {"group": "Surface CO₂ (SOCAT)", "label": "Surface fCO₂",      "units": "µatm",    "vmin": 280,  "vmax": 450,  "source": "socat"},
    "co2_sst":  {"group": "Surface CO₂ (SOCAT)", "label": "Sea-surface temp",  "units": "°C",      "vmin": -2,   "vmax": 32,   "source": "socat"},
    "co2_sal":  {"group": "Surface CO₂ (SOCAT)", "label": "Sea-surface sal",   "units": "PSU",     "vmin": 30,   "vmax": 38,   "source": "socat"},
    # Interior carbon (GLODAP) — sampled at the selected depth
    "dic":  {"group": "Interior carbon (GLODAP)", "label": "Dissolved Inorganic Carbon", "units": "µmol/kg", "vmin": 1900, "vmax": 2400, "source": "glodap"},
    "talk": {"group": "Interior carbon (GLODAP)", "label": "Total Alkalinity",           "units": "µmol/kg", "vmin": 2200, "vmax": 2500, "source": "glodap"},
    "ph":   {"group": "Interior carbon (GLODAP)", "label": "pH (in situ)",               "units": "",        "vmin": 7.6,  "vmax": 8.2,  "source": "glodap"},
    "cant": {"group": "Interior carbon (GLODAP)", "label": "Anthropogenic carbon",       "units": "µmol/kg", "vmin": 0,    "vmax": 70,   "source": "glodap"},
    # Oxygen (ISAS recent + Δ vs WOA baseline) — selected depth
    "o2_recent":  {"group": "Oxygen", "label": "Dissolved O₂ (ISAS 2014–2018)", "units": "µmol/kg", "vmin": 0,   "vmax": 350, "source": "isas"},
    "deox_delta": {"group": "Oxygen", "label": "Deoxygenation Δ vs WOA",        "units": "µmol/kg", "vmin": -50, "vmax": 50,  "source": "isas"},
    # Physical & nutrients (WOA) — selected depth, annual
    "woa_temp":      {"group": "Physical & nutrients (WOA)", "label": "Temperature",  "units": "°C",      "vmin": -2, "vmax": 32,  "source": "woa"},
    "woa_sal":       {"group": "Physical & nutrients (WOA)", "label": "Salinity",     "units": "PSU",     "vmin": 30, "vmax": 38,  "source": "woa"},
    "woa_o2":        {"group": "Physical & nutrients (WOA)", "label": "Dissolved O₂", "units": "µmol/kg", "vmin": 0,  "vmax": 350, "source": "woa"},
    "woa_nitrate":   {"group": "Physical & nutrients (WOA)", "label": "Nitrate",      "units": "µmol/kg", "vmin": 0,  "vmax": 45,  "source": "woa"},
    "woa_phosphate": {"group": "Physical & nutrients (WOA)", "label": "Phosphate",    "units": "µmol/kg", "vmin": 0,  "vmax": 3.5, "source": "woa"},
    "woa_silicate":  {"group": "Physical & nutrients (WOA)", "label": "Silicate",     "units": "µmol/kg", "vmin": 0,  "vmax": 180, "source": "woa"},
    # Acidification (ΩA/ΩC read directly from GLODAP; horizon & shift platform-derived)
    "omega_arag":         {"group": "Acidification (GLODAP + platform)", "label": "Aragonite saturation (ΩA)", "units": "Ω", "vmin": 0.5, "vmax": 4.0, "source": "glodap"},
    "omega_calc":         {"group": "Acidification (GLODAP + platform)", "label": "Calcite saturation (ΩC)",   "units": "Ω", "vmin": 0.8, "vmax": 6.0, "source": "glodap"},
    "arag_horizon":       {"group": "Acidification (GLODAP + platform)", "label": "Aragonite saturation-horizon depth", "units": "m", "vmin": 0, "vmax": 4000, "source": "platform", "depth_invariant": True},
    "arag_horizon_shift": {"group": "Acidification (GLODAP + platform)", "label": "Horizon shift since preindustrial", "units": "m", "vmin": 0, "vmax": 400, "source": "platform", "depth_invariant": True},
    # Seafloor
    "seafloor_depth": {"group": "Seafloor", "label": "Seafloor depth (GEBCO)", "units": "m", "vmin": 0, "vmax": 6000, "source": "gebco", "depth_invariant": True},
    "substrate":      {"group": "Seafloor", "label": "Seabed substrate", "units": "", "source": "dutkiewicz", "categorical": True, "depth_invariant": True},
}

# Curated short list that can colour the hex grid (keeps the selector limited).
COLOR_VARS: list[str] = ["co2_fco2", "dic", "o2_recent", "woa_temp", "omega_arag"]


def group_point(sampled: dict[str, float | None],
                labels: dict[str, str] | None = None) -> list[dict]:
    """Group sampled values by section, preserving MARINE_CARBON_VARS order.

    `sampled` maps variable key -> value (or None). `labels` optionally maps a key to a
    display STRING (for categorical variables like substrate, whose numeric code is not a
    magnitude). A variable with a label carries `value_label`; the raw `value` is still
    included for provenance. Never fuse across variables — this only groups.
    """
    labels = labels or {}
    out: list[dict] = []
    index: dict[str, dict] = {}
    for key, cfg in MARINE_CARBON_VARS.items():
        grp = index.get(cfg["group"])
        if grp is None:
            grp = {"group": cfg["group"], "variables": []}
            index[cfg["group"]] = grp
            out.append(grp)
        grp["variables"].append({
            "key": key, "label": cfg["label"], "units": cfg["units"],
            "value": sampled.get(key),
            "value_label": labels.get(key),
            "depth_invariant": bool(cfg.get("depth_invariant")),
        })
    return out
