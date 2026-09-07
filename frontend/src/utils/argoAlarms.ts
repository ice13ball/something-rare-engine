// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export interface AlarmDef {
  key: string;
  label: string;
  color: string;
}

// Note: AlarmDef adds a `color` field beyond the spec's { key, label } minimum — the UI needs it for checkbox fill color.
export const ALARM_DEFS: AlarmDef[] = [
  { key: "low_oxygen", label: "Low oxygen", color: "#f97316" },
  { key: "low_ph",     label: "Low pH",     color: "#7c9bb5" },
];

export interface DatasetStats {
  meanTemp: number | null;
  stdTemp:  number | null;
  meanSal:  number | null;
  stdSal:   number | null;
}

function statsFor(values: number[]): { mean: number | null; std: number | null } {
  if (values.length < 2) return { mean: null, std: null };
  const mean = values.reduce((s, v) => s + v, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  const std = Math.sqrt(variance);
  return { mean, std: std > 0 ? std : null };
}

export function computeDatasetStats(features: any[]): DatasetStats {
  const temps: number[] = [];
  const sals:  number[] = [];
  for (const f of features) {
    const p = f.properties;
    if (p.surface_temp_c != null) temps.push(p.surface_temp_c);
    if (p.surface_salinity != null) sals.push(p.surface_salinity);
  }
  const { mean: meanTemp, std: stdTemp } = statsFor(temps);
  const { mean: meanSal,  std: stdSal  } = statsFor(sals);
  return { meanTemp, stdTemp, meanSal, stdSal };
}

// Depth-adaptive thresholds: O₂ and pH are measured at max_depth_m, so "alarming"
// means different things at surface vs. OMZ vs. abyssal depths.
export function oxygenThreshold(depth: number | null): number {
  if (depth == null || depth < 200) return 150;  // surface: well-oxygenated water expected
  if (depth < 1000)                 return 90;   // OMZ layer: some depletion natural, < 90 is hypoxic
  return 60;                                     // abyssal: < 60 is genuinely concerning
}

export function phThreshold(depth: number | null): number {
  if (depth == null || depth < 200) return 7.95; // surface: normal seawater 8.0–8.3
  if (depth < 1000)                 return 7.75; // mid-water: naturally lower due to CO₂
  return 7.60;                                   // deep: naturally acidic, < 7.6 is alarming
}

// Maximum pH physically attainable in seawater. No natural process — hydrothermal
// venting included — drives seawater pH *up* past ~8.6; even extreme surface blooms
// top out around 8.5. A value above this is a failed/drifting BGC pH sensor, not
// ocean chemistry. We deliberately do NOT flag a low floor: hydrothermal plumes and
// OMZ water genuinely depress pH, so a low reading is a real signal (shown via the
// neutral "below expected" anomaly path), not something to brand a sensor fault.
// Argo's real-time stream often ships these high values with no QC flag (ph_qc NULL),
// so we catch them here as a measurement-validity check only.
export const PH_PLAUSIBLE_MAX = 8.6;

export function phImplausible(ph: number | null | undefined): boolean {
  if (ph == null) return false;
  return Number(ph) > PH_PLAUSIBLE_MAX;
}

export function floatHasAlarm(
  props: Record<string, any>,
  alarm: string,
  _stats: DatasetStats,
): boolean {
  const depth: number | null = props.max_depth_m ?? null;
  switch (alarm) {
    case "low_oxygen":
      return props.oxygen_umol_kg != null && props.oxygen_umol_kg < oxygenThreshold(depth);
    case "low_ph":
      // Low pH is a genuine signal (hydrothermal plumes, OMZ water) — alarm on it.
      return props.ph != null && props.ph < phThreshold(depth);
    default:
      return false;
  }
}

// ── Expected-range labels for popup display ──────────────────────────────

export function oxygenExpected(depth: number | null): string {
  const t = oxygenThreshold(depth);
  return `≥ ${t} µmol/kg`;
}

export function phExpected(depth: number | null): string {
  const t = phThreshold(depth);
  return `≥ ${t.toFixed(2)}`;
}

