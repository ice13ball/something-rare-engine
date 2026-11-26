# Method of the land mask, basemap release 2026-11-11 (ODbL 4.6)

Release: `2026-11-11` (layers land z0–11, coast z12–13). Licence of this method description: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

The satellite imagery of the basemap is cut to land with a land/water mask made from OpenStreetMap land polygons.
In this release the mask is OpenStreetMap data only, rasterised without changes.

**Inputs**
- OpenStreetMap land polygons (derived from the OSM coastline), taken from the
  [Overture Maps](https://docs.overturemaps.org/attribution/) base theme, release `2026-10-21.0`, `type=land`,
  `subtype=land`, `class=land` (all selected rows have `sources.dataset = OpenStreetMap`).
  © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).

**Steps (per map tile, in Web Mercator, EPSG:3857)**
1. Rasterise the OSM land polygons to the tile grid (anti-aliased, 2× supersampling): OSM land = 1, sea = 0.
2. Low zooms only (z8–11, layer `land`): the mask is eroded by one pixel, so the coarse coastline stays inside the
   sharper coastline of the z12–14 layers.

**Not part of the mask:** the imagery itself (ESA WorldCover 2021 Sentinel-2 composite in this release), GEBCO
bathymetry and the place-name labels.

The mask is not published as a file; this description is the offer under ODbL 4.6. Questions: through the contact
on [something-rare.com](https://something-rare.com/).
