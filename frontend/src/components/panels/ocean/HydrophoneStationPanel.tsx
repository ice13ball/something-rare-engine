// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Sparkline } from "../../charts/Sparkline";

import { API } from "../shared/tokens";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, HintText, SourceFooter } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

type SoundscapeRow = {
  day: string;
  broadband_spl_db: number | null;
  spl_10hz_db: number | null;
  spl_63hz_db: number | null;
  spl_100hz_db: number | null;
  spl_125hz_db: number | null;
  spl_1khz_db: number | null;
  spl_10khz_db: number | null;
  l50_db: number | null;
  l95_db: number | null;
  n_minutes_recorded: number | null;
  source_url: string | null;
};

const HYDROPHONE_SOURCE_LABEL: Record<string, string> = {
  ooi:    "OOI",
  imos:   "IMOS",
  mars:   "MBARI MARS",
  palaoa: "AWI PALAOA",
  obsea:  "OBSEA",
  km3net: "KM3NeT",
  nrs:        "NOAA NRS",
  sanctsound: "NOAA SanctSound",
  nefsc:      "NOAA NEFSC",
  // Phase 4 — 12 NOAA Passive Acoustic Archive programs
  pifsc:  "NOAA PIFSC",
  sefsc:  "NOAA SEFSC",
  onms:   "NOAA ONMS",
  adeon:  "ADEON",
  boem:   "BOEM",
  aeon:   "AEON",
  navy:   "US Navy",
  nps:    "National Park Service",
  jasco:  "JASCO",
  fram:   "FRAM",
  coastal_studies_institute: "Coastal Studies Institute",
  ioos:   "IOOS",
  // Phase 3 — PANGAEA/Dryad additions
  sambah: "SAMBAH (Baltic Sea)",
  // HAUSGARTEN uses source='fram' — no separate label entry needed
  // Phase 4 — CTBTO IMS
  ims: "CTBTO IMS (Hydroacoustic)",
};

