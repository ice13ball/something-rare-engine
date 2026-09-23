// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LandLayerId } from "./landLayers";
import type { AssertComplete, AssertDisjoint } from "./layerRegistry";

/**
 * Every sea layer id, as a VALUE.
 *
 * ⛔ The type is derived from this array, not written beside it. When the two
 * were separate, `?layers=` validated against `LAYER_CONFIGS` — a different,
 * shorter list — and silently dropped six real layers from any URL that named
 * them. A union you can only read at compile time cannot be used to check a
 * string arriving at runtime, so something else gets used instead, and that
 * something else drifts.
 */
export const SEA_LAYER_IDS = [
  "contracts", "reserved-areas", "apeis", "biodiversity-hotspots", "seamounts",
  "relinquished-areas", "argo", "hydrothermal-vents", "eez", "protected-marine-sites",
  "noise-risk", "oceansites", "onc", "onc-instruments", "chess", "submarine-cables", "ports",
  "tectonic-plates", "vessel-events", "ais-live", "monitoring-density", "offshore-activities",
  "deepdata-stations", "hydrophone-stations", "bathymetry", "ocean-currents",
  "woa-climatology", "oxygen-deox", "wod-oxygen", "memento", "geotraces", "methane-seeps",
  "ocean-carbon", "ocean-co2-surface", "sios-svalbard", "marine-carbon", "arctic-catchments",
  "seabed-substrate", "arctic-sediment-carbon", "mosaic-sediment", "vme-suitability",
  "ocean-acidification", "coral-acid-exposure", "cumulative-human-impact",
  "marhys",
] as const;

export type SeaLayerId = (typeof SEA_LAYER_IDS)[number];

/**
 * Hydrothermal vent `status` — InterRidge's own Activity value, verbatim
 * (served since 2026-09-21). ⛔ Not platform vocabulary any more — the old
 * invented words "Active"/"Inactive"/"Extinct" don't exist in the source.
 * Single source of truth for the filter Set default and option count —
 * derive `.size < N`, never hardcode the option count.
 */
export const VENT_STATUS_VALUES = ["active, confirmed", "active, inferred", "inactive"] as const;

/**
 * The four overlap tests a concession can be filtered by. Closed vocabulary:
 * `claimPassesFilter` looks each selected value up in a fixed record, so a
 * value that is not one of these has no test to fail and is ignored rather
 * than treated as "failed" — see the comment at that call site.
 */
export const CLAIM_RISK_VALUES = ["biodiversity", "argo", "vents", "unesco"] as const;

/**
 * MARHYS sample types, as the source codes them.
 *
 * ⛔ `STD` (calibration standard) is deliberately ABSENT. The source ships ten
 * STD samples and not one of them carries a coordinate, so an option for it
 * would be a control that can never match a marker. A share link naming it must
 * drop the value rather than blank the layer.
 */
export const MARHYS_SAMPLE_TYPE_VALUES = ["HF", "EM", "SW"] as const;
export type MarhysSampleType = (typeof MARHYS_SAMPLE_TYPE_VALUES)[number];
export type ClaimRiskValue = (typeof CLAIM_RISK_VALUES)[number];

export type LayerId = SeaLayerId | LandLayerId;

export interface LayerConfig {
  id: LayerId;
  label: string;
  color: string;          // CSS hex for UI
  // readonly so the array below can be `as const` — that is what preserves the
  // literal ids, which is what makes the completeness guard able to see them.
  fillRgba: readonly [number, number, number, number];  // deck.gl RGBA
  lineRgba: readonly [number, number, number, number];
  description: string;
}

