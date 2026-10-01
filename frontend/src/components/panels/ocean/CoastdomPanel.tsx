// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { Row, Section, PanelHeader, HintText } from "../shared/primitives";
import { usePangaeaWaterMeta } from "../shared/usePangaeaWaterMeta";
import { PangaeaCitationBlock } from "../shared/PangaeaCitationBlock";
import { useMapStore } from "../../../store/mapStore";
import { effectiveCoastdomRange, filterSamplesByYear } from "../../../utils/coastdomYearFilter";

/**
 * One CoastDOM position: EVERY sample the source holds there, by date then depth.
 *
 * ⛔ Nothing is averaged. A position can hold up to 1,415 samples over 44 years;
 * each is listed with its own quality flag, method and references. Labels are
 * the source's own header strings (meta `units`), e.g. "DOC [µmol/l]".
 * ⛔ An undated sample prints "no date in source" — never a substituted date.
 */
type Sample = Record<string, string | number | null>;

/** Value field, its QF field and method field where the source has them. */
const PARAMS: Array<{ value: string; qf?: string; method?: string }> = [
  { value: "doc_umol_l", qf: "qf_doc", method: "doc_method" },
  { value: "don_umol_l" },
  { value: "dop_umol_l" },
  { value: "tdn_umol_l", qf: "qf_tdn", method: "tdn_method" },
  { value: "tdp_umol_l", qf: "qf_tdp", method: "tdp_method" },
  { value: "poc_umol_l", qf: "qf_poc", method: "poc_method" },
  { value: "pn_umol_l", qf: "qf_tpn", method: "pn_method" },
  { value: "pp_umol_l", qf: "qf_pp", method: "pp_method" },
  { value: "dic_umol_kg", qf: "qf_dic" },
  { value: "at_umol_kg", qf: "qf_at" },
  { value: "chl_a_ug_l", qf: "qf_chl_a" },
  { value: "no3_no2_umol_l", qf: "qf_no3_no2" },
  { value: "nh4_umol_l", qf: "qf_nh4" },
  { value: "hpo4_umol_l", qf: "qf_hpo4" },
  { value: "tss_mg_l" },
  { value: "temp_c" },
  { value: "sal" },
  { value: "elevation_m" },
];

export function CoastdomPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "common"]);
  const lat = typeof properties.lat === "number" ? properties.lat : null;
  const lon = typeof properties.lon === "number" ? properties.lon : null;
  const meta = usePangaeaWaterMeta("coastdom");
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (lat == null || lon == null) return;
    let cancelled = false;
    setSamples(null);
    setFailed(false);
    fetch(`${API}/api/v1/map/coastdom/samples?lat=${encodeURIComponent(String(lat))}&lon=${encodeURIComponent(String(lon))}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (!cancelled) setSamples(Array.isArray(d?.samples) ? d.samples : []); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [lat, lon]);

  // Same effective range as the map (null = not narrowed -> panel unchanged).
  const storedRange = useMapStore((s) => s.coastdomYearRange);
  const bounds = useMapStore((s) => s.coastdomYearBounds);
  const range = effectiveCoastdomRange(storedRange, bounds);
  const shown = samples && filterSamplesByYear(samples, range);

  const units = meta?.units ?? {};
  const label = (field: string) => units[field] ?? field;

  return (
    <div>
      <PanelHeader>{String(properties.location ?? t("pangaeaWater.unnamedLocation"))}</PanelHeader>
      <HintText>{t("pangaeaWater.samplesHere", { count: Number(properties.n_samples ?? samples?.length ?? 0) })}</HintText>
      {range && shown && samples && (
        <HintText>
          {t("pangaeaWater.samplesInRange", {
            inRange: shown.length, total: samples.length, from: range[0], to: range[1],
          })}
        </HintText>
      )}
      {failed && <HintText>{t("pangaeaWater.loadFailed")}</HintText>}
      {!failed && samples === null && <HintText>{t("pangaeaWater.loading")}</HintText>}
      {shown?.map((s) => (
        <Section
          key={String(s.row_no)}
          title={`${s.sample_date != null ? String(s.sample_date) : t("pangaeaWater.noDateInSource")} · ${label("depth_m")}: ${s.depth_m ?? "—"}`}
        >
          {s.sample_id != null && <Row label={t("pangaeaWater.sampleId")} value={String(s.sample_id)} />}
          {PARAMS.filter((p) => s[p.value] != null || (p.qf != null && s[p.qf] != null)).map((p) => (
            <Row
              key={p.value}
              label={label(p.value)}
              value={
                <>
                  {s[p.value] ?? "—"}
                  {p.qf && s[p.qf] != null ? ` · ${label(p.qf)} ${s[p.qf]}` : ""}
                  {p.method && s[p.method] != null ? ` · ${String(s[p.method])}` : ""}
                </>
              }
            />
          ))}
          {(["ref_1", "ref_2", "ref_3"] as const).filter((k) => s[k] != null).map((k) => (
            <Row key={k} label={t("pangaeaWater.reference")} value={String(s[k])} />
          ))}
          {s.comment != null && <Row label={t("pangaeaWater.comment")} value={String(s.comment)} />}
          {s.pi != null && <Row label={t("pangaeaWater.pi")} value={`${s.pi}${s.institution ? ` — ${s.institution}` : ""}`} />}
        </Section>
      ))}
      <PangaeaCitationBlock version={meta} doiFallback="10.1594/PANGAEA.964012" />
    </div>
  );
}
