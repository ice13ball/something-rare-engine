// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { isZoneClassification, zoneLabelFor } from "../../../utils/offshoreZones";
import { offshoreSourceLink } from "../../../utils/sourceUrl";
import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow, BathymetryConfidenceBlock } from "../shared/chips";
import { PolygonThumbnail } from "./PolygonThumbnail";

export function OffshoreActivityPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const type = String(p.activity_type ?? "");
  const status = String(p.status ?? "");
  const isZone = isZoneClassification(String(p.source ?? ""), status);
  const zoneLabel = isZone ? zoneLabelFor(String(p.source ?? ""), status) : null;
  const badgeStyle = isZone
    ? "text-slate-400 border-slate-500/40"
    : type === "offshore_wind" ? "text-sky-300 border-sky-500/40"
    : type === "seabed_mining" ? "text-fuchsia-300 border-fuchsia-500/40"
    : type === "ccs_storage"   ? "text-emerald-300 border-emerald-500/40"
    : "text-red-300 border-red-500/40";
  const typeLabel = zoneLabel ?? (
    type === "ccs_storage" ? "CCS Storage" : tEnum(t, "offshoreType", type || "oil_gas")
  );
  const sourceName: Record<string, string> = {
    emodnet:               "EMODnet Human Activities",
    boem:                  "BOEM (USA)",
    crown_estate:          "The Crown Estate (UK)",
    crown_estate_scotland: "Crown Estate Scotland",
    nopta:                 "NOPTA (Australia)",
    nzpam:                 "NZP&M (New Zealand)",
    anp:                   "ANP (Brazil)",
    sodir:                 "Sodir (Norway)",
    nsta:                  "NSTA (UK North Sea)",
    cnh:                   "CNH / PEMEX (Mexico)",
    esdm:                  "ESDM (Indonesia)",
    pasa:                  "PASA (South Africa)",
    mra_png:               "MRA Papua New Guinea",
    mme_nam:               "MME Namibia",
    sbma_ck:               "SBMA Cook Islands",
    cnsopb:                "CNSOPB (Canada – Nova Scotia)",
    cnlopb:                "C-NLOPB (Canada – Newfoundland & Labrador)",
    dea_dk:                "GEUS / DEA (Denmark North Sea)",
    sodir_co2:             "Sodir (Norway CCS)",
    nsta_co2:              "NSTA (UK Carbon Storage)",
    anh_co:                "ANH (Colombia)",
    meei_tt:               "MEEI / IMA (Trinidad & Tobago)",
    petrocom_gh:           "Petroleum Commission (Ghana)",
    pmp_gy:                "Petroleum Mgmt Programme (Guyana)",
    pad_ie:                "Petroleum Affairs Division (Ireland)",
    perupetro_pe:          "PERUPETRO (Peru)",
  };
  const src = String(p.source ?? "");
  const thumbColor = isZone
    ? "rgb(148 163 184)"  // slate-400 to match map rendering
    : type === "offshore_wind" ? "rgb(56 189 248)"
    : type === "seabed_mining" ? "rgb(217 70 239)"
    : type === "ccs_storage"   ? "rgb(16 185 129)"
    : "rgb(220 38 38)";
  const clickLon = typeof p._lon === "number" ? p._lon : undefined;
  const clickLat = typeof p._lat === "number" ? p._lat : undefined;

  return (
    <>
      <Badge label={typeLabel} color={badgeStyle} />
      <PanelHeader>{String(p.name ?? p.source_id ?? "—")}</PanelHeader>
      <PolygonThumbnail geometry={p.geometry} clickLon={clickLon} clickLat={clickLat} fillRgb={thumbColor} />
      <Section title={t("offshore.concessionDetailsSectionTitle")}>
        {p.operator        != null && <Row label={t("offshore.operatorLabel")}      value={String(p.operator)} />}
        {p.licence_holder  != null && String(p.licence_holder).trim() !== String(p.operator ?? "").trim() && (
          <Row label={t("offshore.licenceHolderLabel")} value={String(p.licence_holder)} />
        )}
        {p.sovereign       != null && <Row label={t("offshore.jurisdictionLabel")} value={String(p.sovereign)} />}
        {p.status          != null && <Row label={t("offshore.statusLabel")}       value={<span className="capitalize">{tEnum(t, "status", String(p.status))}</span>} />}
        {p.licence_type    != null && <Row label={t("offshore.licenceTypeLabel")}  value={<span className="capitalize">{String(p.licence_type).toLowerCase()}</span>} />}
        {p.area_km2        != null && <Row label={t("offshore.areaLabel")}         value={`${(p.area_km2 as number).toLocaleString()} km²`} />}
        {p.basin           != null && <Row label={t("offshore.basinLabel")}        value={String(p.basin)} />}
        {p.water_depth_m   != null && <Row label={t("offshore.waterDepthLabel")}   value={`${Math.round(p.water_depth_m as number).toLocaleString()} m`} />}
        {p.water_depth_m  == null && p.water_zone != null && <Row label={t("offshore.depthClassLabel")} value={String(p.water_zone)} />}
        {clickLat != null && clickLon != null && <SeafloorDepthRow lat={clickLat} lon={clickLon} />}
        {p.licensing_round != null && <Row label={t("offshore.roundLabel")}        value={String(p.licensing_round)} />}
        {p.awarded_date    != null && <Row label={t("offshore.awardedLabel")}      value={String(p.awarded_date).slice(0, 10)} />}
        {p.expires_date    != null && <Row label={t("offshore.expiresLabel")}      value={String(p.expires_date).slice(0, 10)} />}
        {p.source_id       != null && <Row label={t("offshore.registryIdLabel")}   value={<span className="font-mono text-xs">{String(p.source_id)}</span>} />}
      </Section>
      {p?.id != null && <BathymetryConfidenceBlock featureType="offshore_activity" fid={String(p.id)} />}
      <SourceAttribution
        link={offshoreSourceLink(p)}
        fallback={`Source: ${sourceName[src] ?? src}`}
      />
    </>
  );
}