export const LAYER_CONFIGS = [
  {
    id: "contracts",
    label: "Mining Concessions",
    color: "#00f2ff",
    fillRgba: [0, 242, 255, 60],
    lineRgba: [0, 242, 255, 200],
    description: "Active ISA exploration contract areas",
  },
  {
    id: "reserved-areas",
    label: "Reserved Areas",
    color: "#00ff9f",
    fillRgba: [0, 255, 159, 80],
    lineRgba: [0, 255, 159, 220],
    description: "Areas reserved for developing states",
  },
  {
    id: "apeis",
    label: "Protected Areas (APEIs)",
    color: "#bf5fff",
    fillRgba: [191, 95, 255, 70],
    lineRgba: [191, 95, 255, 220],
    description: "Areas of Particular Environmental Interest — no mining",
  },
  {
    id: "biodiversity-hotspots",
    label: "OBIS Species (Deep)",
    color: "#ff9f00",
    fillRgba: [255, 159, 0, 180],
    lineRgba: [255, 159, 0, 255],
    description: "Rare deep-sea species observations (corals, sponges) from OBIS",
  },
  {
    id: "relinquished-areas",
    label: "Relinquished Areas",
    color: "#ff4466",
    fillRgba: [255, 68, 102, 45],
    lineRgba: [255, 68, 102, 180],
    description: "Former concession areas handed back to ISA — mining abandoned",
  },
  {
    id: "seamounts",
    label: "Seamounts",
    color: "#7eb8f7",
    fillRgba: [126, 184, 247, 180],
    lineRgba: [126, 184, 247, 255],
    description: "37,889 seamounts (Yesson et al. 2020 / PANGAEA, SRTM v.11) — yellow = inside concession",
  },
  {
    id: "argo",
    label: "Argo Floats",
    color: "#00e5ff",
    fillRgba: [0, 229, 255, 200],
    lineRgba: [0, 229, 255, 255],
    description: "Real-time ocean health: temperature, salinity, O₂, pH — orange = near active mining zone",
  },
  {
    id: "hydrothermal-vents",
    label: "Hydrothermal Vents",
    color: "#ff4400",
    fillRgba: [255, 68, 0, 200],
    lineRgba: [255, 68, 0, 255],
    description: "Vent fields from InterRidge Database v3.4 — bright red + glow = active, confirmed by direct observation; dim red, no glow = active, inferred from a plume or anomaly; grey = inactive",
  },
  {
    id: "eez",
    label: "EEZ Boundaries",
    color: "#ffd700",
    fillRgba: [255, 215, 0, 0],
    lineRgba: [255, 215, 0, 180],
    description: "World Exclusive Economic Zones v12 (MarineRegions.org) — 200 nautical mile national jurisdiction boundaries",
  },
  {
    id: "protected-marine-sites",
    label: "UNESCO Marine Heritage",
    color: "#00e676",
    fillRgba: [0, 230, 118, 50],
    lineRgba: [0, 230, 118, 220],
    description: "UNESCO World Heritage Marine Programme sites — internationally recognised marine protected areas",
  },
  {
    id: "noise-risk",
    label: "Noise Risk Grid",
    color: "#ff6b00",
    fillRgba: [255, 107, 0, 180],
    lineRgba: [255, 107, 0, 255],
    description: "Impact Risk Index combining underwater noise (ICES/EMODnet) with cetacean density (OBIS-SEAMAP)",
  },
  {
    id: "oceansites",
    label: "OceanSITES Moorings",
    color: "#00cfff",
    fillRgba: [0, 207, 255, 200],
    lineRgba: [0, 207, 255, 255],
    description: "Fixed deep-ocean mooring stations measuring temperature, salinity, and currents over years (OceanSITES / OceanOPS)",
  },
  {
    id: "onc",
    label: "ONC Observatories",
    color: "#4db8a4",
    fillRgba: [77, 184, 164, 200],
    lineRgba: [77, 184, 164, 255],
    description: "Ocean Networks Canada observing stations — cabled seafloor nodes, drifting buoys and expedition instruments (CC BY 4.0)",
  },
  {
    id: "chess",
    label: "Chemosynthetic Sites",
    color: "#00c896",
    fillRgba: [0, 200, 150, 200],
    lineRgba: [0, 200, 150, 255],
    description: "Cold seeps, whale falls, and oxygen-minimum zones from the ChEssBase OBIS dataset — chemosynthetic ecosystems that exist independently of sunlight",
  },
  {
    id: "submarine-cables",
    label: "Submarine Cables",
    color: "#fbbf24",
    fillRgba: [251, 191, 36, 120],
    lineRgba: [251, 191, 36, 220],
    description: "Submarine cable routes from EMODnet (global telecom) and ONC (NE Pacific fibre-optic observatory network) — toggle each source independently",
  },
  {
    id: "onc-instruments",
    label: "ONC Instruments",
    color: "#a78bfa",
    fillRgba: [167, 139, 250, 200],
    lineRgba: [167, 139, 250, 255],
    description: "Individual instruments deployed on the Ocean Networks Canada cabled observatory — CTDs, hydrophones, cameras, junction boxes and more",
  },
  {
    id: "ports",
    label: "Port Locations",
    color: "#60a5fa",
    fillRgba: [96, 165, 250, 200],
    lineRgba: [96, 165, 250, 255],
    description: "Global port infrastructure — 3,898 ports across 175 countries",
  },
  {
    id: "tectonic-plates",
    label: "Tectonic Plates",
    color: "#c9956e",
    fillRgba: [201, 149, 110, 40],
    lineRgba: [201, 149, 110, 180],
    description: "Global plate boundaries and polygons (Peter Bird 2003)",
  },
  {
    id: "vessel-events",
    label: "Dark Vessels",
    color: "#f59e0b",
    fillRgba: [245, 158, 11, 220],
    lineRgba: [245, 158, 11, 255],
    description: "Sentinel-1 SAR detections correlated against our raw AIS ingest. Green = matched (AIS present), red = dark (no AIS, but AIS was received nearby), amber = ambiguous (no AIS reception nearby to judge).",
  },
  {
    id: "ais-live",
    label: "Live Vessels (AIS)",
    color: "#22d3ee",
    fillRgba: [34, 211, 238, 220],
    lineRgba: [34, 211, 238, 255],
    description: "Raw AIS positions ingested by Abyssal Claims from AISStream.io. Zoom in to see individual vessels; click for identity, flag, and 30-day track.",
  },
  {
    id: "bathymetry",
    label: "Seafloor Bathymetry",
    color: "#3b82a6",
    // Raster overlay — fill/line RGBA aren't rendered; values are placeholders to satisfy the type.
    fillRgba: [59, 130, 166, 0],
    lineRgba: [59, 130, 166, 0],
    description: "GEBCO_2026 shaded-relief seafloor depth (free, IHO/IOC)",
  },
  {
    id: "monitoring-density",
    label: "Baseline Monitoring Density",
    color: "#ff7a00",
    fillRgba: [255, 122, 0, 120],
    lineRgba: [255, 122, 0, 0],
    description: "Equal-area hexagonal grid showing density of baseline scientific monitoring records (OBIS, ChEssBase, Argo, OceanSITES, ONC, and more). Darker = more records (well-observed); lighter = sparse monitoring gap. Use alongside Mining Concessions to identify monitoring gaps near potential exploitation frontlines.",
  },
  {
    id: "offshore-activities",
    label: "Offshore Activities",
    color: "#dc2626",
    fillRgba: [220, 38, 38, 150],
    lineRgba: [220, 38, 38, 220],
    description: "Government-issued concessions for offshore oil/gas, wind farms, and seabed mining inside national EEZ/ECS jurisdictions.",
  },
  {
    id: "deepdata-stations",
    label: "Contractor Sampling Stations",
    color: "#f472b6",
    fillRgba: [244, 114, 182, 220],
    lineRgba: [244, 114, 182, 255],
    description: "Platform-derived analysis: physical sampling deployments aggregated from ISA contractor DwC archives via OBIS. Each dot is one Multi-Corer / Box-Corer / Epibenthic Sledge station, color-coded by contractor (NORI, UKSRL, BGR, IFREMER, …).",
  },
  {
    id: "hydrophone-stations",
    label: "Hydrophone Stations",
    color: "#e879f9",
    fillRgba: [232, 121, 249, 200],
    lineRgba: [232, 121, 249, 255],
    description: "Underwater acoustic monitoring stations — passive hydrophone deployments from cabled observatories and moored arrays. Per-feature colour overrides this default based on source/status.",
  },
  {
    id: "marhys",
    label: "Vent Fluid Chemistry",
    // Warm orange: this is discharge chemistry, and it sits next to the vents
    // layer without being mistaken for it. Per-sample colour overrides this by
    // sample type — reference seawater is deliberately NOT drawn in a vent colour.
    color: "#fb923c",
    fillRgba: [251, 146, 60, 200],
    lineRgba: [251, 146, 60, 255],
    description: "Measured compositions of hydrothermal vent fluids — MARHYS 4.0 (Diehl & Bach 2024). Each point is one sample, shown with the source's own coordinates. 883 of 6,788 samples carry no usable position and are absent from the map.",
  },
  {
    id: "ocean-currents",
    label: "Ocean Currents",
    color: "#5eead4",
    // Animated particle field — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [94, 234, 212, 0],
    lineRgba: [94, 234, 212, 0],
    description: "Animated surface (and 1000 m) ocean-current flow from Copernicus Marine — the field that drives mining-plume drift. Daily snapshot, ~0.5° — indicative, not navigational.",
  },
  {
    id: "woa-climatology",
    label: "Ocean Climatology (WOA)",
    color: "#50aac8",
    // Raster colour-field layer — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [80, 170, 200, 0],
    lineRgba: [80, 170, 200, 0],
    description: "World Ocean Atlas 2023 gridded climatology — temperature, salinity, oxygen, nutrients and more at 8 standard depths. Static annual mean at ~1° resolution.",
  },
  {
    id: "ocean-carbon",
    label: "Ocean Carbon (GLODAP)",
    color: "#34d399",
    // Raster colour-field layer — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [52, 211, 153, 0],
    lineRgba: [52, 211, 153, 0],
    description: "GLODAP v2 gridded ocean carbon climatology — dissolved inorganic carbon, total alkalinity, pH and more at standard depths. Research-grade, ~1° resolution.",
  },
  {
    id: "marine-carbon",
    label: "Marine Carbon (unified)",
    color: "#6ee7b7",
    // Hex-grid layer — fill/line RGBA placeholders to satisfy the type (rendered via PolygonLayer).
    fillRgba: [110, 231, 183, 0],
    lineRgba: [110, 231, 183, 0],
    description: "Unified carbon readout — click a hex cell to see surface CO₂, interior carbon, oxygen and physical climatology at one location, each labelled by source. Co-located samples, not a combined value.",
  },
  {
    id: "vme-suitability",
    label: "VME Suitability (modeled)",
    color: "#a78bfa",
    fillRgba: [167, 139, 250, 0],
    lineRgba: [167, 139, 250, 0],
    description: "MODELED habitat suitability for reef-forming deep-sea corals. Not observed data.",
  },
  {
    id: "coral-acid-exposure",
    label: "Coral Acidification Exposure (modeled)",
    color: "#be1e5a",
    // Hex-grid layer — fill/line RGBA placeholders to satisfy the type (rendered via PolygonLayer, coloured per-cell from /meta).
    fillRgba: [190, 30, 90, 0],
    lineRgba: [190, 30, 90, 0],
    description: "MODELED exposure of suitable coral habitat to undersaturated (corrosive) water — crosses our VME suitability model with reconstructed aragonite saturation horizons. Exposure, not loss: cold-water corals are documented living below the saturation horizon.",
  },
  {
    id: "ocean-co2-surface",
    label: "Surface Ocean CO₂ (SOCAT)",
    color: "#38bdf8",
    // Raster colour-field layer — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [56, 189, 248, 0],
    lineRgba: [56, 189, 248, 0],
    description: "SOCAT v2026 surface ocean CO₂ fugacity (fCO₂) measurements — global research cruise observations, colour-coded by decade. ~29 million data points.",
  },
  {
    id: "seabed-substrate",
    label: "Seabed Substrate",
    color: "#a8a29e",
    // Raster colour-field layer — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [168, 162, 158, 0],
    lineRgba: [168, 162, 158, 0],
    description: "Dutkiewicz et al. 2015 global seabed lithology — 13 sediment classes (gravel, sand, silts, biogenic oozes, volcanic ash) on a 0.1° grid. Raster field with pickable hex view.",
  },
  {
    id: "arctic-sediment-carbon",
    label: "Arctic Sediment Carbon",
    color: "#d4a373",
    fillRgba: [212, 163, 115, 180],
    lineRgba: [255, 255, 255, 180],
    description: "Circum-Arctic seafloor organic carbon (CASCADE): interpolated field + raw stations.",
  },
  {
    id: "memento",
    label: "Marine CH₄ / N₂O (MEMENTO)",
    color: "#2dd4bf",
    fillRgba: [45, 212, 191, 200],
    lineRgba: [45, 212, 191, 255],
    description: "GEOMAR MEMENTO database of surface ocean methane (CH₄) and nitrous oxide (N₂O) measurements — global research cruise casts, colour-coded by gas value and decade.",
  },
  {
    id: "methane-seeps",
    label: "Methane Seeps",
    color: "#ef4444",
    fillRgba: [239, 68, 68, 200],
    lineRgba: [239, 68, 68, 255],
    description: "Observed seafloor methane-emission sites (SEAFLEA): gas seeps, pockmarks, mounds, hydrate, chemosynthetic communities.",
  },
  {
    id: "mosaic-sediment",
    label: "Marine Sediment Carbon",
    color: "#c084fc",
    fillRgba: [192, 132, 252, 180],
    lineRgba: [192, 132, 252, 220],
    description: "Global marine sediment carbon cores (TOC, TN, δ¹³C, radiocarbon Δ¹⁴C) from MOSAIC (ETH Zürich)",
  },
  {
    id: "cumulative-human-impact",
    label: "Cumulative Human Impact",
    color: "#f0be5a",
    // Raster colour-field layer — fill/line RGBA are placeholders to satisfy the type.
    fillRgba: [240, 190, 90, 0],
    lineRgba: [240, 190, 90, 0],
    description: "MODELLED dimensionless index of total human pressure on marine ecosystems (NCEAS / Halpern et al. 2025) — the sum of ~10 anthropogenic stressors, present-state. Seabed mining is only a minor component; context, not accusation.",
  },
] as const satisfies readonly LayerConfig[];

