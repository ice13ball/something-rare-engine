// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { LineLayer } from "@deck.gl/layers";

export interface CurrentsMeta {
  url: string;
  bounds: [number, number, number, number]; // [W, S, E, N]
  imageUnscale: [number, number];
  date: string;
  depth_label: string;
  width: number;
  height: number;
  available_dates?: string[];
  min_date?: string;
  max_date?: string;
}

// One decoded arrow sample (static reduced-motion fallback).
export interface CurrentArrow {
  source: [number, number]; // [lon, lat]
  target: [number, number]; // [lon, lat] = source + scaled velocity
  speed: number;            // m/s, for color
}

/** Cool→warm ramp for current speed (m/s). */
export function speedColor(speed: number): [number, number, number] {
  const t = Math.min(speed / 1.5, 1); // saturate at 1.5 m/s
  // teal (low) -> amber (high)
  return [
    Math.round(94 + t * 157),
    Math.round(234 - t * 43),
    Math.round(212 - t * 176),
  ];
}

/**
 * Static arrow flow-field — the reduced-motion fallback for the ocean-currents
 * layer. The animated version is a 2D-canvas particle overlay rendered
 * separately (see CurrentsParticleCanvas), so it isn't a deck.gl layer.
 * Returns [] when no arrows are ready.
 */
export function buildCurrentsArrowLayer(arrows: CurrentArrow[] | null): any[] {
  if (!arrows || arrows.length === 0) return [];
  return [
    new LineLayer<CurrentArrow>({
      id: "ocean-currents-arrows",
      data: arrows,
      getSourcePosition: (d) => d.source,
      getTargetPosition: (d) => d.target,
      getColor: (d) => [...speedColor(d.speed), 200] as [number, number, number, number],
      getWidth: 1.5,
      widthMinPixels: 1,
      // Cast: deck.gl 9.2 Parameters type omits depthTest on generic LineLayer<T>.
      parameters: { depthTest: false } as any,
      pickable: false,
    }),
  ];
}
