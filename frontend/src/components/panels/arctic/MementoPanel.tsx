// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";

import { useMapStore } from "../../../store/mapStore";
import { MEMENTO_PARAM_META, MEMENTO_FIRST_CLASS } from "../../../utils/mementoParams";
import { formatLatLon } from "../../../utils/coords";

import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader, WarningBanner } from "../shared/primitives";

// ── MEMENTO (GEOMAR CH₄/N₂O) panel ──────────────────────────────────────────

interface MementoSample {
  depth_m: number | null;
  sample_time: string | null;
  ch4: number | null;
  n2o: number | null;
  n2o_perc: number | null;
  o2: number | null;
  temp: number | null;
  sal: number | null;
  params: Record<string, unknown>;
  /** Platform-derived, not MEMENTO's. See mementoParams.ts. */
  ch4_is_atmospheric?: boolean | null;
  n2o_is_atmospheric?: boolean | null;
}

interface MementoCastDetail {
  cast_id: number | string;
  set_name: string | null;
  station: string | null;
  sample_time: string | null;
  lat: number;
  lon: number;
  decade: number | null;
  n_samples: number;
  min_depth_m: number | null;
  max_depth_m: number | null;
  has_ch4: boolean;
  has_n2o: boolean;
  ch4_surf: number | null;
  n2o_surf: number | null;
  samples: MementoSample[];
}

/** Atmospheric mole fractions must never be plotted on a nmol/l depth axis.
 *  The flag is per-gas: a row whose CH₄ is atmospheric may still carry good N₂O. */
const isAtmospheric = (s: MementoSample, gas: "ch4" | "n2o") =>
  gas === "ch4" ? s.ch4_is_atmospheric === true : s.n2o_is_atmospheric === true;

function MementoDepthChart({ samples, gas }: { samples: MementoSample[]; gas: "ch4" | "n2o" }) {
  const validCh4 = samples.filter(s => s.ch4 != null && s.ch4 !== -999 && s.depth_m != null && !isAtmospheric(s, "ch4"));
  const validN2o = samples.filter(s => s.n2o != null && s.n2o !== -999 && s.depth_m != null && !isAtmospheric(s, "n2o"));
  const hasCh4 = validCh4.length >= 2;
  const hasN2o = validN2o.length >= 2;
  if (gas === "ch4" ? !hasCh4 : !hasN2o) return null;

  const W = 300, H = 210, PAD_L = 52, PAD_R = 14, PAD_T = 16, PAD_B = 46;
  const drawW = W - PAD_L - PAD_R;
  const drawH = H - PAD_T - PAD_B;

  const activePoints = gas === "ch4" ? validCh4 : validN2o;
  const allDepths = activePoints.map(s => s.depth_m as number);
  const minD = Math.min(...allDepths), maxD = Math.max(...allDepths);
  const rangeD = Math.max(maxD - minD, 1);
  const py = (d: number) => PAD_T + ((d - minD) / rangeD) * drawH;

  const ch4Vals = validCh4.map(s => s.ch4 as number);
  const n2oVals = validN2o.map(s => s.n2o as number);

  const primaryVals = gas === "ch4" ? ch4Vals : n2oVals;
  const minV = Math.min(...primaryVals), maxV = Math.max(...primaryVals);
  const rangeV = Math.max(maxV - minV, 1);
  const px = (v: number, vmin: number, vrange: number) => PAD_L + ((v - vmin) / vrange) * drawW;

  const midD = (minD + maxD) / 2;
  const midV = (minV + maxV) / 2;
  const fmtV = (v: number) => v < 10 ? v.toFixed(1) : Math.round(v).toString();

  const makeLine = (pts: MementoSample[], valFn: (s: MementoSample) => number, vmin: number, vrange: number) =>
    pts.map(s => `${px(valFn(s), vmin, vrange).toFixed(1)},${py(s.depth_m as number).toFixed(1)}`).join(" ");

  const gasLabel = gas === "ch4" ? "CH₄ (nM)" : "N₂O (nM)";

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      className="block bg-black/40 rounded-md mb-3 border border-white/10">
      <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      <line x1={PAD_L} y1={PAD_T + drawH} x2={PAD_L + drawW} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      {[minD, midD, maxD].map((d, i) => {
        const y = py(d);
        return (
          <g key={`d${i}`}>
            <line x1={PAD_L} y1={y} x2={PAD_L + drawW} y2={y} stroke="white" strokeOpacity={0.06} strokeWidth={0.6} />
            <line x1={PAD_L - 4} y1={y} x2={PAD_L} y2={y} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
            <text x={PAD_L - 7} y={y + 3} textAnchor="end" fill="rgba(255,255,255,0.55)" fontSize="9">{Math.round(d)}</text>
          </g>
        );
      })}
      {[minV, midV, maxV].map((v, i) => {
        const x = px(v, minV, rangeV);
        return (
          <g key={`v${i}`}>
            <line x1={x} y1={PAD_T + drawH} x2={x} y2={PAD_T + drawH + 4} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
            <text x={x} y={PAD_T + drawH + 14} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize="9">{fmtV(v)}</text>
          </g>
        );
      })}
      <text transform={`translate(11 ${PAD_T + drawH / 2}) rotate(-90)`} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="10">Depth (m)</text>
      <text x={PAD_L + drawW / 2} y={H - 6} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="10">{gasLabel}</text>
      {hasCh4 && gas === "ch4" && (
        <>
          <polyline points={makeLine(validCh4, s => s.ch4 as number, minV, rangeV)} fill="none" stroke="rgb(45 212 191)" strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
          {validCh4.map((s, i) => <circle key={`c${i}`} cx={px(s.ch4 as number, minV, rangeV)} cy={py(s.depth_m as number)} r={2} fill="rgb(45 212 191)" />)}
        </>
      )}
      {hasN2o && gas === "n2o" && (
        <>
          <polyline points={makeLine(validN2o, s => s.n2o as number, minV, rangeV)} fill="none" stroke="rgb(232 121 249)" strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
          {validN2o.map((s, i) => <circle key={`n${i}`} cx={px(s.n2o as number, minV, rangeV)} cy={py(s.depth_m as number)} r={2} fill="rgb(232 121 249)" />)}
        </>
      )}
    </svg>
  );
}

