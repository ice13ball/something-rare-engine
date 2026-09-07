// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "./tokens";
import { Row } from "./primitives";

export function QcChip({ qc }: { qc: unknown }) {
  if (qc == null) return null;
  const n = Number(qc);
  if (n !== 3 && n !== 4) return null;
  return (
    <span className="ml-1 px-1 py-0.5 text-[10px] rounded bg-amber-500/20 text-amber-300 font-mono">
      QC {n}
    </span>
  );
}

// Shown next to a value whose pH is outside the physical range of seawater —
// a sensor fault our own plausibility check caught (Argo often ships no QC flag).
export function SensorFaultChip({ label }: { label: string }) {
  return (
    <span className="ml-1 px-1 py-0.5 text-[10px] rounded bg-red-500/20 text-red-300 font-mono">
      {label}
    </span>
  );
}

/**
 * Renders a "Seafloor depth" row from GEBCO bathymetry for the given (lat, lon).
 * Renders nothing while loading, on lookup failure, or for land coordinates
 * (depth >= 0) — caller can drop it into any sea-feature panel safely.
 *
 * Backed by /v1/bathymetry/lookup, which proxies Open-Topo-Data's gebco2020
 * dataset (same GEBCO source as the visual bathymetry layer).
 */
export function SeafloorDepthRow({ lat, lon }: { lat: number; lon: number }) {
  const { t } = useTranslation("common");
  const [depth, setDepth] = useState<number | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API}/api/v1/bathymetry/lookup?lat=${lat}&lon=${lon}`, { signal: ctrl.signal })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d && typeof d.depth_m === "number") setDepth(d.depth_m); })
      .catch(() => { /* swallow — row just won't render */ });
    return () => ctrl.abort();
  }, [lat, lon]);
  if (depth === null || depth >= 0) return null;  // unknown or land
  const meters = Math.abs(Math.round(depth));
  return (
    <Row
      label={t("seafloorDepthLabel", { defaultValue: "Seafloor depth" })}
      value={<span title="GEBCO_2020 bathymetry"><span className="font-mono">{meters.toLocaleString()} m</span> {t("belowSeaLevel", { defaultValue: "below sea level" })}</span>}
    />
  );
}

// ── Bathymetry confidence block ───────────────────────────────────────────────

export function BathymetryConfidenceBlock({ featureType, fid }: { featureType: string; fid: string }) {
  const { t } = useTranslation("panels");
  const [d, setD] = useState<any>(null);
  const [gmrt, setGmrt] = useState<any>(null);
  const [state, setState] = useState<"loading" | "none" | "ok">("loading");
  useEffect(() => {
    let live = true;
    setState("loading");
    setD(null);
    setGmrt(null);
    fetch(`${API}/api/v1/bathymetry/confidence/${featureType}/${encodeURIComponent(fid)}`)
      .then(r => r.status === 204 ? null : r.ok ? r.json() : null)
      .then(j => {
        if (!live) return;
        if (!j) { setState("none"); return; }
        setD(j);
        setState("ok");
      })
      .catch(() => { if (live) setState("none"); });
    fetch(`${API}/api/v1/bathymetry/gmrt/${featureType}/${encodeURIComponent(fid)}`)
      .then(r => r.status === 204 ? null : r.ok ? r.json() : null)
      .then(j => { if (live && j) setGmrt(j); })
      .catch(() => {});
    return () => { live = false; };
  }, [featureType, fid]);
  if (state === "none") return null;
  if (state === "loading") return <p className="text-xs text-white/40 animate-pulse mt-3">{t("bathyConfidence.loading")}</p>;
  const chipColor = d.mapped_confidence === "high" ? "#34d399" : d.mapped_confidence === "low" ? "#f87171" : "#fbbf24";
  return (
    <div className="mt-3 border-t border-white/10 pt-3 flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-white/50">{t("bathyConfidence.title")}</span>
        <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: chipColor + "22", color: chipColor }}>
          {t(`bathyConfidence.rating.${d.mapped_confidence}` as any)}
        </span>
      </div>
      <p className="text-xs text-white/70">{t("bathyConfidence.measured")}: {d.pct_measured?.toFixed(0)}% · {t("bathyConfidence.multibeam")}: {d.pct_multibeam?.toFixed(0)}%</p>
      <p className="text-xs text-white/70">{t("bathyConfidence.predicted")}: {d.pct_indirect?.toFixed(0)}%</p>
      {d.depth_median_m != null && <p className="text-xs text-white/70">{t("bathyConfidence.depth")}: {Math.round(d.depth_min_m)}–{Math.round(d.depth_max_m)} m (med {Math.round(d.depth_median_m)})</p>}
      {d.slope_median_deg != null && <p className="text-xs text-white/70">{t("bathyConfidence.slope")}: {d.slope_median_deg?.toFixed(1)}°</p>}
      {gmrt?.meters_per_node != null && <p className="text-xs text-white/70">{t("bathyConfidence.gmrt")}: {Math.round(gmrt.meters_per_node)} m/node</p>}
      <p className="text-[11px] text-white/40">{t("bathyConfidence.caveat")}</p>
    </div>
  );
}
