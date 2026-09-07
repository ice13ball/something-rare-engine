// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { FeatureCollection, Point } from "geojson";

/**
 * Builds deck.gl layers for historical plume back-track paths.
 *
 * Each feature in the FeatureCollection is a Point at the back-tracked origin
 * with `properties.path_coords` containing the full [[lon,lat],...] path.
 *
 * Visual encoding:
 * - Origin dots: white, sized by recency (recent = larger + brighter), clickable
 * - Path lines: very faint orange trails
 * - Solid faint trail connecting all origins chronologically (oldest → newest)
 */

export interface PlumeOriginInfo {
  profile_id: string;
  platform_id: string | number;
  profile_date: string;
  contractor_name: string | null;
  origin_lon: number;
  origin_lat: number;
  speed_cms: number | null;
  steps_completed: number | null;
  source_dataset: string | null;
}

export function buildPlumeHistoryLayers(
  data: FeatureCollection | null,
  idSuffix = "",
  onDotClick?: (info: PlumeOriginInfo, x: number, y: number) => void,
) {
  if (!data || data.features.length === 0) return [];
  const sfx = idSuffix ? `-${idSuffix}` : "";

  // Sort ascending by profile_date so trail line runs past → present
  const sorted = [...data.features].sort((a, b) => {
    const da = new Date(a.properties?.profile_date ?? 0).getTime();
    const db = new Date(b.properties?.profile_date ?? 0).getTime();
    return da - db;
  });

  const now = Date.now();
  const oldest = new Date(sorted[0].properties?.profile_date ?? now).getTime();
  const newest = new Date(sorted[sorted.length - 1].properties?.profile_date ?? now).getTime();
  const range = Math.max(newest - oldest, 1);

  // age ratio: 0 = oldest, 1 = newest
  const withAge = sorted.map(f => {
    const t = new Date(f.properties?.profile_date ?? now).getTime();
    return { f, ratio: (t - oldest) / range };
  });

  // ── Individual path trails ──────────────────────────────────────────────
  const pathData = withAge.flatMap(({ f, ratio }) => {
    const coords: [number, number][] = f.properties?.path_coords ?? [];
    if (coords.length < 2) return [];
    return [{ path: coords, color: [214, 164, 64, Math.round(20 + ratio * 60)] as [number, number, number, number] }];
  });

  const pathLayer = new PathLayer({
    id: `plume-history-paths${sfx}`,
    data: pathData,
    getPath: d => d.path,
    getColor: d => d.color,
    getWidth: 1.5,
    widthMinPixels: 1,
    widthMaxPixels: 2,
    pickable: false,
  });

  // ── Chronological trail connecting all origins (solid line) ─────────────
  const originCoords = withAge.map(({ f }) =>
    (f.geometry as Point).coordinates as [number, number]
  );

  const trailLayer = new PathLayer({
    id: `plume-history-trail${sfx}`,
    data: [{ path: originCoords }],
    getPath: d => d.path,
    getColor: [214, 164, 64, 40],
    getWidth: 1,
    widthMinPixels: 1,
    pickable: false,
  });

  // ── Origin dots ─────────────────────────────────────────────────────────
  const dotData = withAge.map(({ f, ratio }) => ({
    position: (f.geometry as Point).coordinates as [number, number],
    ratio,
    properties: f.properties,
  }));

  const glowLayer = new ScatterplotLayer({
    id: `plume-history-origin-glow${sfx}`,
    data: dotData,
    getPosition: d => d.position,
    getRadius: d => 6000 + d.ratio * 4000,
    getFillColor: d => [214, 164, 64, Math.round(15 + d.ratio * 35)],
    pickable: false,
    radiusUnits: "meters",
  });

  const dotLayer = new ScatterplotLayer({
    id: `plume-history-origins${sfx}`,
    data: dotData,
    getPosition: d => d.position,
    getRadius: d => 2500 + d.ratio * 2000,
    getFillColor: d => [255, 255, 255, Math.round(80 + d.ratio * 175)],
    getLineColor: [214, 164, 64, 180],
    stroked: true,
    lineWidthMinPixels: 1,
    getLineWidth: 800,
    pickable: !!onDotClick,
    radiusUnits: "meters",
    autoHighlight: !!onDotClick,
    highlightColor: [220, 150, 255, 220],
    onClick: onDotClick
      ? (info: any) => {
          const p = info.object?.properties ?? {};
          const [lon, lat] = info.object?.position ?? [0, 0];
          onDotClick(
            {
              profile_id:      p.profile_id   ?? "",
              platform_id:     p.platform_id  ?? "",
              profile_date:    p.profile_date ?? "",
              contractor_name: p.contractor_name ?? null,
              origin_lon:      p.origin_lon   ?? lon,
              origin_lat:      p.origin_lat   ?? lat,
              speed_cms:       p.speed_cms    ?? null,
              steps_completed: p.steps_completed ?? null,
              source_dataset:  p.source_dataset  ?? null,
            },
            info.x,
            info.y,
          );
        }
      : undefined,
  });

  return [pathLayer, trailLayer, glowLayer, dotLayer];
}
