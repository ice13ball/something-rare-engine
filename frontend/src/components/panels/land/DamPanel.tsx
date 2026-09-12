// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function DamPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const name = String(p.dam_name ?? "").trim();
  const gdwId = p.gdw_id != null ? String(p.gdw_id) : "";

  // ⛔ GDW v1.0 (figshare doi:10.6084/m9.figshare.25988293, CC BY 4.0) replaced
  // GOODD here on 2026-09-11. GOODD published four fields and its numeric
  // DAM_ID was rendered where a name belonged on all 38,667 rows.
  //
  // GDW carries real attributes, but it is NOT complete, and three quarters of
  // its barriers still have no name. Measured over all 41,145 loaded rows:
  //     country 41,145 (100%) · capacity 35,334 (86%) · year 15,229 (37%)
  //     NAME    10,071 (24.5%) · river 9,501 (23%) · height 9,311 (23%)
  //     power      242 (0.6%)
  // So a nameless point is the COMMON case, not a failure. It gets the GDW id
  // as a heading and a line saying the source names only a quarter of them —
  // never a blank panel that reads like a broken fetch.
  //
  // ⛔ Every -99 in GDW is a no-data code and is stored as NULL by the loader
  // (power_mw 40,903 of them, dam_hgt_m 31,834, year_dam 25,915). Nothing here
  // should ever render one; if "-99 m" appears, the loader regressed.
  const has = (v: unknown) => v != null && v !== "";

  return (
    <>
      <Badge label={t("dam.panelBadge")} color="text-indigo-300 border-indigo-500/40" />
      <PanelHeader>{name || (gdwId ? t("dam.gdwIdHeader", { id: gdwId }) : "—")}</PanelHeader>
      <Section title={t("dam.detailsSectionTitle")}>
        {has(gdwId)         && <Row label={t("dam.gdwIdLabel")}      value={gdwId} />}
        {has(p.river)       && <Row label={t("dam.riverLabel")}      value={String(p.river)} />}
        {has(p.country)     && <Row label={t("dam.countryLabel")}    value={String(p.country)} />}
        {has(p.main_basin)  && <Row label={t("dam.basinLabel")}      value={String(p.main_basin)} />}
        {has(p.dam_type)    && <Row label={t("dam.damTypeLabel")}    value={String(p.dam_type)} />}
        {has(p.height_m)    && <Row label={t("dam.heightLabel")}     value={`${p.height_m} m`} />}
        {has(p.purpose)     && <Row label={t("dam.purposeLabel")}    value={String(p.purpose)} />}
        {has(p.year_built)  && <Row label={t("dam.yearBuiltLabel")}  value={String(p.year_built)} />}
        {has(p.volume_mcm)  && <Row label={t("dam.volumeLabel")}     value={`${Number(p.volume_mcm).toLocaleString()} MCM`} />}
        {has(p.area_skm)    && <Row label={t("dam.areaLabel")}       value={`${Number(p.area_skm).toLocaleString()} km²`} />}
        {has(p.power_mw)    && <Row label={t("dam.powerLabel")}      value={`${Number(p.power_mw).toLocaleString()} MW`} />}
        {has(p.grand_id)    && <Row label={t("dam.grandIdLabel")}    value={String(p.grand_id)} />}
      </Section>
      {/* A nameless barrier is the majority case in GDW. Say so, so that an
          absent name never reads as a fetch that failed. */}
      {!name && (
        <p className="text-xs text-white/65 italic mt-1">{t("dam.unnamedNote")}</p>
      )}
      <SourceAttribution link={sourceLinkFor("global-dam-watch", p)} />
      <ExternalLinks>
        {/* A Wikipedia search only works when there is a name to search for. */}
        {name && <ExternalLink href={`https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(name + " dam")}`} label="Wikipedia" />}
        <ExternalLink href="https://www.globaldamwatch.org" label="Global Dam Watch" />
      </ExternalLinks>
    </>
  );
}
