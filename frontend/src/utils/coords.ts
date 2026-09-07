// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Coordinate display helpers.
 *
 * Some upstream sources publish longitude on a 0-360 axis rather than
 * -180..180 (MEMENTO does for 47 casts: PROTEOMZ, HRS1316/1317, SPOT).
 * PostGIS wraps those correctly when it projects them, so the MAP is right —
 * only the raw `lon` column, surfaced verbatim through `/by-id`, reads wrong.
 *
 * We normalise at DISPLAY time, never at ingest: the stored column is the
 * provider's value and stays byte-for-byte theirs.
 */

/**
 * Wrap a longitude onto the -180..180 axis. Values already in range — including
 * exactly ±180 — pass through untouched, so a legitimate 180° is never flipped
 * to -180°. MEMENTO's out-of-range values top out at 283.7, so one wrap suffices.
 */
export function displayLon(lon: number): number {
  if (!Number.isFinite(lon)) return lon;
  if (lon > 180) return lon - 360;
  if (lon < -180) return lon + 360;
  return lon;
}

/** Format a lat/lon pair for a panel row, wrapping 0-360 longitudes. */
export function formatLatLon(lat: number, lon: number, digits = 4): string {
  return `${lat.toFixed(digits)}°, ${displayLon(lon).toFixed(digits)}°`;
}
