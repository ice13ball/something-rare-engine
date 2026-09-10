// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LandLayerId } from "./landLayers";

export type SeaLayerId = "contracts" | "reserved-areas" | "apeis" | "biodiversity-hotspots" | "seamounts" | "relinquished-areas" | "argo" | "hydrothermal-vents" | "eez" | "protected-marine-sites" | "noise-risk" | "oceansites" | "onc" | "onc-instruments" | "chess" | "submarine-cables" | "ports" | "tectonic-plates" | "vessel-events" | "ais-live" | "monitoring-density" | "offshore-activities" | "deepdata-stations" | "hydrophone-stations" | "bathymetry" | "ocean-currents" | "woa-climatology" | "oxygen-deox" | "wod-oxygen" | "memento" | "geotraces" | "methane-seeps" | "ocean-carbon" | "ocean-co2-surface" | "sios-svalbard" | "marine-carbon" | "arctic-catchments" | "seabed-substrate" | "arctic-sediment-carbon" | "mosaic-sediment" | "vme-suitability" | "ocean-acidification" | "coral-acid-exposure" | "cumulative-human-impact";

export type LayerId = SeaLayerId | LandLayerId;

export interface LayerConfig {
  id: LayerId;
  label: string;
  color: string;          // CSS hex for UI
  fillRgba: [number, number, number, number];  // deck.gl RGBA
  lineRgba: [number, number, number, number];
  description: string;
}

export const LAYER_CONFIGS: LayerConfig[] = [
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
    description: "Vent fields from InterRidge Database v3.4 — red triangle + plume = Active, grey outline = Inactive/Extinct",
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
];
