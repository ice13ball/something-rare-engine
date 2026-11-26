// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { BitmapLayer } from "@deck.gl/layers";

/**
 * A BitmapLayer for the server-rendered field PNGs (WOA, nutrients model, ocean colour, oxygen, carbon,
 * acidification, CO₂). Those PNGs are plate carrée grids (EPSG:4326: equal steps of latitude per pixel row),
 * sliced in Map3D into quads of about 29° of latitude each.
 *
 * ⛔ A plain BitmapLayer stretches its image LINEARLY between the quad's corners in Web Mercator, so inside each
 * 29° band every row landed at the wrong latitude: about 6° too far north at 70°N, 1.7° at 41°N, with a visible
 * seam at every band edge (IO PAN report on MOCA, 26.11.2026: ocean colour "as if the layer and the map had
 * different projections"; on the Baltic the data covered southern Sweden). `_imageCoordinateSystem: "lnglat"`
 * makes deck.gl look the texture up per fragment by longitude and latitude, so every pixel sits on its own cell.
 *
 * Not for the TileLayer rasters (catchments, substrate, bathymetry, forest loss…): those tiles are Web Mercator.
 */
export class FieldBitmapLayer extends BitmapLayer {
  static layerName = "FieldBitmapLayer";
  static defaultProps = { _imageCoordinateSystem: "lnglat" as const };
}
