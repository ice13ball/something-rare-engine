// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/** Full overview treatment through zoom 8; smoothly return to true scale at 10. */
export function overviewWeight(zoom: number): number {
  const t = Math.max(0, Math.min(1, (zoom - 8) / 2));
  return 1 - t * t * (3 - 2 * t);
}

/**
 * Both generated mountain bases and the main chimney base contain a circle of
 * local radius 0.5. Add a shared height allowance, rather than clamping heights:
 * height differences between features survive the size floor. Scale XYZ together.
 */
export function overviewScale(
  trueScale: [number, number, number], columnRadius: number, weight: number,
): [number, number, number] {
  const factor = 1 + weight * columnRadius / (0.5 * trueScale[0]);
  return [trueScale[0] * factor, trueScale[1] * factor, trueScale[2] * factor];
}
