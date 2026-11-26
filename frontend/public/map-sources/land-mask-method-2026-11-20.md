# Method of the land mask, basemap release 2026-11-20 (ODbL 4.6)

Release: `2026-11-20` (layers land, coast, coast14). Licence of this method description: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

The satellite imagery of the basemap (layers `land`, `coast`, `coast14`) is cut to land with a land/water mask.
The mask is derived from OpenStreetMap data and is therefore a Derivative Database under the
[Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/). As required by section 4.6, this is the
method by which anyone can rebuild it from the same inputs. The method is offered under ODbL 1.0; the licence of the
tiles does not apply to it.

**Inputs**
- OpenStreetMap land polygons (derived from the OSM coastline), taken from the
  [Overture Maps](https://docs.overturemaps.org/attribution/) base theme, release `2026-10-21.0`, `type=land`,
  `subtype=land`, `class=land` (all selected rows have `sources.dataset = OpenStreetMap`).
  © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).
- Copernicus Sentinel-2 imagery, green (B03) and near-infrared (B08) bands: Sentinel-2 Level 3 quarterly mosaics
  2025 from the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/).

**Steps (per map tile, in Web Mercator, EPSG:3857)**
1. Rasterise the OSM land polygons to the tile grid (anti-aliased, 2× supersampling): OSM land = 1, sea = 0.
2. Compute NDWI = (green − NIR) / (green + NIR) from the imagery. Map it to a soft "not water" value: 1 at
   NDWI ≤ −0.05, 0 at NDWI ≥ 0.10, linear in between.
3. Keep that image-derived "not water" only within 1,000 m seaward of OSM land (distance measured to the nearest
   OSM land pixel in the tile). Further out to sea it is ignored.
4. Final mask = maximum of step 1 and step 3. So the mask is OSM land plus what the image shows as not water close
   to the OSM coastline: piers, breakwaters, harbour moles, sandbanks and coastline changes newer than OSM.
5. Light smoothing of the image-derived part (Gaussian, σ = 0.8 px) so the edge is not jagged.
6. Low zooms only (z8–11, layer `land`): the mask is eroded by one pixel, so the coarse coastline stays inside the
   sharper coastline of the z12–14 layers.

**Not part of the mask:** the imagery itself, GEBCO bathymetry and the place-name labels. The labels layer is
distributed separately under ODbL 1.0.

The mask is not a product of its own and is not published as a file; this description is the offer under
ODbL 4.6. Questions: through the contact on [something-rare.com](https://something-rare.com/).
