// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";

import { useMapStore } from "../../../store/mapStore";
import { MOSAIC_VARS, mosaicVarHex } from "../../../utils/mosaicVars";
import type { MosaicVarKey } from "../../../utils/mosaicVars";

import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader, WarningBanner } from "../shared/primitives";
import { SampleDate } from "../shared/SampleDate";

interface MosaicProvenanceEntry {
  doi?: string | null;
  title?: string | null;
  method?: string | null;
}

interface MosaicSample {
  sample_id: number;
  depth_upper_cm: number | null;
  depth_bottom_cm: number | null;
  depth_avg_cm: number | null;
  material_analyzed: string | null;
  replicate: number | null;
  toc: number | null;
  tn: number | null;
  d13c: number | null;
  d14c: number | null;
  fm14c: number | null;
  provenance: Record<string, MosaicProvenanceEntry> | null;
}

interface MosaicCoreDetail {
  core_id: number;
  core_name: string | null;
  latitude: number;
  longitude: number;
  water_depth_m: number | null;
  sampling_year: number | null;
  decade: number | null;
  sampling_method: string | null;
  research_vessel: string | null;
  seas: string | null;
  eez: string | null;
  longhurst: string | null;
  has_toc: boolean;
  has_tn: boolean;
  has_d13c: boolean;
  has_d14c: boolean;
  toc_surf: number | null;
  tn_surf: number | null;
  d13c_surf: number | null;
  d14c_surf: number | null;
  sampling_date: string | null;
  sampling_month: number | null;
  sampling_day: number | null;
  campaign_name: string | null;
  campaign_start: string | null;
  campaign_end: string | null;
  core_comment: string | null;
  date_precision: "day" | "month" | "year" | "campaign" | "none" | null;
}

interface MosaicResponse {
  core: MosaicCoreDetail;
  samples: MosaicSample[];
}

function MosaicDepthChart({
  samples,
  variable,
  unit,
  color,
}: {
  samples: MosaicSample[];
  variable: MosaicVarKey;
  unit: string;
  color: string;
}) {
  const valid = samples.filter(s => s[variable] != null && s.depth_avg_cm != null) as (MosaicSample & { depth_avg_cm: number })[];
  if (valid.length < 1) return null;

  const W = 300, H = 210, PAD_L = 52, PAD_R = 14, PAD_T = 16, PAD_B = 46;
  const drawW = W - PAD_L - PAD_R;
  const drawH = H - PAD_T - PAD_B;

  const allDepths = valid.map(s => s.depth_avg_cm);
  const minD = Math.min(...allDepths), maxD = Math.max(...allDepths);
  const rangeD = Math.max(maxD - minD, 1);
  const py = (d: number) => PAD_T + ((d - minD) / rangeD) * drawH;

  const vals = valid.map(s => s[variable] as number);
  const minV = Math.min(...vals), maxV = Math.max(...vals);
  const rangeV = Math.max(maxV - minV, 1);
  const px = (v: number) => PAD_L + ((v - minV) / rangeV) * drawW;

  const midD = (minD + maxD) / 2;
  const midV = (minV + maxV) / 2;
  const fmtV = (v: number) => Math.abs(v) < 10 ? v.toFixed(2) : Math.round(v).toString();

  const linePts = valid.map(s => `${px(s[variable] as number).toFixed(1)},${py(s.depth_avg_cm).toFixed(1)}`).join(" ");

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      className="block bg-black/40 rounded-md mb-3 border border-white/10">
      <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      <line x1={PAD_L} y1={PAD_T + drawH} x2={PAD_L + drawW} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      {/* depth axis labels (depth_avg_cm) */}
      <text x={PAD_L - 4} y={PAD_T + 4}       textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{minD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH / 2 + 3} textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{midD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH + 2}  textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{maxD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH + 14} textAnchor="end" fontSize={9} fill="white" fillOpacity={0.4}>cm</text>
      {/* value axis labels */}
      <text x={PAD_L}            y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(minV)}</text>
      <text x={PAD_L + drawW / 2} y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(midV)}</text>
      <text x={PAD_L + drawW}     y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(maxV)}</text>
      {/* axis label */}
      <text x={PAD_L + drawW / 2} y={PAD_T + drawH + 28} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.55}>{unit}</text>
      {valid.length >= 2 && (
        <polyline points={linePts} fill="none" stroke={color} strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
      )}
      {valid.map((s, i) => (
        <circle key={i} cx={px(s[variable] as number)} cy={py(s.depth_avg_cm)} r={2} fill={color} />
      ))}
    </svg>
  );
}