/** One gas cell in the MEMENTO samples table. Atmospheric values stay visible —
 *  muted and badged "air" — because they are real measurements of a different
 *  quantity (ppb mole fraction), not bad data. */
function GasCell({ value, atmospheric, className }: {
  value: number | null; atmospheric?: boolean | null; className: string;
}) {
  const txt = value == null || value === -999 ? "—" : value.toFixed(2);
  if (!atmospheric) return <td className={className}>{txt}</td>;
  return (
    <td className={className} title="Atmospheric mole fraction (ppb), not dissolved gas">
      <span className="text-white/40">{txt}</span>
      <span className="ml-1 text-[9px] text-amber-300/80">air</span>
    </td>
  );
}

export function MementoPanel({ id }: { id: number | string }) {
  const [data, setData]       = useState<MementoCastDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const mementoGas            = useMapStore(s => s.mementoGas);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v2/spatial/memento/by-id/${id}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [id]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const dateStr = data.sample_time ? String(data.sample_time).slice(0, 10) : null;
  const samples = data.samples ?? [];
  const isSingle = data.n_samples === 1 || samples.length <= 1;

  const fmtVal = (v: number | null) =>
    v == null || v === -999 ? "—" : v.toFixed(2);

  return (
    <>
      <WarningBanner color="orange">
        Platform-derived classification. MEMENTO publishes dissolved and atmospheric gas under the same column name (CH₄ is both Methane_Ocean [nmol/l] and Methane_Atmosphere [ppb]) and its CSV export omits the distinction. Where the contributor did not label a sample <span className="font-mono">_Air</span>, we inferred which values are atmospheric from the cruise median; those are marked “air”. The underlying values are unmodified, and every value — including flagged ones — is available in Area Export.
        {" "}If you intend to publish data from this cast, MEMENTO’s terms of use ask you to cite the database as: Kock, A. and Bange, H. W. (2015) Counting the ocean’s greenhouse gas emissions, Eos 96(3), 10–13, doi:10.1029/2015EO023665 — to include their acknowledgement statement, to also cite the original publications if you use fewer than 10 individual data submissions, and to contact the contributing scientist for permission to use any unpublished data.
      </WarningBanner>

      <Badge label="MEMENTO" color="text-teal-300 border-teal-500/40" />
      <PanelHeader>{data.set_name ?? `Cast ${data.cast_id}`}</PanelHeader>

      {!isSingle && <MementoDepthChart samples={samples} gas={mementoGas} />}

      {isSingle && samples.length > 0 && (
        <Section title={samples[0].ch4_is_atmospheric ? "Atmospheric sample" : "Surface / underway sample"}>
          <Row label={samples[0].ch4_is_atmospheric ? "CH₄ (air)" : "CH₄"}
               value={samples[0].ch4 == null || samples[0].ch4 === -999 ? "—"
                      : `${fmtVal(samples[0].ch4)} ${samples[0].ch4_is_atmospheric ? "ppb" : "nmol/l"}`} />
          <Row label={samples[0].n2o_is_atmospheric ? "N₂O (air)" : "N₂O"}
               value={samples[0].n2o == null || samples[0].n2o === -999 ? "—"
                      : `${fmtVal(samples[0].n2o)} ${samples[0].n2o_is_atmospheric ? "ppb" : "nmol/l"}`} />
          {samples[0].n2o_perc != null && samples[0].n2o_perc !== -999 && (
            <Row label="N₂O sat." value={`${fmtVal(samples[0].n2o_perc)} %`} />
          )}
          {samples[0].o2   != null && samples[0].o2   !== -999 && <Row label="O₂"   value={fmtVal(samples[0].o2)} />}
          {samples[0].temp != null && samples[0].temp !== -999 && <Row label="Temp"  value={`${fmtVal(samples[0].temp)} °C`} />}
          {samples[0].sal  != null && samples[0].sal  !== -999 && <Row label="Sal."  value={fmtVal(samples[0].sal)} />}
        </Section>
      )}

      {!isSingle && samples.length > 0 && (
        <Section title={`Samples (${samples.length})`}>
          <div className="max-h-44 overflow-y-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/70 text-white/70">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Depth (m)</th>
                  <th className="text-right px-2 py-1 font-normal">CH₄</th>
                  <th className="text-right px-2 py-1 font-normal">N₂O</th>
                  <th className="text-right px-2 py-1 font-normal">O₂</th>
                  <th className="text-right px-2 py-1 font-normal">T (°C)</th>
                  <th className="text-right px-2 py-1 font-normal">Sal.</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s, i) => (
                  <tr key={i} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{s.depth_m ?? "—"}</td>
                    <GasCell value={s.ch4} atmospheric={s.ch4_is_atmospheric}
                             className="px-2 py-0.5 text-right text-teal-300" />
                    <GasCell value={s.n2o} atmospheric={s.n2o_is_atmospheric}
                             className="px-2 py-0.5 text-right text-fuchsia-300" />
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.o2)}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.temp)}</td>
                    <td className="px-2 py-0.5 text-right text-white/75">{fmtVal(s.sal)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {(() => {
        // Union of every non-first-class param present on any sample of this cast,
        // rendered in registry order. `nh4` exists on 0.2% of samples, so absent
        // params are omitted rather than shown as "—".
        const present = new Set<string>();
        for (const s of samples) {
          for (const p of MEMENTO_PARAM_META) {
            if (MEMENTO_FIRST_CLASS.has(p.key)) continue;
            const v = s.params?.[p.key];
            if (typeof v === "number" && v !== -999) present.add(p.key);
          }
        }
        if (present.size === 0) return null;
        const shallow = samples[0];
        return (
          <Section title="Other measured parameters">
            {MEMENTO_PARAM_META.filter(p => present.has(p.key)).map(p => {
              const v = shallow?.params?.[p.key];
              const txt = typeof v === "number" && v !== -999 ? `${v.toFixed(2)} ${p.unit}` : "—";
              return <Row key={p.key} label={p.label} value={txt} />;
            })}
            <p className="mt-2 text-[10px] leading-snug text-white/45">
              Values shown for the shallowest sample. Some rows are the same measurement
              expressed in different units (e.g. Methane in nmol/l, nmol/kg and nl/l).
            </p>
          </Section>
        );
      })()}

      <Section title="Cast details">
        {data.set_name    != null && <Row label="Cruise / set" value={String(data.set_name)} />}
        {data.station     != null && <Row label="Station"      value={String(data.station)} />}
        {dateStr          != null && <Row label="Date"         value={dateStr} />}
        {data.decade      != null && <Row label="Decade"       value={`${data.decade}s`} />}
        {/* 47 casts store lon on a 0-360 axis; the map wraps them, the column doesn't. */}
        <Row label="Lat / Lon"   value={formatLatLon(data.lat, data.lon)} />
        <Row label="Samples"     value={String(data.n_samples)} />
        {(data.min_depth_m != null || data.max_depth_m != null) && (
          <Row label="Depth range" value={`${data.min_depth_m ?? "?"} – ${data.max_depth_m ?? "?"} m`} />
        )}
        {data.has_ch4 && <Row label="Has CH₄" value="yes" />}
        {data.has_n2o && <Row label="Has N₂O" value="yes" />}
      </Section>

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a href="https://portal.geomar.de/memento" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          GEOMAR MEMENTO portal ↗
        </a>
        <span className="block text-white/60 mt-0.5">
          Database citation (per MEMENTO’s terms of use): Kock &amp; Bange (2015) Eos 96(3), 10–13,{" "}
          <a href="https://doi.org/10.1029/2015EO023665" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
            doi:10.1029/2015EO023665
          </a>
        </span>
        <span className="block text-white/50 mt-0.5">
          {"Required acknowledgement: “The MEMENTO database is administered by the Kiel Data Management Team at GEOMAR Helmholtz Centre for Ocean Research and supported by the German BMBF project SOPRAN (Surface Ocean Processes in the Anthropocene, http://sopran.pangaea.de). The database is accessible through the MEMENTO webpage: https://memento.geomar.de.”"}
        </span>
        <span className="block text-white/50 mt-0.5">
          Project paper: Bange et al. (2009) Environ. Chem.,{" "}
          <a href="https://doi.org/10.1071/en09033" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
            doi:10.1071/en09033
          </a>
        </span>
      </p>
    </>
  );
}
