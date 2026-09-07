// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Pure-SVG mini-map of a polygon's true shape. Lives in the panel rather than
// as a deck.gl overlay so it sidesteps MVT clip artefacts entirely — the user
// sees one clean shape regardless of how the map fragments it across tiles.
// Renders MultiPolygon (and Polygon) with proper hole rendering via even-odd
// fill rule, and marks where the user clicked with a concentric dot.
export function PolygonThumbnail({
  geometry,
  clickLon,
  clickLat,
  fillRgb,
}: {
  geometry: any;
  clickLon?: number;
  clickLat?: number;
  fillRgb: string; // CSS color, e.g. "rgb(220 38 38)"
}) {
  if (!geometry || (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon")) {
    return null;
  }
  const polygons: number[][][][] = geometry.type === "Polygon"
    ? [geometry.coordinates]
    : geometry.coordinates;

  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const poly of polygons) for (const ring of poly) for (const [lon, lat] of ring) {
    if (lon < minLon) minLon = lon; if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat; if (lat > maxLat) maxLat = lat;
  }

  const W = 240, H = 120, PAD = 8;
  const dataW = Math.max(maxLon - minLon, 1e-6);
  const dataH = Math.max(maxLat - minLat, 1e-6);
  const drawW = W - 2 * PAD, drawH = H - 2 * PAD;
  const scale = Math.min(drawW / dataW, drawH / dataH);
  const offX = PAD + (drawW - dataW * scale) / 2;
  const offY = PAD + (drawH - dataH * scale) / 2;

  const project = (lon: number, lat: number): [number, number] => [
    offX + (lon - minLon) * scale,
    H - offY - (lat - minLat) * scale, // flip Y so north is up
  ];

  const d = polygons.map(poly =>
    poly.map(ring =>
      ring.map(([lon, lat], i) => {
        const [x, y] = project(lon, lat);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ") + " Z"
    ).join(" ")
  ).join(" ");

  const marker = clickLon != null && clickLat != null && Number.isFinite(clickLon) && Number.isFinite(clickLat)
    ? project(clickLon, clickLat)
    : null;

  return (
    <svg
      width="100%" height={H} viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      className="block bg-black/40 rounded-md mb-3 border border-white/10"
    >
      <path d={d} fill={fillRgb} fillOpacity={0.25} stroke={fillRgb} strokeOpacity={0.9} strokeWidth={1.2} fillRule="evenodd" />
      {marker && (
        <>
          <circle cx={marker[0]} cy={marker[1]} r={5} fill="white" fillOpacity={0.35} />
          <circle cx={marker[0]} cy={marker[1]} r={2.5} fill="white" />
        </>
      )}
    </svg>
  );
}


