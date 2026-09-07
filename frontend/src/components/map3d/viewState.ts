// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { MapView } from "@deck.gl/core";

export const BASEMAP = {
  version: 8 as const,
  sources: {
    "esri-satellite": {
      type: "raster" as const,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "Esri, DigitalGlobe, Earthstar Geographics, USGS",
    },
    "esri-labels": {
      type: "raster" as const,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
    },
  },
  layers: [
    { id: "satellite", type: "raster" as const, source: "esri-satellite" },
    { id: "labels",    type: "raster" as const, source: "esri-labels" },
  ],
};

// repeat:true makes deck.gl draw layers in every visible world copy, matching
// the basemap's renderWorldCopies. Without it, data renders only in the canonical
// [-180,180] copy and abruptly disappears at a vertical seam when panning across
// the Pacific / antimeridian.
export const MAP_VIEW = new MapView({ id: "default", repeat: true });

// Shared style for DeckGL hover tooltips.
export const tooltipStyle = {
  backgroundColor: "rgba(10, 14, 22, 0.92)",
  color: "#e6edf6",
  fontSize: "12px",
  padding: "6px 8px",
  borderRadius: "6px",
  border: "1px solid rgba(255,255,255,0.08)",
  pointerEvents: "none" as const,
  maxWidth: "260px",
};