export function MosaicPanel({ coreId }: { coreId: number | string }) {
  const [data, setData]   = useState<MosaicResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const mosaicVariable = useMapStore(s => s.mosaicVariable);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v2/spatial/mosaic/by-id/${coreId}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [coreId]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const { core, samples } = data;
  const varInfo  = MOSAIC_VARS.find(v => v.key === mosaicVariable) ?? MOSAIC_VARS[0];
  const varColor = mosaicVarHex(varInfo.key);

  // Distinct source DOIs across this core's samples, credited per variable
  // (provenance is per-value: e.g. TOC and Δ14C on the same sample can come
  // from two different publications).
  const doiMap = new Map<string, { title: string | null; vars: Set<string> }>();
  for (const s of samples) {
    if (!s.provenance) continue;
    for (const [vkey, prov] of Object.entries(s.provenance)) {
      if (!prov?.doi) continue;
      const existing = doiMap.get(prov.doi);
      if (existing) existing.vars.add(vkey);
      else doiMap.set(prov.doi, { title: prov.title ?? null, vars: new Set([vkey]) });
    }
  }

  const fmtVal = (v: number | null) => v == null ? "—" : Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1);

  return (
    <>
      <WarningBanner color="orange">
        Literature-compiled database — each value links to its source publication. Radiocarbon (Δ¹⁴C) coverage is sparse.
      </WarningBanner>

      <Badge label="MOSAIC" color="text-emerald-300 border-emerald-500/40" />
      <PanelHeader>{core.core_name ?? `Core ${core.core_id}`}</PanelHeader>

      <MosaicDepthChart samples={samples} variable={varInfo.key} unit={varInfo.unit} color={varColor} />

      {samples.length === 0 ? (
        // ⛔ Not a bare `&&`. A core whose sample fetch failed and a core the
        // source genuinely holds no sections for rendered identically —
        // nothing at all — so "we could not load them" read as "there are
        // none". Check 24e; the same rule as the ONC drifters.
        <Section title="Samples">
          <p className="text-white/50 text-[11px]">
            No sections recorded for this core in MOSAIC.
          </p>
        </Section>
      ) : (
        <Section title={`Samples (${samples.length})`}>
          <div className="max-h-44 overflow-y-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/80">
                <tr>
                  <th className="px-2 py-0.5 text-left text-white/50 font-normal">Depth (cm)</th>
                  <th className="px-2 py-0.5 text-left text-white/50 font-normal">Material</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">TOC (%)</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">TN (%)</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">δ¹³C (‰)</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Δ¹⁴C (‰)</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s, i) => (
                  <tr key={i} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">
                      {s.depth_upper_cm ?? "?"}–{s.depth_bottom_cm ?? "?"}
                    </td>
                    <td className="px-2 py-0.5 text-white/70">{s.material_analyzed ?? "—"}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.toc)}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.tn)}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.d13c)}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.d14c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Core details">
        <Row label="Lat / Lon" value={`${core.latitude.toFixed(4)}°, ${core.longitude.toFixed(4)}°`} />
        {core.water_depth_m   != null && <Row label="Water depth"    value={`${core.water_depth_m} m`} />}
        <Row label="Sampled" value={
          <SampleDate
            precision={core.date_precision ?? null}
            year={core.sampling_year} month={core.sampling_month} day={core.sampling_day}
            campaignStart={core.campaign_start} campaignEnd={core.campaign_end}
            campaignName={core.campaign_name} comment={core.core_comment}
          />
        } />
        {/* ⛔ These four were SELECTed by the endpoint, typed in the interface
            above, and never rendered — 70.2% / 65.8% / 27.5% / 22.0% populated
            on the live table. We pay to fetch and store them and then hide
            them, which check 24d calls the cheapest defect on the list.
            Units match the Samples table headers above; `_surf` is the
            shallowest section, not a core average, and says so. */}
        {core.decade          != null && <Row label="Decade"          value={`${core.decade}s`} />}
        {core.toc_surf        != null && <Row label="TOC, surface"    value={`${core.toc_surf} %`} />}
        {core.tn_surf         != null && <Row label="TN, surface"     value={`${core.tn_surf} %`} />}
        {core.d13c_surf       != null && <Row label="δ¹³C, surface"   value={`${core.d13c_surf} ‰`} />}
        {core.sampling_method != null && <Row label="Method"         value={core.sampling_method} />}
        {core.research_vessel != null && <Row label="Vessel"         value={core.research_vessel} />}
        {core.seas            != null && <Row label="Sea"            value={core.seas} />}
        {core.eez             != null && <Row label="EEZ"            value={core.eez} />}
        {core.longhurst       != null && <Row label="Longhurst province" value={core.longhurst} />}
      </Section>

      {doiMap.size > 0 && (
        <Section title="Sources">
          <div className="flex flex-col gap-1 text-[11px]">
            {Array.from(doiMap.entries()).map(([doi, info]) => (
              <a
                key={doi}
                href={`https://doi.org/${doi}`}
                target="_blank"
                rel="noopener noreferrer"
                title={info.title ?? doi}
                className="text-teal-400 hover:underline truncate"
              >
                {Array.from(info.vars).join(", ")}: {info.title ?? doi} ↗
              </a>
            ))}
          </div>
        </Section>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Van der Voort et al. 2021, ESSD 13:2135 · MOSAIC DOI{" "}
        <a href="https://doi.org/10.5168/mosaic019.1" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          10.5168/mosaic019.1 ↗
        </a>
        {" · "}CC-BY 4.0
      </p>
    </>
  );
}
