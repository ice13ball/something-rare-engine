// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState } from "react";
import type { TFunction } from "i18next";
import { phImplausible } from "../../../utils/argoAlarms";

import { API } from "../shared/tokens";
import { latLonFromProps } from "../shared/format";
import { Row, Section, BodyText } from "../shared/primitives";

// Shared by ArgoPanel and TrailDotPanel — the two Argo float panels.

// QC flags: 1=good, 2=probably-good, 3=probably-bad, 4=bad, 8=estimated, 9=missing
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function argoQcNote(p: Record<string, unknown>, t: TFunction<any, any>): string | null {
  const isBad = (q: unknown) => q != null && (Number(q) === 3 || Number(q) === 4);
  const phVal = p.ph != null ? Number(p.ph) : null;

  // Physically impossible pH = failed sensor. Fires even when Argo set no QC flag
  // (ph_qc NULL), which is the common case for the affected floats.
  if (phImplausible(phVal)) {
    return t("argo.sensorFaultPh", { phVal: phVal!.toFixed(3) });
  }

  const flagged: string[] = [];
  if (isBad(p.ph_qc))     flagged.push(`pH ${Number(p.ph).toFixed(3)}`);
  if (isBad(p.oxygen_qc)) flagged.push(`oxygen ${Number(p.oxygen_umol_kg).toFixed(1)} µmol/kg`);
  if (isBad(p.temp_qc))   flagged.push(`deep temp ${Number(p.deep_temp_c).toFixed(2)} °C`);
  if (isBad(p.sal_qc))    flagged.push(`deep salinity ${Number(p.deep_salinity).toFixed(3)} PSU`);
  if (flagged.length === 0) return null;

  // Build context-aware note. pH this low + normal temp = sensor fault (not volcanic vent).
  const phFlagged = isBad(p.ph_qc);
  const deepTemp = p.deep_temp_c != null ? Number(p.deep_temp_c) : null;

  if (phFlagged && phVal != null && phVal < 6 && deepTemp != null && deepTemp < 10 && !isBad(p.temp_qc)) {
    return t("argo.qcFaultPh", { phVal: phVal.toFixed(2), deepTemp: deepTemp.toFixed(2) });
  }
  return t("argo.qcFaultFlagged", { count: flagged.length, sensors: flagged.join(", ") });
}


