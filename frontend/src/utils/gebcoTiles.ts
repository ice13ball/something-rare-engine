// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * GEBCO bathymetry WMS tile URL builder.
 *
 * GEBCO's WMS only accepts bbox-based GetMap requests, not XYZ-template URLs.
 * deck.gl's TileLayer supports `data: (tile) => string` — this helper converts
 * the {x, y, z} tile index into the EPSG:3857 bbox GEBCO needs and returns a
 * GetMap URL pointing at the GEBCO_LATEST shaded-relief layer.
 *
 * GEBCO_LATEST auto-tracks the newest published grid (GEBCO_2024 today,
 * GEBCO_2025 from June 2026 onward) — so URLs we set now keep working.
 *
 * Attribution required: "GEBCO Compilation Group (2026) GEBCO Bathymetric
 * Compilation Group" + DOI on the project's about/attribution surface.
 */

const GEBCO_WMS = "https://wms.gebco.net/mapserv";
const TILE_PIXELS = 256;
// Web-Mercator half-circumference at the equator, in meters.
const HALF_CIRCUMFERENCE_M = 20037508.342789244;

/** Returns EPSG:3857 bbox [minX, minY, maxX, maxY] for the given XYZ tile. */
export function tileBbox3857(z: number, x: number, y: number): [number, number, number, number] {
  const n = 2 ** z;
  const tileWidth = (2 * HALF_CIRCUMFERENCE_M) / n;
  const minX = -HALF_CIRCUMFERENCE_M + x * tileWidth;
  const maxX = minX + tileWidth;
  const maxY = HALF_CIRCUMFERENCE_M - y * tileWidth;
  const minY = maxY - tileWidth;
  return [minX, minY, maxX, maxY];
}

/** Returns a GEBCO WMS GetMap URL for the given XYZ tile (shaded relief). */
export function gebcoTileUrl(z: number, x: number, y: number): string {
  const [minX, minY, maxX, maxY] = tileBbox3857(z, x, y);
  const qs = new URLSearchParams({
    service: "WMS",
    version: "1.3.0",
    request: "GetMap",
    layers: "GEBCO_LATEST",
    styles: "",
    crs: "EPSG:3857",
    bbox: `${minX},${minY},${maxX},${maxY}`,
    width: String(TILE_PIXELS),
    height: String(TILE_PIXELS),
    format: "image/png",
    transparent: "true",
  });
  return `${GEBCO_WMS}?${qs.toString()}`;
}

export const GEBCO_ATTRIBUTION = "GEBCO Compilation Group · GEBCO_2025 Grid";
