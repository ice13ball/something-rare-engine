// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { latLonFromProps } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, BodyText, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

export function SeamountPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const height = p.height_m != null ? Number(p.height_m) : null;
  const depth = p.summit_depth_m != null ? Number(p.summit_depth_m) : null;
  const area = p.area_km2 != null ? Number(p.area_km2) : null;
  const inConc = Boolean(p.in_concession);
  const in2011 = Boolean(p.in_2011);
  const overlapping = Boolean(p.overlapping_base);

  // Classify by height
  let sizeClass = "Medium";
  if (height != null) {
    if (height >= 3000) sizeClass = "Major";
    else if (height >= 2000) sizeClass = "Large";
    else if (height >= 1500) sizeClass = "Medium";
    else sizeClass = "Small";
  }

  return (
    <>
      <PanelHeader>{t("seamount.panelTitleWithId", { peakId: String(p.peak_id ?? "") })}</PanelHeader>
      <Subtitle className={`mb-4 ${inConc ? "text-orange-400" : "text-sky-400"}`}>
        {inConc
          ? t("seamount.subtitleWithinConcession", { size: tEnum(t, "seamountSize", sizeClass) })
          : t("seamount.subtitleOutsideConcession", { size: tEnum(t, "seamountSize", sizeClass) })}
      </Subtitle>
      <Section title={t("seamount.physicalSectionTitle")}>
        <Row label={t("seamount.heightLabel")}      value={height != null ? `${height.toLocaleString()} m` : "—"} />
        <Row label={t("seamount.summitDepthLabel")} value={depth != null ? t("seamount.summitDepthValue", { depth: depth.toLocaleString() }) : "—"} />
        <Row label={t("seamount.baseAreaLabel")}    value={area != null ? `${area.toLocaleString()} km²` : "—"} />
        <Row label={t("seamount.sizeClassLabel")}   value={tEnum(t, "seamountSize", sizeClass)} />
        {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
      </Section>
      <Section title={t("seamount.catalogueSectionTitle")}>
        <Row label={t("seamount.peakIdLabel")}     value={String(p.peak_id ?? "—")} />
        <Row label={t("seamount.catalogueLabel")}  value={in2011 ? t("seamount.catalogueValueBoth") : t("seamount.catalogueValueNew")} />
        <Row label={t("seamount.baseOverlapLabel")} value={overlapping ? t("seamount.baseOverlapYes") : t("seamount.baseOverlapNo")} />
        <Row label={t("seamount.bathymetryLabel")} value="SRTM v.11 (15 arc-sec)" />
      </Section>
      <BodyText>
        {inConc ? t("seamount.bodyInConcession") : t("seamount.bodyOutside")}
      </BodyText>
      <SourceAttribution link={sourceLinkFor("yesson-seamounts", p)} />
    </>
  );
}

