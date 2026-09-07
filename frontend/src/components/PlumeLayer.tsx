// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { ScatterplotLayer, GeoJsonLayer, PathLayer } from "@deck.gl/layers";
import type { FeatureCollection, Feature } from "geojson";

/**
 * Zoom-adaptive arrowhead: stays ~10px on screen at any zoom level.
 * `sizeDeg` is computed from zoom so the arrow scales with the map.
 */
function arrowheadWings(
  from: [number, number],
  to: [number, number],
  sizeDeg: number,
  wingAngleDeg = 25
): [[number, number], [number, number]] {
  const midLat = (from[1] + to[1]) / 2;
  const cosLat = Math.cos(midLat * (Math.PI / 180));

  const dx = (to[0] - from[0]) * cosLat;
  const dy = to[1] - from[1];
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len === 0) return [to, to];

  // Back-direction unit vector
  const bx = -dx / len;
  const by = -dy / len;

  const a = wingAngleDeg * (Math.PI / 180);
  const cosA = Math.cos(a);
  const sinA = Math.sin(a);

  const w1: [number, number] = [
    to[0] + (bx * cosA - by * sinA) * sizeDeg / cosLat,
    to[1] + (bx * sinA + by * cosA) * sizeDeg,
  ];
  const w2: [number, number] = [
    to[0] + (bx * cosA + by * sinA) * sizeDeg / cosLat,
    to[1] + (-bx * sinA + by * cosA) * sizeDeg,
  ];

  return [w1, w2];
}

/**
 * Returns deck.gl layers for plume back-track visualisation.
 * Called from MapView's layer array — not a React component.
 *
 * Visual:
 * - Single arrow: origin → float current position
 * - White dot + orange glow at the 7-day-ago origin
 * - Orange highlight on the source mining contract polygon (if available)
 *
 * @param idSuffix — unique suffix to avoid layer ID collisions when multiple
 *   traces are rendered simultaneously (e.g. the argoId / profile_id).
 */
export function buildPlumeLayers(correlationData: FeatureCollection | null, idSuffix = "", zoom = 3) {
  if (!correlationData) return [];
  const sfx = idSuffix ? `-${idSuffix}` : "";
  // Keep arrowhead at ~10px on screen regardless of zoom
  const arrowSizeDeg = 10 * 360 / (256 * Math.pow(2, zoom));

  const pathFeature = correlationData.features.find(
    (f: Feature) => f.properties?.role === "backtrack_path"
  );
  const sourceFeature = correlationData.features.find(
    (f: Feature) => f.properties?.role === "source_contract"
  );

  const layers = [];

  if (pathFeature?.geometry.type === "LineString") {
    const coords = (pathFeature.geometry as any).coordinates as [number, number][];
    const origin  = coords[coords.length - 1]; // white dot — where water was 7 days ago
    const current = coords[0];                 // Argo float current position

    const [wing1, wing2] = arrowheadWings(origin, current, arrowSizeDeg);

    // Arrow: shaft + two arrowhead wings, all as one PathLayer
    layers.push(
      new PathLayer({
        id: `plume-arrow${sfx}`,
        data: [
          { path: [origin, current] },   // shaft
          { path: [current, wing1] },    // left wing
          { path: [current, wing2] },    // right wing
        ],
        getPath: (d: any) => d.path,
        getColor: [214, 164, 64, 200],
        getWidth: 2,
        widthMinPixels: 2,
        widthMaxPixels: 4,
        capRounded: true,
        parameters: { depthTest: false },
        pickable: false,
      })
    );

    // Glow + white dot at origin (7-day-ago position)
    layers.push(
      new ScatterplotLayer({
        id: `plume-origin-glow${sfx}`,
        data: [{ position: origin }],
        getPosition: (d: any) => d.position,
        getRadius: 30000,
        getFillColor: [214, 164, 64, 30],
        radiusMinPixels: 10,
        radiusMaxPixels: 25,
        parameters: { depthTest: false },
        pickable: false,
      }),
      new ScatterplotLayer({
        id: `plume-origin${sfx}`,
        data: [{ position: origin }],
        getPosition: (d: any) => d.position,
        getRadius: 12000,
        getFillColor: [255, 255, 255, 240],
        getLineColor: [214, 164, 64, 255],
        stroked: true,
        lineWidthMinPixels: 2,
        radiusMinPixels: 5,
        radiusMaxPixels: 12,
        parameters: { depthTest: false },
        pickable: false,
      })
    );
  }

  // Source mining contract highlight
  if (sourceFeature) {
    layers.push(
      new GeoJsonLayer({
        id: `plume-source-contract${sfx}`,
        data: { type: "FeatureCollection", features: [sourceFeature] },
        filled: false,
        stroked: true,
        getLineColor: [214, 164, 64, 255],
        getLineWidth: 3,
        lineWidthMinPixels: 2,
        parameters: { depthTest: false },
        pickable: false,
      })
    );
  }

  return layers;
}
