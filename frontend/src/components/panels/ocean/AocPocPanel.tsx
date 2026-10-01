// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { Row, Section, PanelHeader, HintText } from "../shared/primitives";
import { useAoc2025PocMeta } from "../shared/useAoc2025PocMeta";

/**
 * One AOC2025 station, every sample there ordered by nominal depth/pressure
 * (SDN:P01::PRESPR01). Row labels carry short units
 * only (i18n) — the backend meta endpoint's units carry full provenance text
 * for API consumers and are deliberately NOT used for these labels; see the
 * footnotes below the samples and backend/ingestion/aoc2025_poc.py for the
 * full unit provenance.
 */
type Sample = Record<string, string | number | null>;

const FIELDS: Array<{ value: string; labelKey: string }> = [
  { value: "prespr01_db", labelKey: "aocPoc.depth" },
  { value: "pressure_db", labelKey: "aocPoc.pressure" },
  { value: "temp_c", labelKey: "aocPoc.temperature" },
  { value: "salinity", labelKey: "aocPoc.salinity" },
  { value: "d13c_permil", labelKey: "aocPoc.d13c" },
  { value: "d15n_permil", labelKey: "aocPoc.d15n" },
  { value: "poc_mg_dm3", labelKey: "aocPoc.poc" },
  { value: "pn_mg_dm3", labelKey: "aocPoc.pn" },
];

/** Renders any parseable timestamp (any offset) as its UTC wall-clock time,
 * e.g. "2025-05-21T15:25:00+02:00" -> "2025-05-21 13:25 UTC". Never the
 * browser's local zone — uses UTC getters, never toLocale*. */
function formatUtc(v: unknown): string {
  if (v == null) return "—";
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return String(v);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} `
    + `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

export function AocPocPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "common"]);
  const station = typeof properties.station === "string" ? properties.station : null;
  const meta = useAoc2025PocMeta();
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!station) return;
    let cancelled = false;
    setSamples(null);
    setFailed(false);
    fetch(`${API}/api/v1/map/aoc2025-poc/samples?station=${encodeURIComponent(station)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (!cancelled) setSamples(Array.isArray(d?.samples) ? d.samples : []); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [station]);

  const obsWindow = [properties.date_min, properties.date_max].filter((v) => v != null);

  return (
    <div>
      <PanelHeader>{station ?? ""}</PanelHeader>
      <HintText>{t("aocPoc.dataKind")}</HintText>
      {obsWindow.length > 0 && (
        <HintText>{t("aocPoc.window")}: {obsWindow.map((v) => formatUtc(v)).join(" – ")}</HintText>
      )}
      {failed && <HintText>{t("aocPoc.loadFailed")}</HintText>}
      {!failed && samples === null && <HintText>{t("aocPoc.loading")}</HintText>}
      {samples?.map((s) => (
        <Section
          key={String(s.row_no)}
          title={`${s.sample_id ?? "—"} · ${formatUtc(s.sample_date)}`}
        >
          {FIELDS.filter((f) => s[f.value] != null).map((f) => (
            <Row key={f.value} label={t(f.labelKey as any)} value={s[f.value] ?? "—"} />
          ))}
        </Section>
      ))}
      <HintText>{t("aocPoc.unitNote")}</HintText>
      <HintText>{t("aocPoc.p01Note")}</HintText>
      <HintText>{t("aocPoc.metadataDiscrepancy")}</HintText>
      <Section title={t("aocPoc.citation")}>
        {meta?.citation && <HintText>{meta.citation}</HintText>}
        <Row label="DOI" value={
          <a href={`https://doi.org/${meta?.doi ?? "10.48457/IOPAN.2026.571"}`} target="_blank" rel="noopener noreferrer" className="text-cyan-400">
            {meta?.doi ?? "10.48457/IOPAN.2026.571"}
          </a>
        } />
        <Row label={t("aocPoc.licence")} value={meta?.license ?? "CC-BY 4.0"} />
      </Section>
    </div>
  );
}
