// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export function fmt(n: number | null | undefined, decimals = 1, unit = "") {
  if (n == null) return "—";
  return `${n.toFixed(decimals)}${unit}`;
}

export function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" });
}

/** Returns [lat, lon] — note: NOT GeoJSON [lon, lat] order. Named explicitly to prevent confusion. */
export function latLonFromProps(p: Record<string, unknown>): [number, number] | null {
  const lat = p.latitude ?? p.lat ?? p._lat;
  const lon = p.longitude ?? p.lon ?? p._lon;
  if (typeof lat === "number" && typeof lon === "number") return [lat, lon];
  return null;
}
