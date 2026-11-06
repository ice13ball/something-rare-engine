// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { MapView } from "@deck.gl/core";
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

// Basemap (Michal, 2026-11-06): NASA GIBS instead of Esri World Imagery, which had no licence for this use.
// ⛔ GIBS tiles exist only up to the TileMatrixSet's level (Blue Marble: GoogleMapsCompatible_Level8); `maxzoom` makes MapLibre overzoom instead of asking for levels that answer 400. The REST path is
// .../{TileMatrix}/{TileRow}/{TileCol}, i.e. z/y/x (from WMTSCapabilities.xml, epsg3857/best).
// ⛔ Coastlines, names and borders come from OpenFreeMap (OpenStreetMap data), NOT from GIBS: on 2026-11-06 GIBS'
// Reference_Labels_15m and Reference_Features_15m answered EPSG:3857 tiles with solid black images or 500s.
// ⛔ OpenFreeMap tiles carry the whole map, not only names: one z2 tile is ~700 KB gzipped, and a globe view
// pulled 6.2 MB. Below zoom 6 the labels read the z0/z1 tiles (`openfreemap-low`, maxzoom 1, overzoomed:
// countries, seas, borders, capitals); the full tiles load from zoom 6 on. The tile URL is set directly
// (`planet/latest`): with a TileJSON `url`, the TileJSON's maxzoom would override ours.
// Every host here must also be in server.js's CSP (img-src for rasters, connect-src for the vector tiles and
// glyphs), and in the privacy texts (each one receives the visitor's IP).
const GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";
const OFM_TILES = "https://tiles.openfreemap.org/planet/latest/{z}/{x}/{y}.pbf";
const OFM_ATTRIBUTION = '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">&copy; OpenMapTiles</a> Data &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';
const FULL_FROM_ZOOM = 6;
const NAME: ExpressionSpecification = ["coalesce", ["get", "name:en"], ["get", "name:latin"], ["get", "name"]];
const HALO = { "text-halo-color": "rgba(8, 14, 24, 0.85)", "text-halo-width": 1.2 };

/** Borders and names from one OpenFreeMap source, shown in [minzoom, maxzoom). */
function labelLayers(source: string, suffix: string, minzoom: number, maxzoom: number): LayerSpecification[] {
  const range = { minzoom, maxzoom };
  return [
    { id: `borders${suffix}`, type: "line", source, "source-layer": "boundary", ...range,
      filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": "rgba(235, 240, 245, 0.55)", "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.5, 8, 1.2] } },
    { id: `sea-names${suffix}`, type: "symbol", source, "source-layer": "water_name", ...range,
      filter: ["in", ["get", "class"], ["literal", ["ocean", "sea", "bay", "strait"]]],
      layout: { "text-field": NAME, "text-font": ["Noto Sans Italic"], "text-size": 11, "text-max-width": 8 },
      paint: { "text-color": "#9cc8e8", ...HALO } },
    { id: `country-names${suffix}`, type: "symbol", source, "source-layer": "place", ...range,
      filter: ["==", ["get", "class"], "country"],
      layout: { "text-field": NAME, "text-font": ["Noto Sans Bold"], "text-size": 11,
                "text-transform": "uppercase", "text-letter-spacing": 0.08, "text-max-width": 8 },
      paint: { "text-color": "#e8edf2", ...HALO } },
    { id: `city-names${suffix}`, type: "symbol", source, "source-layer": "place", minzoom: Math.max(minzoom, 4), maxzoom,
      filter: ["match", ["get", "class"], ["city", "town"], true, false],
      layout: { "text-field": NAME, "text-font": ["Noto Sans Regular"], "text-size": 11, "text-max-width": 8 },
      paint: { "text-color": "#e8edf2", ...HALO } },
  ];
}

export const BASEMAP: StyleSpecification = {
  version: 8,
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {
    "gibs-bluemarble": {
      type: "raster",
      tiles: [`${GIBS}/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`],
      tileSize: 256,
      maxzoom: 8,
      attribution: 'Imagery: <a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA GIBS / ESDIS</a>, Blue Marble: NASA Earth Observatory',
    },
    "openfreemap-low": { type: "vector", tiles: [OFM_TILES], maxzoom: 1, attribution: OFM_ATTRIBUTION },
    "openfreemap":     { type: "vector", tiles: [OFM_TILES], maxzoom: 14, attribution: OFM_ATTRIBUTION },
  },
  layers: [
    { id: "satellite", type: "raster", source: "gibs-bluemarble" },
    // Blue Marble is ~500 m per pixel, so coasts blur past z8; the OpenStreetMap water outline keeps them readable when
    // zoomed in. ⛔ Not GIBS Coastlines_15m: on 2026-11-06 it also returned solid black tiles (dark 256 px squares).
    { id: "coastlines", type: "line", source: "openfreemap", "source-layer": "water", minzoom: FULL_FROM_ZOOM,
      paint: { "line-color": "rgba(235, 240, 245, 0.45)", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.4, 12, 1] } },
    ...labelLayers("openfreemap-low", "-low", 0, FULL_FROM_ZOOM),
    ...labelLayers("openfreemap", "", FULL_FROM_ZOOM, 24),
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