/**
 * Sea layers that exist and are served, but carry NO `LAYER_CONFIGS` entry.
 *
 * `LAYER_CONFIGS` is not "every layer" — it is the list that drives three
 * specific behaviours, and being absent from it has three measured consequences
 * (verified 2026-09-12):
 *
 *  1. `Map3D.tsx` auto-enables any `LAYER_CONFIGS` id a returning visitor has
 *     not seen before — unconditionally, ignoring `default_on`. An absent layer
 *     is never switched on that way. All six below are `default_on: false`, so
 *     nothing is lost today; the first `default_on: true` layer added without an
 *     entry here would simply never appear, with no error anywhere.
 *  2. `controls/tooltips.ts` builds `LAYER_LABEL_MAP` from this array, so the
 *     "pairs with" chips fall back to the raw dash-id instead of a human label.
 *  3. ⛔ `WelcomeOverlay.tsx` validated the `?layers=` URL parameter against this
 *     array. A link naming one of these six had it silently dropped — a typo and
 *     a real-but-unlisted layer were indistinguishable, and both quietly produced
 *     a smaller, authoritative layer set. Fixed by validating against
 *     `SEA_LAYER_IDS` + `LAND_LAYER_IDS` instead; this list no longer gates it.
 *
 * ⚠️ The honest reason for each: none was recorded. Git history shows all six
 * were added by commits that registered "layer id + store state" — the id went
 * into the type and into LAYER_DEFAULTS, and `LAYER_CONFIGS` was simply not part
 * of that step. There is no principle separating them from the 38 that are
 * listed: `woa-climatology` is a field layer and IS listed, `wod-oxygen` is a
 * field layer and is NOT. So this is drift, written down rather than explained
 * away. ⛔ Do not invent a rationale here — a false reason looks considered and
 * stops the next person re-checking.
 */
export const NO_LAYER_CONFIG = [
  "arctic-catchments", "geotraces", "ocean-acidification",
  "oxygen-deox", "sios-svalbard", "wod-oxygen",
] as const;

/** Every sea layer either has a LAYER_CONFIGS entry or is named above. */
const _seaConfigsComplete: AssertComplete<
  (typeof LAYER_CONFIGS)[number]["id"] | LandLayerId,
  (typeof NO_LAYER_CONFIG)[number]
> = true;

/** ⛔ …and the two lists must not overlap: silencing the check above by adding a
 * layer that actually IS configured would make this file assert something false. */
const _seaConfigsDisjoint: AssertDisjoint<
  (typeof LAYER_CONFIGS)[number]["id"],
  (typeof NO_LAYER_CONFIG)[number]
> = true;

void _seaConfigsComplete;
void _seaConfigsDisjoint;