// Live seasonal-cycle explorer: pick a month, see the WOA "normal" (T/S/O₂) for
// that month at this float's location/depth. Independent of the float's date —
// observed values and the anomaly block stay tied to the actual profile date.
// Uses the live /v1/woa/sample point endpoint (cheap point lookup, cached grids),
// caches per month client-side, aborts stale fetches, and self-hides on error.
function WoaSeasonalExplorer({ lat, lon, deepDepth, profileMonth, t }: {
  lat: number; lon: number; deepDepth: number; profileMonth: number; t: TFunction<any, any>;
}) {
  const [month, setMonth] = useState(profileMonth);
  const [vals, setVals] = useState<Record<string, number | null> | null>(null);
  const [loading, setLoading] = useState(false);
  const cacheRef = useRef<Map<number, Record<string, number | null>>>(new Map());

  useEffect(() => {
    const cached = cacheRef.current.get(month);
    if (cached) { setVals(cached); setLoading(false); return; }
    const ctrl = new AbortController();
    let aborted = false;
    setLoading(true);
    fetch(`${API}/api/v1/woa/sample?lat=${lat}&lon=${lon}&month=${month}&deep_m=${deepDepth}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (!aborted) { cacheRef.current.set(month, d); setVals(d); setLoading(false); } })
      .catch(() => { if (!aborted) { setVals(null); setLoading(false); } });
    return () => { aborted = true; ctrl.abort(); };
  }, [month, lat, lon, deepDepth]);

  const fmt = (v: unknown, d = 2, u = "") => (v == null ? "—" : `${Number(v).toFixed(d)}${u}`);
  const hasAny = !!vals && [
    vals.woa_surface_temp_c, vals.woa_surface_sal,
    vals.woa_deep_temp_c, vals.woa_deep_sal, vals.woa_deep_oxygen_umol_kg,
  ].some((x) => x != null);

  return (
    <Section title={t("argo.woaSeasonalTitle")}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("argo.woaSeasonalMonthLabel")}</span>
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
        >
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>
              {new Date(Date.UTC(2000, m - 1, 1)).toLocaleString(undefined, { month: "long" })}
            </option>
          ))}
        </select>
      </div>
      {loading ? (
        <BodyText className="text-white/65 text-xs">{t("argo.woaSeasonalLoading")}</BodyText>
      ) : hasAny ? (
        <>
          {vals!.woa_surface_temp_c != null && <Row label={t("argo.surfaceTempLabel")} value={fmt(vals!.woa_surface_temp_c, 2, " °C")} />}
          {vals!.woa_surface_sal != null && <Row label={t("argo.surfaceSalinityLabel")} value={fmt(vals!.woa_surface_sal, 3, " PSU")} />}
          {vals!.woa_deep_temp_c != null && <Row label={t("argo.deepTempLabel")} value={fmt(vals!.woa_deep_temp_c, 2, " °C")} />}
          {vals!.woa_deep_sal != null && <Row label={t("argo.deepSalinityLabel")} value={fmt(vals!.woa_deep_sal, 3, " PSU")} />}
          {vals!.woa_deep_oxygen_umol_kg != null && <Row label={t("argo.oxygenLabel")} value={fmt(vals!.woa_deep_oxygen_umol_kg, 1, " µmol/kg")} />}
        </>
      ) : (
        <BodyText className="text-white/65 text-xs">{t("argo.woaSeasonalNoData")}</BodyText>
      )}
      <BodyText className="text-white/65 text-xs mt-1">{t("argo.woaSeasonalNote")}</BodyText>
    </Section>
  );
}

// WOA observed-vs-climatology anomaly + regional-climatology blocks. Shared by
// the live float panel (ArgoPanel) and every historical trail point (TrailDotPanel)
// — each argo_profiles row carries its own woa_* climatology values.
export function WoaSections({ p, t }: { p: Record<string, unknown>; t: TFunction<any, any> }) {
  const anomaly = (obs: unknown, clim: unknown, d = 2, unit = "") => {
    if (obs == null || clim == null) return null;
    const delta = Number(obs) - Number(clim);
    const sign = delta >= 0 ? "+" : "";
    const col = Math.abs(delta) < 1e-9 ? "text-white/80" : delta > 0 ? "text-amber-300" : "text-sky-300";
    return <span className={col}>{sign}{delta.toFixed(d)}{unit}</span>;
  };
  const aST = anomaly(p.surface_temp_c, p.woa_surface_temp_c, 2, " °C");
  const aSS = anomaly(p.surface_salinity, p.woa_surface_sal, 3, " PSU");
  const aDT = anomaly(p.deep_temp_c, p.woa_deep_temp_c, 2, " °C");
  const aDS = anomaly(p.deep_salinity, p.woa_deep_sal, 3, " PSU");
  const aO2 = anomaly(p.oxygen_umol_kg, p.woa_deep_oxygen_umol_kg, 1, " µmol/kg");
  const hasAnomaly = aST || aSS || aDT || aDS || aO2;
  const ctx = (v: unknown, d = 2, unit = "") => v == null ? null : `${Number(v).toFixed(d)}${unit}`;
  const hasCtx = [p.woa_deep_aou, p.woa_deep_o2sat, p.woa_deep_phosphate, p.woa_deep_silicate, p.woa_deep_nitrate].some((x) => x != null);
  return (
    <>
      {hasAnomaly && (
        <Section title={t("argo.woaAnomalyTitle")}>
          {aST && <Row label={t("argo.surfaceTempLabel")} value={aST} />}
          {aSS && <Row label={t("argo.surfaceSalinityLabel")} value={aSS} />}
          {aDT && <Row label={t("argo.deepTempLabel")} value={aDT} />}
          {aDS && <Row label={t("argo.deepSalinityLabel")} value={aDS} />}
          {aO2 && <Row label={t("argo.oxygenLabel")} value={aO2} />}
          <BodyText className="text-white/65 text-xs mt-1">{t("argo.woaAnomalyNote")}</BodyText>
        </Section>
      )}
      {hasCtx && (
        <Section title={t("argo.woaContextTitle")}>
          {p.woa_deep_aou != null && <Row label="AOU" value={ctx(p.woa_deep_aou, 1, " µmol/kg")!} />}
          {p.woa_deep_o2sat != null && <Row label={t("argo.o2satLabel")} value={ctx(p.woa_deep_o2sat, 1, " %")!} />}
          {p.woa_deep_phosphate != null && <Row label={t("argo.phosphateLabel")} value={ctx(p.woa_deep_phosphate, 2, " µmol/kg")!} />}
          {p.woa_deep_silicate != null && <Row label={t("argo.silicateLabel")} value={ctx(p.woa_deep_silicate, 1, " µmol/kg")!} />}
          {p.woa_deep_nitrate != null && <Row label={t("argo.nitrateLabel")} value={ctx(p.woa_deep_nitrate, 1, " µmol/kg")!} />}
          <BodyText className="text-white/65 text-xs mt-1">{t("argo.woaContextNote")}</BodyText>
        </Section>
      )}
      {(() => {
        const c = latLonFromProps(p);
        if (!c) return null;
        const pm = p.profile_date ? (new Date(String(p.profile_date)).getUTCMonth() + 1) : new Date().getUTCMonth() + 1;
        const month = Number.isFinite(pm) && pm >= 1 && pm <= 12 ? pm : 1;
        const deep = Number(p.deep_pressure_m);
        return <WoaSeasonalExplorer lat={c[0]} lon={c[1]} deepDepth={Number.isFinite(deep) ? deep : 0} profileMonth={month} t={t} />;
      })()}
    </>
  );
}

