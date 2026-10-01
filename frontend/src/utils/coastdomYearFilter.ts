// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * CoastDOM year-range filter — ONE predicate shared by the Map3D useMemo, the
 * flyConfigs predicate, the colour accessor and the detail panel, so they cannot
 * drift apart.
 *
 * ⛔ The filter must never hide data unless the user narrows it. The store holds
 * `null` for "full range" and every function here treats an effective range of
 * `null` as the identity: all positions pass and the count is `n_samples`
 * (undated samples included).
 * ⛔ A payload without `year_counts` (cached JSON from before the field existed)
 * has no bounds, so the effective range is `null`: show everything, control off.
 * Years are inclusive at both ends. `year_counts` keys are strings.
 */
export type YearRange = readonly [number, number];
export type YearBounds = { min: number; max: number };

export const COASTDOM_YEAR_RANGE_KEY = "coastdomYearRange";

type Props = Record<string, unknown> | null | undefined;

function yearCounts(props: Props): Record<string, number> | null {
  const yc = props?.year_counts;
  return yc && typeof yc === "object" && !Array.isArray(yc) ? (yc as Record<string, number>) : null;
}

/** Min/max year present anywhere in the data; null when nothing can be filtered on. */
export function coastdomYearBounds(features: ReadonlyArray<{ properties?: Props }> | null | undefined): YearBounds | null {
  let min = Infinity;
  let max = -Infinity;
  for (const f of features ?? []) {
    const yc = yearCounts(f.properties);
    if (!yc) continue;
    for (const k of Object.keys(yc)) {
      const y = Number(k);
      if (!Number.isInteger(y) || !(Number(yc[k]) > 0)) continue;
      if (y < min) min = y;
      if (y > max) max = y;
    }
  }
  return Number.isFinite(min) ? { min, max } : null;
}

/**
 * The range that actually filters. null (= no filtering) when there is no
 * stored range, no bounds, or the range covers every year in the data.
 * Otherwise the range clamped to [from <= to].
 */
export function effectiveCoastdomRange(range: YearRange | null, bounds: YearBounds | null): YearRange | null {
  if (!range || !bounds) return null;
  const from = Math.min(range[0], range[1]);
  const to = Math.max(range[0], range[1]);
  if (from <= bounds.min && to >= bounds.max) return null;
  return [from, to];
}

/** Samples of one position inside the range. `null` range: every sample, undated too. */
export function coastdomInRangeCount(props: Props, range: YearRange | null): number {
  const total = Number(props?.n_samples ?? 0);
  if (!range) return total;
  const yc = yearCounts(props);
  if (!yc) return total; // cannot filter -> never hide
  let n = 0;
  for (const [k, v] of Object.entries(yc)) {
    const y = Number(k);
    if (y >= range[0] && y <= range[1]) n += Number(v) || 0;
  }
  return n;
}

export function coastdomPassesYearRange(props: Props, range: YearRange | null): boolean {
  if (!range) return true;
  if (!yearCounts(props)) return true;
  return coastdomInRangeCount(props, range) > 0;
}

/** Calendar year of a `sample_date` (ISO "YYYY-MM-DD"); null when absent/unparseable. */
export function sampleYear(date: unknown): number | null {
  if (typeof date !== "string") return null;
  const m = /^(\d{4})-/.exec(date);
  return m ? Number(m[1]) : null;
}

/** Panel side: keep samples dated inside the range; null range keeps all (undated too). */
export function filterSamplesByYear<T extends { sample_date?: unknown }>(samples: readonly T[], range: YearRange | null): T[] {
  if (!range) return [...samples];
  return samples.filter((s) => {
    const y = sampleYear(s.sample_date);
    return y !== null && y >= range[0] && y <= range[1];
  });
}

/** Share-link payload: ["2010","2022"] or null when not narrowed. */
export function encodeYearRange(range: YearRange | null): string[] | null {
  return range ? [String(range[0]), String(range[1])] : null;
}

/** Strict decode of a link value; anything malformed -> null (= full range). */
export function decodeYearRange(value: unknown): YearRange | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  if (!value.every((v) => typeof v === "string" && /^\d{4}$/.test(v))) return null;
  const a = Number(value[0]);
  const b = Number(value[1]);
  return a <= b ? [a, b] : [b, a];
}
