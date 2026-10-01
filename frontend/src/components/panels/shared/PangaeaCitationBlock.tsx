// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, HintText } from "./primitives";
import type { PangaeaVersion } from "./usePangaeaWaterMeta";

/** Citation, related publication, DOI, licence and version — every string as the
 *  source file and JSON-LD publish it (served by /v1/pangaea-water/meta), never
 *  retyped. The DOI falls back to the layer's constant while meta is loading. */
export function PangaeaCitationBlock({ version, doiFallback }: { version: PangaeaVersion | null; doiFallback: string }) {
  const { t } = useTranslation(["panels"]);
  const doi = version?.doi ?? doiFallback;
  return (
    <Section title={t("pangaeaWater.citation")}>
      {version?.citation && <HintText>{version.citation}</HintText>}
      {version?.related_citation && <HintText>{t("pangaeaWater.related")}: {version.related_citation}</HintText>}
      <Row label="DOI" value={<a href={`https://doi.org/${doi}`} target="_blank" rel="noopener noreferrer" className="text-cyan-400">{doi}</a>} />
      {version?.license && (
        <Row label={t("pangaeaWater.licence")}
             value={<a href={version.license} target="_blank" rel="noopener noreferrer" className="text-cyan-400">{version.license}</a>} />
      )}
      {version && (
        <HintText>{t("pangaeaWater.version", { date: version.date_published ?? "—", sha: version.sha256.slice(0, 12) })}</HintText>
      )}
      <HintText>{t("pangaeaWater.dataAge")}</HintText>
    </Section>
  );
}