export function HydrophoneStationPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const stationId = String(p.station_id ?? "");
  const [rows, setRows] = useState<SoundscapeRow[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!stationId) return;
    let cancelled = false;
    setRows(null);
    setError(false);
    fetch(`${API}/api/v1/hydrophones/${encodeURIComponent(stationId)}/soundscape`, {})
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data: SoundscapeRow[]) => { if (!cancelled) setRows(Array.isArray(data) ? data : []); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [stationId]);

  const sourceKey = String(p.source ?? "");
  const isRetired = p.deploy_end != null;
  const depthM = typeof p.depth_m === "number" ? p.depth_m : null;
  const depthBandKey =
    depthM == null ? "" :
    depthM < 200 ? "shallow" :
    depthM <= 2000 ? "slope" : "abyssal";
  const depthBandLabel = depthBandKey ? (t(`hydrophone.${depthBandKey}` as any) as string) : "";

  const sparklineSamples = useMemo(() => {
    if (!rows) return [];
    return rows
      .map((r, i) => (r.broadband_spl_db == null ? null : { t: i, v: r.broadband_spl_db }))
      .filter((s): s is { t: number; v: number } => s !== null);
  }, [rows]);

  const broadbandValues = rows
    ? rows.map((r) => r.broadband_spl_db).filter((v): v is number => v != null)
    : [];
  const meanBroadband = broadbandValues.length > 0
    ? broadbandValues.reduce((a, b) => a + b, 0) / broadbandValues.length
    : null;
  const latest = rows && rows.length > 0 ? rows[rows.length - 1] : null;

  const activeLabel  = (t("hydrophone.active"  as any) as string) || "Active";
  const retiredLabel = (t("hydrophone.retired" as any) as string) || "Retired";

  return (
    <>
      <div className="flex gap-2 flex-wrap">
        <Badge
          label={HYDROPHONE_SOURCE_LABEL[sourceKey] ?? sourceKey}
          color="text-cyan-300 border-cyan-500/40"
        />
        <Badge
          label={isRetired ? retiredLabel : activeLabel}
          color={isRetired ? "text-slate-300 border-slate-500/40" : "text-emerald-300 border-emerald-500/40"}
        />
      </div>
      <PanelHeader>{String(p.name ?? stationId)}</PanelHeader>

      <Section title={(t("hydrophone.detailsTitle" as any) as string) || "Station details"}>
        {p.operator != null && (
          <Row label={(t("hydrophone.operatorLabel" as any) as string) || "Operator"} value={String(p.operator)} />
        )}
        {depthM != null && (
          <Row
            label={(t("hydrophone.depthLabel" as any) as string) || "Depth"}
            value={`${depthM.toLocaleString()} m${depthBandLabel ? ` (${depthBandLabel})` : ""}`}
          />
        )}
        {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
        {p.model != null && p.model !== "" && (
          <Row label={(t("hydrophone.modelLabel" as any) as string) || "Model"} value={String(p.model)} />
        )}
        {p.hz_range_lo != null && p.hz_range_hi != null && (
          <Row
            label={(t("hydrophone.rangeLabel" as any) as string) || "Frequency range"}
            value={`${Number(p.hz_range_lo).toLocaleString()} – ${Number(p.hz_range_hi).toLocaleString()} Hz`}
          />
        )}
        {p.deploy_start != null && (
          <Row
            label={(t("hydrophone.deployedLabel" as any) as string) || "Deployed"}
            value={`${String(p.deploy_start).slice(0, 10)}${
              isRetired ? ` → ${String(p.deploy_end).slice(0, 10)}` : ` (${activeLabel})`
            }`}
          />
        )}
        {p.license != null && p.license !== "" && (
          <Row label={(t("hydrophone.licenseLabel" as any) as string) || "License"} value={String(p.license)} />
        )}
      </Section>

      <Section title={(t("hydrophone.soundscapeTitle" as any) as string) || "Soundscape"}>
        {rows === null && !error && (
          <HintText>{(t("hydrophone.loading" as any) as string) || "Loading…"}</HintText>
        )}
        {error && (
          <p className="text-amber-300 text-[14px]">
            {(t("hydrophone.fetchError" as any) as string) || "Could not load soundscape data."}
          </p>
        )}
        {rows !== null && rows.length === 0 && !error && (
          <HintText>
            {(t("hydrophone.noData" as any) as string) ||
              "No soundscape data yet — station registered, monitoring not yet published."}
          </HintText>
        )}
        {rows !== null && rows.length > 0 && (
          <>
            <div className="my-2">
              <Sparkline samples={sparklineSamples} color="#22d3ee" width={260} height={48} />
            </div>
            {meanBroadband != null && (
              <Row
                label={(t("hydrophone.meanBroadband" as any) as string) || "Mean broadband SPL"}
                value={`${meanBroadband.toFixed(1)} dB`}
              />
            )}
            {latest?.spl_10hz_db  != null && <Row label="10 Hz"  value={`${latest.spl_10hz_db.toFixed(1)} dB`} />}
            {latest?.spl_63hz_db  != null && <Row label="63 Hz"  value={`${latest.spl_63hz_db.toFixed(1)} dB`} />}
            {latest?.spl_100hz_db != null && <Row label="100 Hz" value={`${latest.spl_100hz_db.toFixed(1)} dB`} />}
            {latest?.spl_125hz_db != null && <Row label="125 Hz" value={`${latest.spl_125hz_db.toFixed(1)} dB`} />}
            {latest?.spl_1khz_db  != null && <Row label="1 kHz"  value={`${latest.spl_1khz_db.toFixed(1)} dB`} />}
            {latest?.spl_10khz_db != null && <Row label="10 kHz" value={`${latest.spl_10khz_db.toFixed(1)} dB`} />}
            {latest?.l50_db       != null && <Row label="L50"    value={`${latest.l50_db.toFixed(1)} dB`} />}
            {latest?.l95_db       != null && <Row label="L95"    value={`${latest.l95_db.toFixed(1)} dB`} />}
          </>
        )}
        <p className="text-white/65 text-[12px] mt-2 leading-relaxed">
          {(t("hydrophone.dataNoteBody" as any) as string) ||
            "Phase 1 surfaces station registry only. SPL products will populate once published by the operator."}
        </p>
      </Section>

      {p.portal_url != null && p.portal_url !== "" && (
        <SourceFooter>
          <a
            href={String(p.portal_url)}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-white/90"
          >
            {(t("hydrophone.openPortal" as any) as string) || "Open operator portal ↗"}
          </a>
        </SourceFooter>
      )}
    </>
  );
}

