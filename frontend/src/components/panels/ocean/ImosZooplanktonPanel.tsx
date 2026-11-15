// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one IMOS zooplankton sample (`/api/v1/imos-zooplankton/sample/{sample_key}`,
 * backend/domains/imos_zooplankton.py).
 * ⛔ Three kinds of taxon, never merged: PRESENT (abundance above zero), ABSENT (counted, abundance 0) and NOT
 *    LISTED (the source gave null or does not list it). For the NRS non-copepod group the source lists present taxa
 *    only (`noncopepod_zeros_explicit` = false), so there an unlisted taxon is unknown, never zero.
 * ⛔ Missing and broken never share a state: 404 = the sample is not in the current import, anything else =
 *    unavailable, with a retry. Never a blank panel.
 * ⛔ Names are rendered as React text (never as HTML).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "../shared/tokens";
import { PanelHeader, Row, Section } from "../shared/primitives";

interface Taxon { taxon: string; is_copepod: boolean; abundance_m3: number }
export interface ImosSample {
  sample: {
    sample_key: string; programme: "auscpr" | "nrs"; trip_code: string | null; region: string | null;
    station_code: string | null; station_name: string | null; lat: number; lon: number;
    sample_time_utc: string | null; sample_depth_m: number | null; sample_volume_m3: number | null;
    biomass_mgm3: number | null; copepod_total_m3: number | null; n_copepod_taxa_present: number | null;
    noncopepod_zeros_explicit: boolean; snapshot: string;
  };
  taxa: Taxon[];
  licence: string; licence_url: string; attribution: string; attribution_cpr: string;
}

export function imosSampleUrl(sampleKey: string): string {
  return `${API}/api/v1/imos-zooplankton/sample/${encodeURIComponent(sampleKey)}`;
}

const nf = (n: number) =>
  n === 0 ? "0" : n >= 100 ? Math.round(n).toLocaleString("en-US") : n >= 1 ? n.toFixed(1) : n.toPrecision(2);

function TaxonList({ rows }: { rows: Taxon[] }) {
  return (
    <ul className="text-xs text-white/85">
      {rows.map((r) => (
        <li key={`${r.is_copepod}:${r.taxon}`} className="flex justify-between gap-3">
          <i>{r.taxon}</i><span className="font-mono text-white/90">{nf(r.abundance_m3)}</span>
        </li>
      ))}
    </ul>
  );
}

export function ImosZooplanktonPanel({ sampleKey }: { sampleKey: string }) {
  const { t } = useTranslation("panels");
  const [data, setData] = useState<ImosSample | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "error" | "ok">("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState("loading");
    setData(null);
    fetch(imosSampleUrl(sampleKey), { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 422 and 503 + Retry-After land here too
        return r.json();
      })
      .then((j) => { if (j) { setData(j as ImosSample); setState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setState("error"); });
    return () => ctrl.abort();
  }, [sampleKey, attempt]);

  if (state === "loading") return <p className="text-white/60 text-xs animate-pulse">{t("imosZooplankton.loading")}</p>;
  if (state === "missing") return <p className="text-white/70 text-sm" role="status">{t("imosZooplankton.missing")}</p>;
  if (state === "error" || !data) {
    return (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("imosZooplankton.error")}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}
          className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
          {t("imosZooplankton.retry")}
        </button>
      </div>
    );
  }

  const s = data.sample;
  const cop = data.taxa.filter((x) => x.is_copepod);
  const non = data.taxa.filter((x) => !x.is_copepod);
  const copPresent = cop.filter((x) => x.abundance_m3 > 0);
  const nonPresent = non.filter((x) => x.abundance_m3 > 0);
  const nonAbsent = non.length - nonPresent.length;
  const where = s.programme === "auscpr" ? s.region : [s.station_name, s.station_code].filter(Boolean).join(" · ");
  const when = s.sample_time_utc ? s.sample_time_utc.replace("T", " ").slice(0, 16) + " UTC" : t("imosZooplankton.noDate");

  return (
    <div data-testid="imos-zooplankton-panel">
      <PanelHeader>{t(s.programme === "auscpr" ? "imosZooplankton.titleCpr" : "imosZooplankton.titleNrs")}</PanelHeader>
      {where && <p className="text-white/80 text-xs mb-1">{where}</p>}
      <p className="text-white/70 text-xs font-mono mb-2">{`${Number(s.lat).toFixed(4)}, ${Number(s.lon).toFixed(4)}`}</p>
      <Row label={t("imosZooplankton.time")} value={when} />
      {s.sample_depth_m !== null && <Row label={t("imosZooplankton.depth")} value={`${nf(s.sample_depth_m)} m`} />}
      {s.sample_volume_m3 !== null && <Row label={t("imosZooplankton.volume")} value={`${nf(s.sample_volume_m3)} m³`} />}
      {s.biomass_mgm3 !== null && (
        <Row label={t(s.programme === "auscpr" ? "imosZooplankton.biomassIndex" : "imosZooplankton.biomass")}
          value={`${nf(s.biomass_mgm3)} mg/m³`} />
      )}
      <Row label={t("imosZooplankton.copepodTotal")}
        value={s.copepod_total_m3 === null ? t("imosZooplankton.notCounted") : `${nf(s.copepod_total_m3)} /m³`} />

      <Section title={t("imosZooplankton.copepods", { n: copPresent.length })}>
        {copPresent.length > 0 ? <TaxonList rows={copPresent} /> : (
          <p className="text-xs text-white/70">{t("imosZooplankton.noneFound")}</p>
        )}
        <p className="text-[11px] text-white/60 mt-1">
          {t("imosZooplankton.absentCounted", { n: cop.length - copPresent.length })}
        </p>
      </Section>
      <Section title={t("imosZooplankton.nonCopepods", { n: nonPresent.length })}>
        {nonPresent.length > 0 ? <TaxonList rows={nonPresent} /> : (
          <p className="text-xs text-white/70">{t("imosZooplankton.noneListed")}</p>
        )}
        <p className="text-[11px] text-white/60 mt-1">
          {s.noncopepod_zeros_explicit
            ? t("imosZooplankton.absentCounted", { n: nonAbsent })
            : t("imosZooplankton.absencesNotRecorded")}
        </p>
      </Section>
      <p className="text-[11px] text-white/60 mt-2">{t("imosZooplankton.unitNote")}</p>
      <p className="text-[11px] text-white/60 mt-1">
        {data.attribution}{s.programme === "auscpr" ? ` ${data.attribution_cpr}` : ""}{" "}
        <a href={data.licence_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
          {data.licence}
        </a>
      </p>
    </div>
  );
}
