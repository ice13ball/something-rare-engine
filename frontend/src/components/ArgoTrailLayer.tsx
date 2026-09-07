// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import type { FeatureCollection, Point } from "geojson";
import { floatHasAlarm } from "../utils/argoAlarms";
import type { DatasetStats } from "../utils/argoAlarms";

/**
 * Builds deck.gl layers for Argo float drift trails.
 *
 * Groups all profiles by platform_id and renders per-float:
 * - Path connecting positions oldest → newest
 * - Dots at historical (non-latest) positions with age-based opacity
 * - Arrowhead wings at the latest position showing travel direction
 *
 * When a platform has been plume-traced, its historical dots become
 * clickable and show measurement data in a popup.
 *
 * Colours: lime-green = normal readings, red = any alarm triggered.
 */

const ALARM_KEYS = ["low_oxygen", "low_ph"] as const;

function floatHasAnyAlarm(props: Record<string, unknown>, stats: DatasetStats): boolean {
  return ALARM_KEYS.some(a => floatHasAlarm(props as Record<string, any>, a, stats));
}

interface TrailDotData {
  position: [number, number];
  ratio: number;
  hasAlarm: boolean;
  traced: boolean;
  properties: Record<string, unknown>;
}

function arrowWings(
  from: [number, number],
  to: [number, number],
  wingFraction = 0.3,
  wingAngleDeg = 28,
): [[number, number], [number, number]] {
  const midLat = (from[1] + to[1]) / 2;
  const cosLat = Math.cos(midLat * (Math.PI / 180));
  const dx = (to[0] - from[0]) * cosLat;
  const dy = to[1] - from[1];
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len === 0) return [to, to];
  const wingLen = len * wingFraction;
  const bx = -dx / len;
  const by = -dy / len;
  const a = wingAngleDeg * (Math.PI / 180);
  const cosA = Math.cos(a);
  const sinA = Math.sin(a);
  return [
    [to[0] + (bx * cosA - by * sinA) * wingLen / cosLat, to[1] + (bx * sinA + by * cosA) * wingLen],
    [to[0] + (bx * cosA + by * sinA) * wingLen / cosLat, to[1] + (-bx * sinA + by * cosA) * wingLen],
  ];
}

export function buildArgoTrailLayers(
  data: FeatureCollection | null,
  datasetStats: DatasetStats,
  tracedPlatforms?: Set<string>,
  onDotClick?: (info: PickingInfo) => void,
) {
  if (!data || !Array.isArray(data.features) || data.features.length === 0) return [];

  // Group by platform_id, collect positions sorted by date ascending
  const platforms = new Map<string, { pos: [number, number]; date: number; hasAlarm: boolean; properties: Record<string, unknown> }[]>();
  for (const f of data.features) {
    const p = f.properties ?? {};
    const pid = String(p.platform_id ?? "");
    if (!pid) continue;
    const pos = (f.geometry as Point).coordinates as [number, number];
    const date = new Date(p.profile_date ?? 0).getTime();
    if (!platforms.has(pid)) platforms.set(pid, []);
    platforms.get(pid)!.push({ pos, date, hasAlarm: floatHasAnyAlarm(p as Record<string, unknown>, datasetStats), properties: p });
  }

  const pathData:  { path: [number, number][] }[] = [];
  const dotData:   TrailDotData[] = [];
  const arrowData: { path: [number, number][] }[] = [];

  for (const [pid, profiles] of platforms) {
    if (profiles.length < 2) continue;
    profiles.sort((a, b) => a.date - b.date);

    // Unwrap longitudes across the antimeridian so paths don't wrap the globe.
    const unwrapped: [number, number][] = [profiles[0].pos];
    for (let i = 1; i < profiles.length; i++) {
      const prevLon = unwrapped[i - 1][0];
      let lon = profiles[i].pos[0];
      while (lon - prevLon > 180) lon -= 360;
      while (lon - prevLon < -180) lon += 360;
      unwrapped.push([lon, profiles[i].pos[1]]);
    }

    const traced = tracedPlatforms?.has(pid) ?? false;
    pathData.push({ path: unwrapped });

    // Dots at historical (non-latest) positions — colored per individual profile alarm
    const oldest = profiles[0].date;
    const newest = profiles[profiles.length - 1].date;
    const range  = Math.max(newest - oldest, 1);
    for (let i = 0; i < profiles.length - 1; i++) {
      dotData.push({
        position: unwrapped[i],
        ratio: (profiles[i].date - oldest) / range,
        hasAlarm: profiles[i].hasAlarm,  // per-profile, not platform-wide
        traced,
        properties: profiles[i].properties,
      });
    }

    // Arrowhead wings at the tip (second-to-last → latest position)
    const prev = unwrapped[unwrapped.length - 2];
    const curr = unwrapped[unwrapped.length - 1];
    const [w1, w2] = arrowWings(prev, curr);
    arrowData.push({ path: [curr, w1] }, { path: [curr, w2] });
  }

  if (!pathData.length) return [];

  const hasTraced = dotData.some(d => d.traced);

  return [
    new PathLayer({

      id: "argo-drift-trail",
      data: pathData,
      getPath: d => d.path,
      getColor: [120, 255, 80, 160],
      getWidth: 2,
      widthMinPixels: 1.5,
      widthMaxPixels: 3,
      pickable: false,
    }),
    new ScatterplotLayer<TrailDotData>({
      id: "argo-drift-dots",
      data: dotData,
      getPosition: d => d.position,
      getRadius: d => d.traced ? 3000 : 2200,
      getFillColor: d => {
        if (d.traced) {
          return d.hasAlarm
            ? [255, 120, 80, Math.round(120 + d.ratio * 135)]
            : [180, 255, 120, Math.round(120 + d.ratio * 135)];
        }
        return d.hasAlarm
          ? [255, 80, 60, Math.round(80 + d.ratio * 160)]
          : [160, 255, 100, Math.round(80 + d.ratio * 160)];
      },
      getLineColor: d => d.traced
        ? (d.hasAlarm ? [255, 80, 40, 255] : [100, 240, 60, 255])
        : (d.hasAlarm ? [255, 60, 40, 200] : [80, 220, 40, 200]),
      lineWidthMinPixels: hasTraced ? 1.5 : 1,
      stroked: true,
      radiusMinPixels: hasTraced ? 4 : 3,
      radiusMaxPixels: hasTraced ? 9 : 6,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      onClick: onDotClick,
      updateTriggers: {
        getRadius: tracedPlatforms?.size,
        getFillColor: tracedPlatforms?.size,
        getLineColor: tracedPlatforms?.size,
      },
    }),
    new PathLayer({
      id: "argo-drift-arrows",
      data: arrowData,
      getPath: d => d.path,
      getColor: [120, 255, 80, 200],
      getWidth: 2,
      widthMinPixels: 1.5,
      widthMaxPixels: 3,
      pickable: false,
    }),
  ];
}
