// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { Row, Section, PanelHeader, HintText, WarningBanner, InfoHint } from "../shared/primitives";
import { useSvalbardFjordsPpMeta } from "../shared/useSvalbardFjordsPpMeta";

/**
 * One Svalbard Fjords Primary Production position, every exposition (station
 * visit) there, each with its depth-ordered samples.
 * Dates are DATE-only (no time component) — rendered as the ISO string the
 * backend gives, never through new Date()+toLocale* (that reads a bare date
 * as UTC midnight and shifts a day west of Greenwich for anyone east of it).
 * See backend/ingestion/svalbard_fjords_pp.py for the full unit provenance.
 */
interface Sample {
  depth_m: number | null;
  temperature_degc: number | null;
  salinity: number | null;
  ca_mg_m3: number | null;
  pe_mgc_m3_h: number | null;
  water_mass: string | null;
}
interface Exposition {
  exposition_no: string;
  date: string | null;
  fjord_part: string | null;
  pi_mgc_m2_day: number | null;
  samples: Sample[];
}
interface SamplesResponse {
  position_id: string;
  station: string;
  region_code: string;
  region_name: string;
  expositions: Exposition[];
}

const REGION_NAMES: Record<string, string> = { K: "Kongsfjorden", H: "Hornsund" };

// A real <table>: the browser sizes every column to its longest value across
// all rows, so the header stays aligned and Ca — up to 11 characters in the
// 2019 data, e.g. "0.564099201", against ≤ 5 everywhere else — takes the
// width it needs instead of an equal share. Values never wrap; if a row is
// still too wide, the wrapper scrolls sideways instead of overlapping.
const TH = "py-1 pr-2 font-normal";
const TD = "py-1 pr-2 whitespace-nowrap";

function fmt(v: number | string | null | undefined): string {
  return v === null || v === undefined ? "—" : String(v);
}

export function SvalbardFjordsPpPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "common"]);
  const positionId = typeof properties.position_id === "string" ? properties.position_id : null;
  const station = typeof properties.station === "string" ? properties.station : null;
  const regionCode = typeof properties.region_code === "string" ? properties.region_code : null;
  const fjordPart = typeof properties.fjord_part === "string" ? properties.fjord_part : null;
  // Coordinates as the source wrote them, taken from position_id
  // ("{region}:{station}:{lat}:{lon}"). The click point (_lat/_lon) is where
  // the cursor hit, and it is absent when the panel opens from search or a link.
  const [lat, lon] = positionId ? positionId.split(":").slice(-2) : [];

  const meta = useSvalbardFjordsPpMeta();
  const [data, setData] = useState<SamplesResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!positionId) return;
    let cancelled = false;
    setData(null);
    setFailed(false);
    fetch(`${API}/api/v1/map/svalbard-fjords-pp/samples?position_id=${encodeURIComponent(positionId)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [positionId]);

  const waterMassExpansions = meta?.column_notes.water_mass.expansions ?? {};
  const waterMassAttribution = meta?.column_notes.water_mass.attribution ?? "";

  return (
    <div>
      <WarningBanner color="orange">{meta?.licence ?? t("svalbardFjordsPp.licenceFallback")}</WarningBanner>

      <PanelHeader>{station ?? ""}</PanelHeader>
      <Row label={t("svalbardFjordsPp.fjord")} value={regionCode ? (REGION_NAMES[regionCode] ?? regionCode) : "—"} />
      <Row label={t("svalbardFjordsPp.fjordPart")} value={fjordPart ?? "—"} />
      <Row label={t("svalbardFjordsPp.coordinates")} value={lat && lon ? `${lat}, ${lon}` : "—"} />

      {meta?.discrepancies && meta.discrepancies.length > 0 && (
        <Section title={t("svalbardFjordsPp.discrepancies")}>
          {meta.discrepancies.map((d) => (
            <HintText key={d.key}>
              {d.metadata_says != null
                ? `${t("svalbardFjordsPp.metadataSays")}: ${d.metadata_says} — ${t("svalbardFjordsPp.dataShows")}: ${d.data_shows}`
                : `${t("svalbardFjordsPp.dataShows")}: ${d.data_shows}`}
            </HintText>
          ))}
        </Section>
      )}

      {failed && <HintText>{t("svalbardFjordsPp.loadFailed")}</HintText>}
      {!failed && data === null && <HintText>{t("svalbardFjordsPp.loading")}</HintText>}

      {data?.expositions.map((exp) => (
        <Section key={exp.exposition_no} title={`${exp.date ?? "—"} · ${exp.fjord_part ?? "—"}`}>
          <HintText>
            {exp.pi_mgc_m2_day != null
              ? `${t("svalbardFjordsPp.piLabel")}: ${fmt(exp.pi_mgc_m2_day)} mgC m⁻² d⁻¹`
              : t("svalbardFjordsPp.piNotReported")}
          </HintText>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-white/10 text-[11px] text-white/60 leading-tight align-bottom">
                  <th className={TH}>{t("svalbardFjordsPp.colDepth")}<br />m</th>
                  <th className={TH}>{t("svalbardFjordsPp.colTemperature")}<br />°C</th>
                  <th className={TH}>{t("svalbardFjordsPp.colSalinity")}</th>
                  <th className={TH}>Ca<br />mg m⁻³</th>
                  <th className={TH}>Pe<br />mgC m⁻³ h⁻¹</th>
                  <th className={TH}>{t("svalbardFjordsPp.colWaterMass")}</th>
                </tr>
              </thead>
              <tbody className="text-[13px] text-white/90 tabular-nums">
                {exp.samples.map((s, i) => (
                  <tr key={i} className="border-b border-white/5 last:border-0">
                    <td className={TD}>{fmt(s.depth_m)}</td>
                    <td className={TD}>{fmt(s.temperature_degc)}</td>
                    <td className={TD}>{fmt(s.salinity)}</td>
                    <td className={TD}>{fmt(s.ca_mg_m3)}</td>
                    <td className={TD}>{fmt(s.pe_mgc_m3_h)}</td>
                    <td className={TD} title={s.water_mass ? `${waterMassExpansions[s.water_mass] ?? s.water_mass} (${waterMassAttribution})` : undefined}>
                      {s.water_mass ?? "—"}
                      {s.water_mass && <InfoHint text={`${waterMassExpansions[s.water_mass] ?? s.water_mass} — ${waterMassAttribution}`} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ))}

      <HintText>{t("svalbardFjordsPp.caNote")}</HintText>
      <HintText>{t("svalbardFjordsPp.salinityNote")}</HintText>

      <Section title={t("svalbardFjordsPp.citation")}>
        {meta?.citation && <HintText>{meta.citation}</HintText>}
        <Row label="DOI" value={
          <a href={`https://doi.org/${meta?.doi ?? "10.48457/iopan-2024-198"}`} target="_blank" rel="noopener noreferrer" className="text-cyan-400">
            {meta?.doi ?? "10.48457/iopan-2024-198"}
          </a>
        } />
      </Section>
    </div>
  );
}
